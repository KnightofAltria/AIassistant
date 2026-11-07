#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机服务与账号认证服务之间的客户端（仅标准库）。

浏览器不直接接触 token：登录后 token 只保存在本机 data/session.json，
由 server.py 通过本模块代为校验、刷新、退出。规格见
文档/登录注册方案/登录注册与本地部署流程.md 第 6 节。
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_SERVER = "http://127.0.0.1:8740"
VERIFY_INTERVAL = 5 * 60          # 距上次在线校验超过这么久才再问认证服务
OFFLINE_GRACE = 7 * 24 * 3600     # 认证服务不可达时，最多继续使用多久
TIMEOUT = 3.0


class AuthFailed(Exception):
    """认证服务明确拒绝（密码错、token 失效、用户名重复等）。"""

    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class AuthUnavailable(Exception):
    """认证服务连不上 / 超时 / 返回的不是预期格式。"""


def resolve_server(cli_value: str, data_dir: Path) -> str:
    """优先级：--auth-server > CSLA_AUTH_SERVER > data/client.json > 默认。"""
    if cli_value:
        return cli_value.rstrip("/")
    env = os.environ.get("CSLA_AUTH_SERVER", "").strip()
    if env:
        return env.rstrip("/")
    cfg = data_dir / "client.json"
    if cfg.is_file():
        try:
            value = json.loads(cfg.read_text(encoding="utf-8")).get("auth_server", "")
            if value:
                return str(value).rstrip("/")
        except (ValueError, OSError):
            pass
    return DEFAULT_SERVER


