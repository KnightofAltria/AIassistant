#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号认证服务（仅标准库）。

只负责账号、密码哈希、登录会话，不接触学习数据和模型请求。
规格见 文档/登录注册方案/登录注册与本地部署流程.md。

启动：
    python auth_server.py                          # 127.0.0.1:8740
    python auth_server.py --host 0.0.0.0           # 局域网
    python auth_server.py --cert a.pem --key b.pem # 直接 HTTPS

管理（只在本机命令行做，不开放网络接口）：
    python auth_server.py users
    python auth_server.py disable <用户名>
    python auth_server.py enable <用户名>
    python auth_server.py reset-password <用户名>
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import ssl
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / "data" / "auth.db"

ACCESS_TTL = 2 * 3600
REFRESH_TTL = 30 * 24 * 3600
PBKDF2_ITERATIONS = int(os.environ.get("CSLA_PBKDF2_ITERATIONS") or 200_000)
MAX_BODY = 16 * 1024

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,20}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL,
    username_key TEXT NOT NULL UNIQUE,
    nickname TEXT DEFAULT '',
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_login_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    access_hash TEXT NOT NULL UNIQUE,
    refresh_hash TEXT NOT NULL UNIQUE,
    access_expires INTEGER NOT NULL,
    refresh_expires INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0,
    user_agent TEXT DEFAULT '',
    ip TEXT DEFAULT '',
    device TEXT DEFAULT '',
    login_at TEXT DEFAULT '',
    last_seen TEXT DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""
# 老库补列：device 是客户端自报的设备名；login_at 是这台设备最初登录的时间，
# 刷新轮换时跟着新会话走，所以设备列表里看到的是"何时登录"而不是"何时刷新"
SESSION_COLUMNS = ("device", "login_at", "last_seen")


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class AuthError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------------------------------------------------------------- 密码哈希
def hash_password(password: str, iterations: int = 0) -> str:
    iterations = iterations or PBKDF2_ITERATIONS
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, 32)
    return "pbkdf2_sha256${}${}${}".format(
        iterations, base64.b64encode(salt).decode(), base64.b64encode(digest).decode())


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, iterations, salt_b64, hash_b64 = encoded.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                     int(iterations), len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


# 用户不存在时也算一次哈希，让两种失败耗时接近
_DUMMY_HASH = hash_password("dummy-password-0")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- 输入校验
def check_username(username) -> str:
    if not isinstance(username, str) or not USERNAME_RE.match(username):
        raise AuthError("invalid_input", "用户名需为 3–20 位字母、数字或下划线", 400)
    return username


def check_password(password, field: str = "密码") -> str:
    if not isinstance(password, str) or not 8 <= len(password) <= 64:
        raise AuthError("invalid_input", f"{field}长度需为 8–64 位", 400)
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AuthError("invalid_input", f"{field}需同时包含字母和数字", 400)
    return password


def check_nickname(nickname) -> str:
    if nickname is None:
        return ""
    if not isinstance(nickname, str):
        raise AuthError("invalid_input", "昵称格式不正确", 400)
    nickname = nickname.strip()
    if len(nickname) > 20:
        raise AuthError("invalid_input", "昵称最多 20 个字", 400)
    return nickname


# ---------------------------------------------------------------- 频率限制
class RateLimiter:
    """滑动窗口计数，进程内有效。"""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def _prune(self, key: str, window: float) -> deque:
        q = self.hits[key]
        cutoff = time.time() - window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, key: str, limit: int, window: float) -> bool:
        with self.lock:
            return len(self._prune(key, window)) >= limit

    def add(self, key: str) -> None:
        with self.lock:
            self.hits[key].append(time.time())

    def clear(self, key: str) -> None:
        with self.lock:
            self.hits.pop(key, None)


LOGIN_WINDOW = 15 * 60
LOGIN_USER_LIMIT = 5
LOGIN_IP_LIMIT = 20
REGISTER_WINDOW = 3600
REGISTER_IP_LIMIT = 10


# ---------------------------------------------------------------- 账号库
class AuthStore:
    def __init__(self, db_path: Path | str = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        have = {row["name"] for row in self.conn.execute("PRAGMA table_info(sessions)")}
        for name in SESSION_COLUMNS:
            if name not in have:
                self.conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} TEXT DEFAULT ''")
        self.conn.commit()
        self.lock = threading.Lock()
        self.limiter = RateLimiter()

    @staticmethod
    def public_user(row) -> dict:
        return {"id": row["id"], "username": row["username"], "nickname": row["nickname"] or "",
                "status": row["status"], "created_at": row["created_at"]}

    def _user_by_name(self, username: str):
        return self.conn.execute("SELECT * FROM users WHERE username_key=?",
                                 (username.lower(),)).fetchone()

    def _new_session(self, user_id: str, user_agent: str = "", ip: str = "",
                     device: str = "", login_at: str = "") -> dict:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        t, ts = int(time.time()), now_text()
        tokens = {"access_token": access, "access_expires_at": t + ACCESS_TTL,
                  "refresh_token": refresh, "refresh_expires_at": t + REFRESH_TTL}
        self.conn.execute(
            "INSERT INTO sessions(id,user_id,access_hash,refresh_hash,access_expires,"
            "refresh_expires,created_at,user_agent,ip,device,login_at,last_seen) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), user_id, token_hash(access), token_hash(refresh),
             tokens["access_expires_at"], tokens["refresh_expires_at"], ts,
             user_agent[:200], ip[:64], device[:60], login_at or ts, ts))
        return tokens

    def _revoke_user_sessions(self, user_id: str, keep_session: str = "") -> None:
        self.conn.execute("UPDATE sessions SET revoked=1 WHERE user_id=? AND id<>?",
                          (user_id, keep_session))

    # ------------------------------------------------------------ 业务
    def register(self, body: dict, ip: str = "") -> dict:
        if self.limiter.blocked(f"reg-ip:{ip}", REGISTER_IP_LIMIT, REGISTER_WINDOW):
            raise AuthError("rate_limited", "注册过于频繁，请稍后再试", 429)
        username = check_username(body.get("username"))
        password = check_password(body.get("password"))
        nickname = check_nickname(body.get("nickname"))
        pw_hash = hash_password(password)
        with self.lock:
            if self._user_by_name(username):
                raise AuthError("username_taken", "该用户名已被注册", 409)
            uid, ts = str(uuid.uuid4()), now_text()
            self.conn.execute(
                "INSERT INTO users(id,username,username_key,nickname,password_hash,status,"
                "created_at,updated_at) VALUES(?,?,?,?,?,'active',?,?)",
                (uid, username, username.lower(), nickname, pw_hash, ts, ts))
            self.conn.commit()
            self.limiter.add(f"reg-ip:{ip}")
            row = self.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        return {"user": self.public_user(row)}

    def login(self, body: dict, ip: str = "", user_agent: str = "") -> dict:
        username, password = body.get("username"), body.get("password")
        if not isinstance(username, str) or not isinstance(password, str) \
                or not username or not password:
            raise AuthError("invalid_input", "请填写用户名和密码", 400)
        user_key = f"login-user:{username.lower()}"
        ip_key = f"login-ip:{ip}"
        if self.limiter.blocked(user_key, LOGIN_USER_LIMIT, LOGIN_WINDOW) or \
                self.limiter.blocked(ip_key, LOGIN_IP_LIMIT, LOGIN_WINDOW):
            raise AuthError("rate_limited", "登录失败次数过多，请 15 分钟后再试", 429)
        row = self._user_by_name(username)
        ok = verify_password(password, row["password_hash"] if row else _DUMMY_HASH)
        if not row or not ok:
            self.limiter.add(user_key)
            self.limiter.add(ip_key)
            raise AuthError("invalid_credentials", "用户名或密码错误", 401)
        if row["status"] != "active":
            raise AuthError("account_disabled", "该账号已被禁用，请联系管理员", 403)
        self.limiter.clear(user_key)
        device = body.get("device") if isinstance(body.get("device"), str) else ""
        with self.lock:
            tokens = self._new_session(row["id"], user_agent, ip, device.strip())
            self.conn.execute("UPDATE users SET last_login_at=? WHERE id=?",
                              (now_text(), row["id"]))
            self.conn.commit()
        return {"user": self.public_user(row), "tokens": tokens}

    def session_for_access(self, access: str):
        """返回 (session, user)；无效时抛 token_invalid / account_disabled。"""
        if not access:
            raise AuthError("token_invalid", "登录已失效，请重新登录", 401)
        sess = self.conn.execute("SELECT * FROM sessions WHERE access_hash=?",
                                 (token_hash(access),)).fetchone()
        if not sess or sess["revoked"] or sess["access_expires"] < time.time():
            raise AuthError("token_invalid", "登录已失效，请重新登录", 401)
        user = self.conn.execute("SELECT * FROM users WHERE id=?", (sess["user_id"],)).fetchone()
        if not user:
            raise AuthError("token_invalid", "登录已失效，请重新登录", 401)
        if user["status"] != "active":
            raise AuthError("account_disabled", "该账号已被禁用，请联系管理员", 403)
        return sess, user

    def me(self, access: str) -> dict:
        sess, user = self.session_for_access(access)
        with self.lock:
            self.conn.execute("UPDATE sessions SET last_seen=? WHERE id=?", (now_text(), sess["id"]))
            self.conn.commit()
        return {"user": self.public_user(user)}

    def refresh(self, body: dict, ip: str = "", user_agent: str = "") -> dict:
        refresh = body.get("refresh_token")
        if not isinstance(refresh, str) or not refresh:
            raise AuthError("invalid_input", "缺少 refresh_token", 400)
        with self.lock:
            sess = self.conn.execute("SELECT * FROM sessions WHERE refresh_hash=?",
                                     (token_hash(refresh),)).fetchone()
            if not sess or sess["revoked"] or sess["refresh_expires"] < time.time():
                raise AuthError("token_invalid", "登录已失效，请重新登录", 401)
            user = self.conn.execute("SELECT * FROM users WHERE id=?",
                                     (sess["user_id"],)).fetchone()
            if not user or user["status"] != "active":
                raise AuthError("account_disabled", "该账号已被禁用，请联系管理员", 403)
            # 轮换：旧会话作废，签发新的一对；设备名和首次登录时间沿用
            self.conn.execute("UPDATE sessions SET revoked=1 WHERE id=?", (sess["id"],))
            tokens = self._new_session(user["id"], user_agent, ip, sess["device"] or "",
                                       sess["login_at"] or sess["created_at"])
            self.conn.commit()
        return {"user": self.public_user(user), "tokens": tokens}

    def logout(self, access: str) -> dict:
        if access:
            with self.lock:
                self.conn.execute("UPDATE sessions SET revoked=1 WHERE access_hash=?",
                                  (token_hash(access),))
                self.conn.commit()
        return {"ok": True}

    def change_password(self, access: str, body: dict) -> dict:
        sess, user = self.session_for_access(access)
        old = body.get("old_password")
        if not isinstance(old, str) or not verify_password(old, user["password_hash"]):
            raise AuthError("invalid_credentials", "原密码错误", 401)
        new = check_password(body.get("new_password"), "新密码")
        if new == old:
            raise AuthError("invalid_input", "新密码不能与原密码相同", 400)
        pw_hash = hash_password(new)
        with self.lock:
            self.conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                              (pw_hash, now_text(), user["id"]))
            self._revoke_user_sessions(user["id"], keep_session=sess["id"])
            self.conn.commit()
        return {"ok": True}

    def update_profile(self, access: str, body: dict) -> dict:
        """目前只允许改昵称；用户名注册后不可改。"""
        _, user = self.session_for_access(access)
        nickname = check_nickname(body.get("nickname"))
        with self.lock:
            self.conn.execute("UPDATE users SET nickname=?, updated_at=? WHERE id=?",
                              (nickname, now_text(), user["id"]))
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
        return {"user": self.public_user(row)}

    # ------------------------------------------------------------ 设备 / 注销
    def list_sessions(self, access: str) -> dict:
        """当前账号仍有效的登录（每台设备一条），current 标出发起请求的这台。"""
        sess, user = self.session_for_access(access)
        rows = self.conn.execute(
            "SELECT * FROM sessions WHERE user_id=? AND revoked=0 AND refresh_expires>=? "
            "ORDER BY id=? DESC, last_seen DESC",
            (user["id"], int(time.time()), sess["id"])).fetchall()
        return {"sessions": [{
            "id": r["id"], "device": r["device"] or "未命名设备", "ip": r["ip"] or "",
            "login_at": r["login_at"] or r["created_at"],
            "last_seen": r["last_seen"] or r["created_at"],
            "current": r["id"] == sess["id"]} for r in rows]}

    def revoke_sessions(self, access: str, body: dict) -> dict:
        """body.session_id 退出指定设备；body.others=true 退出除本机以外的全部设备。"""
        sess, user = self.session_for_access(access)
        with self.lock:
            if body.get("others") is True:
                cur = self.conn.execute(
                    "UPDATE sessions SET revoked=1 WHERE user_id=? AND id<>? AND revoked=0",
                    (user["id"], sess["id"]))
            else:
                sid = body.get("session_id")
                if not isinstance(sid, str) or not sid:
                    raise AuthError("invalid_input", "缺少 session_id", 400)
                if sid == sess["id"]:
                    raise AuthError("invalid_input", "要退出本机请直接点“退出登录”", 400)
                cur = self.conn.execute(
                    "UPDATE sessions SET revoked=1 WHERE user_id=? AND id=? AND revoked=0",
                    (user["id"], sid))
                if not cur.rowcount:
                    raise AuthError("not_found", "该设备已经下线", 404)
            self.conn.commit()
        return {"ok": True, "revoked": cur.rowcount}

    def delete_account(self, access: str, body: dict) -> dict:
        """注销账号：校验密码后删除账号与全部会话。用户名随之释放，可被重新注册。"""
        _, user = self.session_for_access(access)
        # 与登录共用失败计数：拿到别人的会话也不能借这里无限试密码
        key = f"login-user:{user['username_key']}"
        if self.limiter.blocked(key, LOGIN_USER_LIMIT, LOGIN_WINDOW):
            raise AuthError("rate_limited", "密码错误次数过多，请 15 分钟后再试", 429)
        password = body.get("password")
        if not isinstance(password, str) or not verify_password(password, user["password_hash"]):
            self.limiter.add(key)
            raise AuthError("invalid_credentials", "密码错误", 401)
        with self.lock:
            self.conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            self.conn.execute("DELETE FROM users WHERE id=?", (user["id"],))
            self.conn.commit()
        self.limiter.clear(key)
        return {"ok": True, "user_id": user["id"]}

    # ------------------------------------------------------------ 管理
    def list_users(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
        return [dict(self.public_user(r), last_login_at=r["last_login_at"]) for r in rows]

    def set_status(self, username: str, status: str) -> bool:
        row = self._user_by_name(username)
        if not row:
            return False
        with self.lock:
            self.conn.execute("UPDATE users SET status=?, updated_at=? WHERE id=?",
                              (status, now_text(), row["id"]))
            if status != "active":
                self._revoke_user_sessions(row["id"])
            self.conn.commit()
        return True

    def reset_password(self, username: str, password: str) -> bool:
        row = self._user_by_name(username)
        if not row:
            return False
        check_password(password)
        pw_hash = hash_password(password)
        with self.lock:
            self.conn.execute("UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                              (pw_hash, now_text(), row["id"]))
            self._revoke_user_sessions(row["id"])
            self.conn.commit()
        return True


# ---------------------------------------------------------------- HTTP
class QuietHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError,
                            ssl.SSLError)):
            return
        super().handle_error(request, client_address)