class AuthClient:
    def __init__(self, base_url: str, session_path: Path, timeout: float = TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.session_path = Path(session_path)
        self.timeout = timeout
        self.lock = threading.RLock()
        self.offline = False
        self.notice = ""              # 给界面看的一句话，例如"离线超过 7 天，请重新登录"
        self._checked_at = 0.0
        self.session = self._load()

    # ------------------------------------------------------------ 会话文件
    def _load(self) -> dict | None:
        try:
            data = json.loads(self.session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not data.get("tokens") or not data.get("user"):
            return None
        return data

    def _save(self) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.session_path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.session, fh, ensure_ascii=False)
        os.replace(str(tmp), str(self.session_path))

    def _clear(self, notice: str = "") -> None:
        self.session = None
        self.offline = False
        self.notice = notice
        try:
            self.session_path.unlink()
        except OSError:
            pass

    # ------------------------------------------------------------ HTTP
    def _call(self, method: str, path: str, body: dict | None = None, token: str = "") -> dict:
        data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
        req = urllib.request.Request(self.base_url + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "CSLA-Client/1.0")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            try:
                err = json.loads(exc.read().decode("utf-8")).get("error") or {}
            except (ValueError, AttributeError):
                err = {}
            if not err.get("code"):
                raise AuthUnavailable(f"认证服务返回异常（HTTP {exc.code}）")
            raise AuthFailed(err["code"], err.get("message") or "认证失败", exc.code)
        except (urllib.error.URLError, socket.timeout, ConnectionError, ssl.SSLError,
                OSError) as exc:
            raise AuthUnavailable(str(getattr(exc, "reason", exc)))
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise AuthUnavailable("认证服务返回的不是 JSON")

    # ------------------------------------------------------------ 状态
    @property
    def user(self) -> dict | None:
        return self.session["user"] if self.session else None

    @property
    def logged_in(self) -> bool:
        return bool(self.session)

    def status(self) -> dict:
        return {"enabled": True, "logged_in": self.logged_in, "user": self.user,
                "offline": self.offline and self.logged_in, "auth_server": self.base_url,
                "notice": self.notice}

    def verify(self, force: bool = False) -> None:
        """在线校验当前会话；必要时刷新。失效则清会话，连不上则进入离线宽限。"""
        with self.lock:
            if not self.session:
                return
            if not force and time.time() - self._checked_at < VERIFY_INTERVAL:
                return
            self._checked_at = time.time()
            tokens = self.session["tokens"]
            try:
                try:
                    if tokens.get("access_expires_at", 0) > time.time() + 30:
                        data = self._call("GET", "/auth/me", token=tokens["access_token"])
                        self.session["user"] = data["user"]
                    else:
                        self._refresh()
                except AuthFailed as exc:
                    if exc.code != "token_invalid":
                        raise
                    self._refresh()          # access 被认为过期（如时钟偏差），用 refresh 再试一次
            except AuthFailed as exc:
                self._clear(exc.message)
                return
            except AuthUnavailable:
                self.offline = True
                if time.time() - self.session.get("last_verified", 0) > OFFLINE_GRACE:
                    self._clear("已离线超过 7 天，请在能连上认证服务时重新登录")
                return
            self.offline = False
            self.notice = ""
            self.session["last_verified"] = time.time()
            self._save()

    def _refresh(self) -> None:
        data = self._call("POST", "/auth/refresh",
                          {"refresh_token": self.session["tokens"]["refresh_token"]})
        self.session["user"] = data["user"]
        self.session["tokens"] = data["tokens"]

    # ------------------------------------------------------------ 操作
    def register(self, username: str, password: str, nickname: str = "") -> dict:
        return self._call("POST", "/auth/register",
                          {"username": username, "password": password, "nickname": nickname})

    def login(self, username: str, password: str) -> dict:
        data = self._call("POST", "/auth/login", {"username": username, "password": password,
                                                  "device": device_name()})
        with self.lock:
            self.session = {"user": data["user"], "tokens": data["tokens"],
                            "last_verified": time.time()}
            self.offline = False
            self.notice = ""
            self._checked_at = time.time()
            self._save()
        return data["user"]

    def logout(self) -> None:
        """先尽量通知认证服务撤销；连不上也照样清掉本机会话。"""
        with self.lock:
            if self.session:
                try:
                    self._call("POST", "/auth/logout",
                               token=self.session["tokens"]["access_token"])
                except (AuthFailed, AuthUnavailable):
                    pass
            self._clear()

    def change_password(self, old_password: str, new_password: str) -> None:
        with self.lock:
            if not self.session:
                raise AuthFailed("auth_required", "请先登录", 401)
            if self.session["tokens"].get("access_expires_at", 0) <= time.time() + 30:
                self._refresh()
                self._save()
            self._call("POST", "/auth/password",
                       {"old_password": old_password, "new_password": new_password},
                       token=self.session["tokens"]["access_token"])

    def update_nickname(self, nickname: str) -> dict:
        with self.lock:
            if not self.session:
                raise AuthFailed("auth_required", "请先登录", 401)
            if self.session["tokens"].get("access_expires_at", 0) <= time.time() + 30:
                self._refresh()
            data = self._call("POST", "/auth/profile", {"nickname": nickname},
                              token=self.session["tokens"]["access_token"])
            self.session["user"] = data["user"]
            self._save()
            return data["user"]

    def _access(self) -> str:
        """当前可用的 access token；快过期就先刷新。调用方需持有 self.lock。"""
        if not self.session:
            raise AuthFailed("auth_required", "请先登录", 401)
        if self.session["tokens"].get("access_expires_at", 0) <= time.time() + 30:
            self._refresh()
            self._save()
        return self.session["tokens"]["access_token"]

    def sessions(self) -> list[dict]:
        with self.lock:
            return self._call("GET", "/auth/sessions", token=self._access())["sessions"]

    def revoke_sessions(self, session_id: str = "", others: bool = False) -> int:
        body = {"others": True} if others else {"session_id": session_id}
        with self.lock:
            return int(self._call("POST", "/auth/sessions/revoke", body,
                                  token=self._access()).get("revoked") or 0)

    def delete_account(self, password: str) -> str:
        """认证服务删除成功后清掉本机会话，返回被删账号的 ID。"""
        with self.lock:
            data = self._call("POST", "/auth/delete", {"password": password},
                              token=self._access())
            self._clear()
            return str(data.get("user_id") or "")

    # 管理员：认证服务会再校验一次角色，这里只是转发
    def admin_users(self) -> list[dict]:
        with self.lock:
            return self._call("GET", "/auth/admin/users", token=self._access())["users"]

    def admin_action(self, action: str, username: str, password: str = "") -> dict:
        body = {"action": action, "username": username}
        if password:
            body["password"] = password
        with self.lock:
            return self._call("POST", "/auth/admin/users", body, token=self._access())["user"]


def device_name() -> str:
    """设备列表里显示的名字：主机名 + 系统，例如 "DESKTOP-01 · Windows"。"""
    host = socket.gethostname().split(".")[0] or "本机"
    system = {"nt": "Windows", "posix": "macOS" if sys.platform == "darwin" else "Linux"}
    return f"{host} · {system.get(os.name, os.name)}"[:60]