def make_handler(store: AuthStore, verbose: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CSLA-Auth/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            # 只记方法和路径，请求体（密码、token）永不进日志
            if verbose:
                super().log_message(fmt, *args)

        def _json(self, payload: dict, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise AuthError("invalid_input", "请求过大", 400)
            if not length:
                return {}
            try:
                data = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise AuthError("invalid_input", "请求不是合法 JSON", 400)
            if not isinstance(data, dict):
                raise AuthError("invalid_input", "请求不是合法 JSON", 400)
            return data

        def _bearer(self) -> str:
            value = self.headers.get("Authorization") or ""
            return value[7:].strip() if value.startswith("Bearer ") else ""

        def _ip(self) -> str:
            return self.client_address[0] if self.client_address else ""

        def _dispatch(self, method: str) -> None:
            path = self.path.split("?", 1)[0]
            ua = self.headers.get("User-Agent") or ""
            try:
                if method == "GET" and path == "/auth/health":
                    self._json({"ok": True, "time": int(time.time())})
                elif method == "GET" and path == "/auth/me":
                    self._json(store.me(self._bearer()))
                elif method == "POST" and path == "/auth/register":
                    self._json(store.register(self._body(), self._ip()), 201)
                elif method == "POST" and path == "/auth/login":
                    self._json(store.login(self._body(), self._ip(), ua))
                elif method == "POST" and path == "/auth/refresh":
                    self._json(store.refresh(self._body(), self._ip(), ua))
                elif method == "POST" and path == "/auth/logout":
                    self._json(store.logout(self._bearer()))
                elif method == "POST" and path == "/auth/password":
                    self._json(store.change_password(self._bearer(), self._body()))
                elif method == "POST" and path == "/auth/profile":
                    self._json(store.update_profile(self._bearer(), self._body()))
                elif method == "GET" and path == "/auth/sessions":
                    self._json(store.list_sessions(self._bearer()))
                elif method == "POST" and path == "/auth/sessions/revoke":
                    self._json(store.revoke_sessions(self._bearer(), self._body()))
                elif method == "POST" and path == "/auth/delete":
                    self._json(store.delete_account(self._bearer(), self._body()))
                else:
                    raise AuthError("not_found", "接口不存在", 404)
            except AuthError as exc:
                self._json({"error": {"code": exc.code, "message": exc.message}}, exc.status)
            except Exception:                         # noqa: BLE001
                self._json({"error": {"code": "server_error", "message": "认证服务内部错误"}}, 500)

        def do_GET(self) -> None:      # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:     # noqa: N802
            self._dispatch("POST")

    return Handler


def build_server(store: AuthStore, host: str, port: int, cert: str = "", key: str = "",
                 verbose: bool = False) -> QuietHTTPServer:
    httpd = QuietHTTPServer((host, port), make_handler(store, verbose))
    if cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key or None)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    return httpd


# ---------------------------------------------------------------- 命令行
def admin(args, store: AuthStore) -> int:
    if args.cmd == "users":
        users = store.list_users()
        if not users:
            print("还没有账号")
        for u in users:
            print(f"{u['username']:<20} {u['status']:<9} 昵称={u['nickname'] or '-':<10} "
                  f"注册={u['created_at']}  最近登录={u['last_login_at'] or '-'}")
        return 0
    if args.cmd in ("disable", "enable"):
        ok = store.set_status(args.username, "disabled" if args.cmd == "disable" else "active")
        print(("已禁用并撤销全部会话：" if args.cmd == "disable" else "已启用：") + args.username
              if ok else f"找不到用户：{args.username}")
        return 0 if ok else 1
    if args.cmd == "reset-password":
        password = getpass.getpass("新密码（8–64 位，含字母和数字）：")
        if password != getpass.getpass("再输一次："):
            print("两次输入不一致")
            return 1
        try:
            ok = store.reset_password(args.username, password)
        except AuthError as exc:
            print(exc.message)
            return 1
        print(f"已重置并撤销全部会话：{args.username}" if ok else f"找不到用户：{args.username}")
        return 0 if ok else 1
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="计算机课程学习助手 · 账号认证服务")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="账号数据库路径")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("users", help="列出账号")
    for name in ("disable", "enable", "reset-password"):
        sub.add_parser(name).add_argument("username")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8740)
    ap.add_argument("--cert", default="", help="TLS 证书（PEM），提供则启用 HTTPS")
    ap.add_argument("--key", default="", help="TLS 私钥（PEM）")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    store = AuthStore(args.db)
    if args.cmd:
        return admin(args, store)

    try:
        httpd = build_server(store, args.host, args.port, args.cert, args.key, args.verbose)
    except OSError as exc:
        print(f"启动失败：端口 {args.port} 不可用（{exc}）")
        return 2
    scheme = "https" if args.cert else "http"
    print("=" * 56)
    print("  账号认证服务")
    print(f"  地址：{scheme}://{args.host}:{args.port}")
    print(f"  数据库：{store.db_path}")
    if not args.cert and args.host not in ("127.0.0.1", "localhost"):
        print("  注意：未启用 HTTPS，密码以明文经过网络，仅适合局域网演示")
    print("=" * 56)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
