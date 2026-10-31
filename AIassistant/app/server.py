#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计算机课程学习助手 —— 本地服务（仅标准库，无第三方依赖）。

启动：
    python server.py                 # 默认 127.0.0.1:8737，需先启动 ../auth_server/auth_server.py
    python server.py --port 9000
    python server.py --mock          # 离线演示模式，不需要 API Key
    python server.py --no-auth       # 跳过登录（单用户，仅开发调试）

启动后在浏览器打开 http://127.0.0.1:8737 ，先登录 / 注册，再填写 DeepSeek API Key 进入。
所有数据保存在本文件所在目录的 data/ 下，按账号分在 data/users/<用户ID>/，可随时删除。
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import mimetypes
import re
import shutil
import sqlite3
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from os import _exit
from pathlib import Path

import auth_client
import deepseek
import extras
import prompts
import rag
import seed
import tools
from store import DATA_DIR, Store

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"


class AuthRequired(Exception):
    """未登录时访问了需要账号数据的接口。"""


class CurrentStore:
    """当前登录账号的 Store。登录、退出、切换账号时用 bind() 替换。

    tools、extras 等拿到的都是这个代理，切换账号时不用改它们。

    Store 只有一条 sqlite 连接，而 HTTP 服务是多线程的：页面加载时浏览器会并发发
    好几个请求，交错执行会让事务卡在未提交状态，之后所有写操作都报
    "database is locked"。所以经代理调用的 Store 方法一律串行执行。
    """

    def __init__(self):
        self._store: Store | None = None
        self._lock = threading.RLock()

    def bind(self, store: Store | None) -> None:
        with self._lock:
            self._store = store

    @property
    def bound(self) -> bool:
        return self._store is not None

    def __getattr__(self, name: str):
        store = self.__dict__.get("_store")
        if store is None:
            raise AuthRequired()
        attr = getattr(store, name)
        if not callable(attr):
            return attr
        lock = self.__dict__["_lock"]

        def locked(*args, **kwargs):
            with lock:
                return attr(*args, **kwargs)
        return locked


STORE = CurrentStore()
LOCK = threading.Lock()

# ---------------------------------------------------------------- 登录与按账号隔离
# 规格见 文档/登录注册方案/登录注册与本地部署流程.md 第 6 节
USERS_DIR = DATA_DIR / "users"
LEGACY_MARK = USERS_DIR / ".legacy_migrated"
AUTH: auth_client.AuthClient | None = None      # None 表示 --no-auth 单用户模式
CURRENT_UID = ""
# 未登录也能访问的接口
OPEN_PATHS = {"/api/state", "/api/heartbeat", "/api/client-closed"}


def init_store(store: Store) -> tuple[int, int]:
    """内置科目、标准文件夹、示例资料；返回（导入示例数，归位数）。"""
    seed.seed(store)
    seed.ensure_folders(store)
    samples = seed.seed_samples(store) + seed.import_shared_samples(store)
    return samples, seed.reorganize(store)


def adopt_legacy_data(user_dir: Path) -> bool:
    """升级前的 data/csla.db 归第一个在本机登录的账号所有。"""
    if LEGACY_MARK.exists():
        return False
    USERS_DIR.mkdir(parents=True, exist_ok=True)
    legacy_db = DATA_DIR / "csla.db"
    moved = False
    if legacy_db.is_file() and not (user_dir / "csla.db").exists():
        user_dir.mkdir(parents=True, exist_ok=True)
        for name in ("csla.db", "csla.db-journal", "csla.db-wal", "csla.db-shm",
                     "materials", "profile"):
            src = DATA_DIR / name
            if src.exists():
                shutil.move(str(src), str(user_dir / name))
        conn = sqlite3.connect(str(user_dir / "csla.db"))
        old_prefix, new_prefix = str(DATA_DIR / "materials"), str(user_dir / "materials")
        conn.execute("UPDATE materials SET path = ? || substr(path, ?) WHERE path LIKE ?",
                     (new_prefix, len(old_prefix) + 1, old_prefix + "%"))
        conn.commit()
        conn.close()
        moved = True
    LEGACY_MARK.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
    return moved


def activate_user(user: dict) -> None:
    """切到某个账号的数据目录；同一账号重复调用不做事。"""
    global CURRENT_UID
    uid = str(user.get("id") or "")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", uid):
        raise ValueError("认证服务返回的用户 ID 不合法")
    with LOCK:
        if CURRENT_UID == uid and STORE.bound:
            return
        user_dir = USERS_DIR / uid
        if adopt_legacy_data(user_dir):
            print(f"  已把升级前的本地数据迁移给账号 {user.get('username')}")
        store = Store(user_dir / "csla.db", data_dir=user_dir)
        init_store(store)
        local = store.ensure_user()
        # 显示名以账号昵称为准（可能在别的电脑上改过）；没设昵称时才用用户名兜底
        nickname = user.get("nickname") or ""
        if nickname and local.get("name") != nickname:
            store.set_meta({"name": nickname})
        elif not nickname and local.get("name") in ("", "本机用户"):
            store.set_meta({"name": user.get("username") or "本机用户"})
        STORE.bind(store)
        CURRENT_UID = uid
        reset_caches()


def deactivate_user() -> None:
    global CURRENT_UID
    with LOCK:
        STORE.bind(None)
        CURRENT_UID = ""
        reset_caches()


def sync_auth(force: bool = False) -> None:
    """按需在线校验会话，并让当前数据目录与登录状态一致。"""
    if AUTH is None:
        return
    AUTH.verify(force=force)
    if AUTH.logged_in:
        activate_user(AUTH.user)
    elif STORE.bound:
        deactivate_user()


def auth_status() -> dict:
    if AUTH is None:
        return {"enabled": False, "logged_in": True, "user": None, "offline": False,
                "auth_server": "", "notice": ""}
    return AUTH.status()


# ---------------------------------------------------------------- 浏览器心跳 / 自动退出
CLIENT = {"seen": False, "last_seen": time.time(), "visible": True, "close_at": 0.0}
CLIENT_LOCK = threading.Lock()
EXIT_ON_CLOSE = False
IDLE_VISIBLE = 25.0        # 页面可见时的空闲上限（秒）
IDLE_HIDDEN = 300.0        # 页面切到后台时的空闲上限
CLOSE_GRACE = 6.0          # 收到"页面关闭"信号后的宽限，用于躲过刷新


def touch_client(visible: bool | None = None, closing: bool = False) -> None:
    with CLIENT_LOCK:
        CLIENT["seen"] = True
        CLIENT["last_seen"] = time.time()
        if visible is not None:
            CLIENT["visible"] = bool(visible)
        CLIENT["close_at"] = time.time() if closing else 0.0


def watchdog(httpd) -> None:
    """没有页面在用了就自动停服，避免留下后台进程。"""
    while True:
        time.sleep(2.0)
        with CLIENT_LOCK:
            now = time.time()
            gap = now - CLIENT["last_seen"]
            limit = IDLE_VISIBLE if CLIENT["visible"] else IDLE_HIDDEN
            close_at = CLIENT["close_at"]
            seen = CLIENT["seen"]
        if not seen:
            # 还没有任何页面连上来（比如浏览器还没开），不要急着退出
            continue
        if close_at and gap > CLOSE_GRACE:
            print("\n浏览器已关闭，服务自动停止。")
            _exit(0)
        if gap > limit:
            print(f"\n已有 {int(gap)} 秒没有页面连接，服务自动停止。")
            _exit(0)
_RETRIEVER: rag.Retriever | None = None
_RETRIEVER_VERSION = -1


# ---------------------------------------------------------------- 检索缓存
def get_retriever() -> rag.Retriever:
    """检索器缓存：用索引版本号判断是否需要重建。

    早期版本用"切片数量"当版本，内容变了但切片数不变（例如重抓后段落数恰好一致）
    就不会重建，回答会一直引用旧内容。现在版本号由 Store 在任何资料/切片/审核
    变动时显式 +1，见 store.rev() / store.bump()。
    """
    global _RETRIEVER, _RETRIEVER_VERSION
    version = STORE.rev()
    if _RETRIEVER is None or _RETRIEVER_VERSION != version:
        _RETRIEVER = rag.Retriever(STORE.all_chunks())
        _RETRIEVER_VERSION = version
    return _RETRIEVER


def reset_caches() -> None:
    """切换账号后检索器和回答缓存都属于上一个账号，必须丢掉。"""
    global _RETRIEVER, _RETRIEVER_VERSION
    _RETRIEVER = None
    _RETRIEVER_VERSION = -1
    _ANSWER_CACHE.clear()


def client() -> deepseek.DeepSeekClient:
    cfg = STORE.get_config()
    return deepseek.DeepSeekClient(cfg.get("api_key", ""), cfg.get("model", deepseek.DEFAULT_MODEL))


def refine_threshold() -> float:
    """拒答阈值可在设置里调；改小更容易硬答，改大更容易说"资料不足"。"""
    try:
        value = STORE.get_config().get("refuse_threshold") or rag.INSUFFICIENCY_FLOOR
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return rag.INSUFFICIENCY_FLOOR


def rag_context(query: str, subject: str = "", k: int = 8) -> rag.RagContext:
    """检索并组装证据。科目未知时先自动路由，命中不到再回退全库。"""
    retriever = get_retriever()
    routed = subject or rag.route_subject(retriever, query)
    hits, queries = rag.search_multi(retriever, query, k=k, subject=routed or None)
    if not hits and routed:
        hits, queries = rag.search_multi(retriever, query, k=k)   # 本科目无资料，回退全库
        routed = ""
    floor = refine_threshold()
    evidence, citations = rag.build_evidence(hits)
    return rag.RagContext(query=query, subject=routed, hits=hits, evidence=evidence,
                          citations=citations, queries=queries, threshold=floor,
                          insufficient=rag.insufficient_evidence(hits, query, floor=floor))


def log_usage(kind: str, messages: list[dict], completion: str,
              first_ms: int = 0, total_ms: int = 0, ok: bool = True) -> None:
    """把一次模型调用记进 usage_log；统计页读的就是这张表。"""
    prompt_chars = sum(len(m.get("content") or "") for m in messages)
    completion_chars = len(completion or "")
    tokens = rag.estimate_tokens(
        "".join(m.get("content") or "" for m in messages) + (completion or ""))
    try:
        STORE.record_usage(kind, STORE.get_config().get("model", deepseek.DEFAULT_MODEL),
                           prompt_chars, completion_chars, tokens,
                           first_ms, total_ms, ok)
    except Exception:                                  # noqa: BLE001 - 统计失败不影响主流程
        pass


# ---------------------------------------------------------------- HTTP 处理
class QuietHTTPServer(ThreadingHTTPServer):
    """浏览器刷新、关闭标签时会重置连接，这属于正常现象，不要打印一长串堆栈。

    Windows 下几乎每次刷新都会触发 WinError 10054，堆栈会把控制台刷满，
    演示时看起来像程序出错了，所以在这里统一静音。
    """

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    server_version = "CSLA/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ 基础工具
    def log_message(self, fmt: str, *args) -> None:      # 安静一点
        if "--verbose" in getattr(self.server, "flags", []):
            super().log_message(fmt, *args)

    def _json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400, **extra) -> None:
        self._json({"error": {"message": message, **extra}}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _sse(self, event: str, data: dict) -> None:
        chunk = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self.wfile.write(chunk.encode("utf-8"))
        self.wfile.flush()

    # ------------------------------------------------------------ 路由
    def _need_login(self, path: str) -> bool:
        """未登录访问账号数据接口时直接回 401，返回 True 表示已拦截。"""
        if not path.startswith("/api/") or path in OPEN_PATHS or path.startswith("/api/auth/"):
            return False
        if STORE.bound:
            return False
        self._error("请先登录", 401, code="auth_required")
        return True

    def do_GET(self) -> None:      # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if self._need_login(path):
                return
            if path.startswith("/api/"):
                self._api_get(path, query)
            else:
                self._static(path)
        except AuthRequired:
            self._error("请先登录", 401, code="auth_required")
        except Exception as exc:                      # noqa: BLE001
            self._error(f"服务器内部错误：{exc}", 500)

    def do_POST(self) -> None:     # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if self._need_login(parsed.path):
                return
            self._api_post(parsed.path, self._body())
        except AuthRequired:
            self._error("请先登录", 401, code="auth_required")
        except deepseek.DeepSeekError as exc:
            self._error(str(exc), 502, retryable=exc.retryable)
        except Exception as exc:                      # noqa: BLE001
            self._error(f"服务器内部错误：{exc}", 500)

    def do_PATCH(self) -> None:    # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            if self._need_login(parsed.path):
                return
            self._api_post(parsed.path, self._body())
        except AuthRequired:
            self._error("请先登录", 401, code="auth_required")
        except deepseek.DeepSeekError as exc:
            self._error(str(exc), 502, retryable=exc.retryable)
        except Exception as exc:                      # noqa: BLE001
            self._error(f"服务器内部错误：{exc}", 500)

    def do_DELETE(self) -> None:   # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if self._need_login(parsed.path):
                return
            self._api_delete(parsed.path, query)
        except AuthRequired:
            self._error("请先登录", 401, code="auth_required")
        except Exception as exc:                      # noqa: BLE001
            self._error(f"删除失败：{exc}", 500)

    # ------------------------------------------------------------ 静态文件
    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._error("资源不存在", 404)
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------ GET API
    def _api_get(self, path: str, query: dict) -> None:
        if path == "/api/state":
            sync_auth()
            auth = auth_status()
            if not STORE.bound:
                self._json({"configured": False, "mock": deepseek.MOCK, "auth": auth})
                return
            cfg = STORE.get_config()
            self._json({
                "configured": STORE.has_api_key() or deepseek.MOCK,
                "mock": deepseek.MOCK,
                "masked_key": STORE.mask_key(),
                "model": cfg.get("model", deepseek.DEFAULT_MODEL),
                "user": STORE.ensure_user(),
                "avatar": STORE.avatar_version(),
                "stats": STORE.stats(),
                "pending_summary": _pending_summary(),
                "auth": auth,
            })
            return

        if path == "/api/auth/status":
            sync_auth()
            self._json(auth_status())
            return

        if path == "/api/profile":
            user = STORE.ensure_user()
            self._json({"profile": user.get("profile", ""),
                        "files": STORE.list_profiles(),
                        "meta": STORE.get_meta(),
                        "user": user.get("name", ""),
                        "avatar": STORE.avatar_version()})
            return

        if path == "/api/profile/avatar":
            self._serve_avatar()
            return

        m = re.fullmatch(r"/api/profile/([\w-]+)(/download)?", path)
        if m:
            try:
                text = STORE.read_profile(m.group(1))
            except ValueError as exc:
                self._error(str(exc), 400)
                return
            if not text:
                self._error("该月份没有档案", 404)
                return
            if m.group(2):
                self._download(text.encode("utf-8"), f"学习者档案-{m.group(1)}.md",
                               "text/markdown; charset=utf-8")
            else:
                self._json({"month": m.group(1), "content": text})
            return

        if path == "/api/subjects":
            self._json({"subjects": STORE.subjects()})
            return

        m = re.fullmatch(r"/api/chapters/([\w-]+)", path)
        if m:
            chapter = STORE.chapter(m.group(1))
            if not chapter:
                self._error("章节不存在", 404)
                return
            self._json({"chapter": chapter, "questions": STORE.questions(chapter["id"]),
                        "stats": STORE.chapter_stats(chapter["id"])})
            return

        if path == "/api/conversations":
            self._json({"conversations": STORE.list_conversations()})
            return

        m = re.fullmatch(r"/api/conversations/([\w-]+)/messages", path)
        if m:
            self._json({"messages": STORE.messages(m.group(1))})
            return

        if path == "/api/summaries":
            kind = query.get("kind", [None])[0]
            conv = query.get("conversation", [""])[0]
            items = STORE.list_summaries(kind)
            if conv:
                items = [x for x in items if x.get("conversation_id") == conv]
            self._json({"summaries": items})
            return

        if path == "/api/mistakes":
            self._json({"mistakes": STORE.list_mistakes()})
            return

        if path == "/api/materials/pending":
            self._json({"materials": STORE.pending_materials(),
                        "stale": STORE.stale_materials()})
            return

        m = re.fullmatch(r"/api/materials/([\w-]+)/raw", path)
        if m:
            self._serve_raw(m.group(1))
            return

        m = re.fullmatch(r"/api/materials/([\w-]+)", path)
        if m:
            self._material_detail(m.group(1))
            return

        if path == "/api/materials":
            folder = query.get("folder", [""])[0]
            materials = STORE.list_materials(folder if folder else None)
            folders = STORE.list_folders()
            subject_names = {s["name"] for s in STORE.subjects()}
            for f in folders:
                # 内置文件夹、科目同名文件夹不允许改名（见 /api/folders/<id>/rename）
                f["renamable"] = not f.get("slug") and f["name"] not in subject_names
            fmap = {f["id"]: f for f in folders}
            for mat in materials:
                f = fmap.get(mat.get("folder_id", ""), {})
                mat["folder_name"] = f.get("name", "")
                mat["folder_shared"] = bool(f.get("is_shared"))
            self._json({"materials": materials, "folders": folders})
            return

        if path == "/api/rag/search":
            q = query.get("q", [""])[0]
            subject = query.get("subject", [""])[0]
            ctx = rag_context(q, subject)
            self._json(ctx.as_dict())
            return

        # ---- 扩展：学习看板 / 复习队列 / 用量 / 全文检索 / 报告导出
        if path == "/api/dashboard":
            self._json(self._dashboard())
            return

        if path == "/api/review":
            due_only = query.get("due", [""])[0] in ("1", "true")
            self._json({"reviews": STORE.list_reviews(due_only=due_only, limit=100),
                        "due": STORE.due_review_count()})
            return

        if path == "/api/usage":
            try:
                days = int(query.get("days", ["14"])[0] or 14)
            except ValueError:
                days = 14
            self._json(STORE.usage_stats(days=max(1, min(days, 365))))
            return

        if path == "/api/search":
            q = query.get("q", [""])[0]
            try:
                k = int(query.get("k", ["8"])[0] or 8)
            except ValueError:
                k = 8
            self._json(self._public_search(q, max(1, min(k, 20))))
            return

        if path == "/api/graph":
            self._json(self._graph())
            return

        if path == "/api/activity":
            try:
                weeks = int(query.get("weeks", ["12"])[0] or 12)
            except ValueError:
                weeks = 12
            self._json(STORE.activity_map(weeks=max(1, min(weeks, 52))))
            return

        if path == "/api/export/report":
            data = extras.build_report(STORE)
            self._download(data, f"学习报告-{time.strftime('%Y%m%d')}.docx")
            return

        self._error("未知接口", 404)

    # ------------------------------------------------------------ POST API
    def _api_post(self, path: str, body: dict) -> None:
        # ---- 登录注册（转发给认证服务，token 只留在本机服务）
        if path.startswith("/api/auth/"):
            self._auth_post(path, body)
            return

        # ---- 配置 API Key
        if path == "/api/config":
            key = (body.get("api_key") or "").strip()
            model = body.get("model") or deepseek.DEFAULT_MODEL
            probe = deepseek.DeepSeekClient(key, model)
            result = probe.validate()            # 失败会抛 DeepSeekError
            with LOCK:
                STORE.set_config("api_key", key)
                STORE.set_config("model", model)
                if body.get("refuse_threshold") is not None:
                    try:
                        STORE.set_config("refuse_threshold",
                                         str(max(0.0, float(body["refuse_threshold"]))))
                    except (TypeError, ValueError):
                        pass
            self._json({"ok": True, "models": result.get("models", []), "mock": deepseek.MOCK})
            return

        # ---- 浏览器心跳：页面还开着就续期，页面关了就开始倒计时
        if path == "/api/heartbeat":
            touch_client(visible=body.get("visible", True))
            self._json({"ok": True})
            return

        if path == "/api/client-closed":
            touch_client(closing=True)
            self._json({"ok": True})
            return

        # ---- 工具型 AI（资料管理 / 科目学习）
        if path == "/api/agent/stream":
            self._agent_stream(body)
            return

        # ---- 科目与章节管理
        if path == "/api/subjects":
            name = (body.get("name") or "").strip()
            if not name:
                self._error("科目名不能为空", 400)
                return
            try:
                subject = STORE.add_subject(name, is_builtin=False)
            except ValueError as exc:
                self._error(str(exc), 409)
                return
            # 新科目同时建一个同名资料文件夹，保持"资料按科目分文件夹"
            folder = STORE.folder_by_name(name) or STORE.add_folder(name, ord=50)
            videos = [v.strip() for v in (body.get("videos") or []) if v.strip()]
            saved = []
            for url in videos[:20]:
                text = (f"# 视频资料：{name}\n\n来源链接：{url}\n\n"
                        f"> 这是用户在创建科目「{name}」时粘贴的视频链接，供复习时跳转使用。\n")
                material = STORE.add_material(
                    title=f"视频 · {url[:60]}", text=text, subject=name,
                    folder_id=folder["id"], source_url=url, ext=".md")
                STORE.replace_chunks(material["id"], rag.chunk_text(text))
                saved.append(url)
            self._json({"subject": subject, "folder": folder, "videos": len(saved)}, 201)
            return

        m = re.fullmatch(r"/api/subjects/([\w-]+)/chapters", path)
        if m:
            title = (body.get("title") or "").strip()
            if not title:
                self._error("章节标题不能为空", 400)
                return
            try:
                chapter = STORE.add_chapter(m.group(1), title, body.get("outline", ""),
                                            is_builtin=False)
            except Exception as exc:               # noqa: BLE001
                self._error(f"新增章节失败：{exc}", 400)
                return
            self._json({"chapter": chapter}, 201)
            return

        m = re.fullmatch(r"/api/chapters/([\w-]+)", path)
        if m:
            STORE.update_chapter(m.group(1), body.get("title"), body.get("outline"))
            self._json({"ok": True})
            return

        m = re.fullmatch(r"/api/chapters/([\w-]+)/summary", path)
        if m:
            self._chapter_summary(m.group(1))
            return

        m = re.fullmatch(r"/api/chapters/([\w-]+)/videos", path)
        if m:
            self._chapter_videos(m.group(1))
            return

        # ---- 用户画像字段
        if path == "/api/profile/meta":
            meta = STORE.set_meta(body or {})
            self._json({"ok": True, "meta": meta}, 201)
            return

        # ---- 显示名 / 头像
        if path == "/api/profile/name":
            self._set_display_name(body)
            return

        if path == "/api/profile/avatar":
            try:
                data = base64.b64decode(str(body.get("content") or ""), validate=True)
            except binascii.Error:
                self._error("头像数据无效", 400)
                return
            try:
                version = STORE.save_avatar(data)
            except ValueError as exc:
                self._error(str(exc), 400)
                return
            self._json({"ok": True, "avatar": version}, 201)
            return

        # ---- 用户档案
        if path == "/api/profile/generate":
            self._generate_profile(body.get("month") or None)
            return

        # ---- 易错提示本
        if path == "/api/mistakes/tips":
            self._mistake_tips()
            return

        # ---- 对话（SSE 流式）
        if path == "/api/chat/stream":
            self._chat_stream(body)
            return

        # ---- 会话管理
        if path == "/api/conversations":
            conv = STORE.create_conversation(body.get("title") or "新对话")
            self._json({"conversation": conv}, 201)
            return

        m = re.fullmatch(r"/api/conversations/([\w-]+)/rename", path)
        if m:
            STORE.rename_conversation(m.group(1), body.get("title") or "未命名")
            self._json({"ok": True})
            return

        # ---- 生成近期总结
        if path == "/api/summaries/generate":
            cid = body.get("conversation_id") or ""
            messages = STORE.messages(cid) if cid else []
            if not messages:
                self._error("该会话没有消息，无法总结", 400)
                return
            transcript = "\n".join(f"{m['role']}：{m['content'][:600]}" for m in messages[-20:])
            text = client().complete(
                [{"role": "system", "content": prompts.SUMMARY_SYSTEM},
                 {"role": "user", "content": transcript}], max_tokens=900)
            title = messages[0]["content"][:24] or "近期总结"
            item = STORE.add_summary("recent", title, text, cid)
            # 同时更新用户画像
            try:
                profile = client().complete(
                    [{"role": "system", "content": prompts.PROFILE_SYSTEM},
                     {"role": "user", "content": transcript}], max_tokens=500)
                STORE.update_profile(profile)
            except deepseek.DeepSeekError:
                pass
            self._json({"summary": item}, 201)
            return

        # ---- 章节讲解（流式）
        m = re.fullmatch(r"/api/chapters/([\w-]+)/tutor", path)
        if m:
            self._chapter_tutor(m.group(1), body)
            return

        # ---- 生成题目
        m = re.fullmatch(r"/api/chapters/([\w-]+)/questions/generate", path)
        if m:
            self._generate_questions(m.group(1), int(body.get("n") or 3))
            return

        # ---- 判分
        if path == "/api/attempts":
            self._attempt(body)
            return

        # ---- 资料
        if path == "/api/materials":
            title = (body.get("title") or "").strip()
            text = body.get("text") or ""
            if not title or not text.strip():
                self._error("标题与内容都不能为空", 400)
                return
            material = STORE.add_material(
                title=title, text=text, subject=body.get("subject", ""),
                folder_id=body.get("folder_id", ""), source_url=body.get("source_url", ""))
            chunks = rag.chunk_text(text)
            STORE.replace_chunks(material["id"], chunks)
            self._json({"material": material, "chunks": len(chunks)}, 201)
            return

        if path == "/api/folders":
            name = (body.get("name") or "").strip()
            if not name:
                self._error("文件夹名不能为空", 400)
                return
            if STORE.folder_by_name(name):
                self._error("同名文件夹已存在", 409)
                return
            folder = STORE.add_folder(name, is_shared=bool(body.get("is_shared")))
            self._json({"folder": folder}, 201)
            return

        m = re.fullmatch(r"/api/folders/([\w-]+)/rename", path)
        if m:
            folder = STORE.folder(m.group(1))
            name = (body.get("name") or "").strip()
            if not folder:
                self._error("文件夹不存在", 404)
                return
            if folder.get("slug"):
                # 内置文件夹按 slug 识别，启动时会被 seed 改回标准名，改了也留不住
                self._error("内置文件夹不能改名", 403)
                return
            if any(s["name"] == folder["name"] for s in STORE.subjects()):
                # 科目与资料文件夹按同名对应（建科目、抓取资料都靠它），改名会脱钩
                self._error(f"这是科目「{folder['name']}」的资料文件夹，不能单独改名", 403)
                return
            if not name or len(name) > 40:
                self._error("文件夹名需为 1–40 个字", 400)
                return
            other = STORE.folder_by_name(name)
            if other and other["id"] != folder["id"]:
                self._error("同名文件夹已存在", 409)
                return
            STORE.rename_folder(folder["id"], name)
            self._json({"ok": True, "folder": STORE.folder(folder["id"])})
            return

        m = re.fullmatch(r"/api/materials/([\w-]+)/move", path)
        if m:
            folder_id = body.get("folder_id") or ""
            if not STORE.material(m.group(1)):
                self._error("资料不存在", 404)
                return
            if folder_id and not STORE.folder(folder_id):
                self._error("目标文件夹不存在", 404)
                return
            STORE.move_material(m.group(1), folder_id)
            self._json({"ok": True})
            return

        # ---- 扩展：复习评分 / 上传导入 / 审核 / 重抓 / 变式题 / 费曼
        if path == "/api/review/grade":
            quality = (body.get("quality") or "good").strip()
            if quality not in ("again", "good", "easy"):
                self._error("quality 只能是 again / good / easy", 400)
                return
            item = STORE.grade_review(body.get("id") or "", quality)
            if not item:
                self._error("复习条目不存在", 404)
                return
            self._json({"review": item, "due": STORE.due_review_count(),
                        "next": extras.srs_label(item["stage"])})
            return

        if path == "/api/materials/import":
            self._import_upload(body)
            return

        m = re.fullmatch(r"/api/materials/([\w-]+)/status", path)
        if m:
            item = STORE.set_material_status(m.group(1), body.get("status") or "approved")
            if not item:
                self._error("资料不存在", 404)
                return
            self._json({"material": item})
            return

        m = re.fullmatch(r"/api/materials/([\w-]+)/refresh", path)
        if m:
            self._refresh_material(m.group(1))
            return

        m = re.fullmatch(r"/api/mistakes/([\w-]+)/variant", path)
        if m:
            self._make_variant(m.group(1))
            return

        if path == "/api/feynman":
            self._feynman(body)
            return

        self._error("未知接口", 404)

    # ------------------------------------------------------------ 登录注册
    def _auth_post(self, path: str, body: dict) -> None:
        if AUTH is None:
            self._error("当前以 --no-auth 单用户模式运行，不需要登录", 400, code="auth_disabled")
            return
        username = str(body.get("username") or "").strip()
        password = body.get("password") if isinstance(body.get("password"), str) else ""
        try:
            if path == "/api/auth/login":
                user = AUTH.login(username, password)
                activate_user(user)
                self._json(auth_status())
                return
            if path == "/api/auth/register":
                AUTH.register(username, password, str(body.get("nickname") or "").strip())
                user = AUTH.login(username, password)      # 注册后直接进入
                activate_user(user)
                self._json(auth_status(), 201)
                return
            if path == "/api/auth/logout":
                AUTH.logout()
                deactivate_user()
                self._json(auth_status())
                return
            if path == "/api/auth/password":
                AUTH.change_password(str(body.get("old_password") or ""),
                                     str(body.get("new_password") or ""))
                self._json({"ok": True})
                return
        except auth_client.AuthFailed as exc:
            if path == "/api/auth/password" and exc.code in ("token_invalid", "account_disabled"):
                # 会话已被撤销或账号被禁用：清掉本机会话，前端据 auth_required 回登录页
                AUTH.logout()
                deactivate_user()
                self._error(exc.message, 401, code="auth_required")
                return
            # 其余（密码错误、用户名重复、格式不对、限流）原样透传，不影响当前登录
            self._error(exc.message, exc.status, code=exc.code)
            return
        except auth_client.AuthUnavailable as exc:
            self._error(f"认证服务不可达（{AUTH.base_url}）：{exc}", 503,
                        code="auth_unavailable")
            return
        self._error("未知接口", 404)

    # ------------------------------------------------------------ DELETE API
    def _api_delete(self, path: str, query: dict | None = None) -> None:
        query = query or {}
        m = re.fullmatch(r"/api/subjects/([\w-]+)", path)
        if m:
            try:
                self._json({"ok": True, **STORE.delete_subject(m.group(1))})
            except PermissionError as exc:
                self._error(str(exc), 403)
            return

        m = re.fullmatch(r"/api/chapters/([\w-]+)", path)
        if m:
            result = STORE.delete_chapter(m.group(1))
            self._json({"ok": True, **result})
            return

        m = re.fullmatch(r"/api/profile/([\w-]+)", path)
        if m:
            if m.group(1) == "avatar":
                STORE.delete_avatar()
                self._json({"ok": True})
                return
            try:
                STORE.delete_profile(m.group(1))
            except ValueError as exc:
                self._error(str(exc), 400)
                return
            self._json({"ok": True})
            return

        m = re.fullmatch(r"/api/folders/([\w-]+)", path)
        if m:
            mode = query.get("mode", ["move"])[0]
            mode = "purge" if mode == "purge" else "move"
            result = STORE.delete_folder(m.group(1), mode)
            self._json({"ok": True, **result})
            return
        for pattern, action in (
            (r"/api/conversations/([\w-]+)", STORE.delete_conversation),
            (r"/api/materials/([\w-]+)", STORE.delete_material),
            (r"/api/summaries/([\w-]+)", STORE.delete_summary),
            (r"/api/mistakes/([\w-]+)", STORE.delete_mistake),
            (r"/api/questions/([\w-]+)", STORE.delete_question),
        ):
            m = re.fullmatch(pattern, path)
            if m:
                action(m.group(1))
                self._json({"ok": True})
                return
        self._error("未知接口", 404)

    # ------------------------------------------------------------ 业务：对话
    def _replay_cache(self, cid: str, ephemeral: bool, cached: dict) -> None:
        """命中缓存：不调模型，把上次的答案与检索详情按同样的事件序列重放一遍。"""
        payload = dict(cached.get("retrieval") or {})
        hits = payload.get("hits") or []
        self._sse_start()
        self._sse("status", {"stage": "retrieving", "conversation_id": cid,
                             "hits": len(hits),
                             "insufficient": payload.get("insufficient", False),
                             "subject": payload.get("subject", ""),
                             "top_score": payload.get("top_score", 0), "cached": True})
        self._sse("retrieval", {**payload, "cached": True})
        answer = cached.get("answer") or ""
        for i in range(0, len(answer), 12):
            self._sse("delta", {"text": answer[i:i + 12]})
        self._sse("status", {"stage": "verifying"})
        verification = cached.get("citations") or {}
        self._sse("citations", verification)
        mid = "" if ephemeral else STORE.add_message(cid, "assistant", answer,
                                                    verification.get("items") or [])
        try:
            STORE.record_usage("cache_hit", STORE.get_config().get("model", ""),
                               0, len(answer), 0, 0, 0)
        except Exception:                              # noqa: BLE001
            pass
        self._sse("completed", {"message_id": mid, "conversation_id": cid,
                                "status": "completed", "cached": True})

    def _chat_stream(self, body: dict) -> None:
        text = (body.get("text") or "").strip()
        if not text:
            self._error("消息不能为空", 400)
            return
        cid = body.get("conversation_id") or ""
        ephemeral = bool(body.get("ephemeral"))     # 章节内随手提问：不落会话记录
        if not ephemeral and not cid:
            conv = STORE.create_conversation(text[:20] or "新对话")
            cid = conv["id"]
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return

        history = [{"role": m["role"], "content": m["content"]}
                   for m in STORE.messages(cid)][-8:] if cid else []
        style = (body.get("style") or "concise").strip()
        used_query = resolve_query(text, history)     # 多轮指代："它 / 这个" 补上前一问
        ckey = cache_key(text, style, history)

        if not ephemeral:
            STORE.add_message(cid, "user", text)

        cached = cache_get(ckey)
        if cached:
            self._replay_cache(cid, ephemeral, cached)
            return

        ctx = rag_context(used_query)
        system = prompts.chat_system(style)
        meta_line = STORE.meta_summary()
        if meta_line:
            system += (f"\n\n学习者信息（供你调整讲解深浅与举例方式，不要主动复述这些信息）：{meta_line}")
        if ctx.evidence:
            system += f"\n\n参考资料（只能引用这些编号）：\n\n{ctx.evidence}"
        if ctx.insufficient:
            # 检索结果可疑时，宁可让模型少引用，也不要把无关资料当证据
            system += ("\n\n注意：本次检索到的资料与问题的相关性很低。"
                      "凡是与问题无关的资料，一律不要引用它的编号；"
                      "请明确说明「资料中没有找到足够依据」，再给出常识性补充并标明这是补充。")
        if ctx.subject:
            system += f"\n\n本次检索范围限定在科目：{ctx.subject}。"
        if used_query != text:
            system += (f"\n\n（本次追问已结合上文补全为：{used_query[:80]}。"
                       "回答时以学生这句话为主，不要把补全的内容当新问题。）")

        retrieval_payload = {
            "query": text, "resolved": used_query,
            "queries": ctx.queries or [used_query],
            "subject": ctx.subject, "insufficient": ctx.insufficient,
            "threshold": ctx.threshold, "top_score": round(ctx.top_score, 2),
            "style": style, "cached": False,
            "hits": [h.as_dict() for h in ctx.hits[:8]],
        }

        self._sse_start()
        self._sse("status", {"stage": "retrieving", "conversation_id": cid,
                             "hits": len(ctx.hits), "insufficient": ctx.insufficient,
                             "subject": ctx.subject, "top_score": round(ctx.top_score, 2)})
        # 检索详情：前端"凭什么这么答"面板直接用这个事件渲染，不额外再查一次
        self._sse("retrieval", retrieval_payload)
        collected: list[str] = []
        started = time.time()
        first_at = 0.0
        try:
            self._sse("status", {"stage": "generating"})
            for piece in client().stream_chat(
                    [{"role": "system", "content": system}, *history,
                     {"role": "user", "content": text}]):
                if not first_at:
                    first_at = time.time()
                collected.append(piece)
                self._sse("delta", {"text": piece})
            answer = "".join(collected)
            verification = rag.validate_citations(answer, ctx.citations, ctx.insufficient)
            self._sse("status", {"stage": "verifying"})
            self._sse("citations", verification)
            mid = "" if ephemeral else STORE.add_message(cid, "assistant", answer, verification["items"])
            cache_put(ckey, {"answer": answer, "citations": verification,
                             "retrieval": retrieval_payload})
            log_usage("chat", [{"content": system}, *history, {"content": text}], answer,
                      int((first_at - started) * 1000) if first_at else 0,
                      int((time.time() - started) * 1000))
            if not ephemeral:
                STORE.touch_activity()
            self._sse("completed", {"message_id": mid, "conversation_id": cid,
                                    "status": "completed", "cached": False})
        except deepseek.DeepSeekError as exc:
            log_usage("chat", [{"content": system}, {"content": text}], "", 0,
                      int((time.time() - started) * 1000), ok=False)
            self._sse("failed", {"code": exc.status or 0, "message": str(exc),
                                 "retryable": exc.retryable})
        except BrokenPipeError:
            return
        finally:
            try:
                self.wfile.flush()
            except Exception:                        # noqa: BLE001
                pass

    # ------------------------------------------------------------ 业务：章节
    def _chapter_tutor(self, chapter_id: str, body: dict) -> None:
        chapter = STORE.chapter(chapter_id)
        if not chapter:
            self._error("章节不存在", 404)
            return
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return
        ctx = rag_context(f"{chapter['title']} {chapter.get('outline', '')}",
                          subject=chapter.get("subject_name", ""))
        system = prompts.SUBJECT_TUTOR_SYSTEM.format(
            chapter=chapter["title"], subject=chapter["subject_name"])
        meta_line = STORE.meta_summary()
        if meta_line:
            system += f"\n\n学习者信息（用于调整讲解深浅）：{meta_line}"
        if ctx.evidence:
            system += f"\n\n参考资料（只能引用这些编号）：\n\n{ctx.evidence}"

        self._sse_start()
        self._sse("status", {"stage": "generating", "chapter_id": chapter_id})
        collected: list[str] = []
        started = time.time()
        try:
            for piece in client().stream_chat(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": f"请讲解本章：{chapter['title']}"}]):
                collected.append(piece)
                self._sse("delta", {"text": piece})
            answer = "".join(collected)
            log_usage("tutor", [{"content": system}], answer, 0,
                      int((time.time() - started) * 1000))
            STORE.set_outline(chapter_id, answer)
            verification = rag.validate_citations(answer, ctx.citations, ctx.insufficient)
            self._sse("citations", verification)
            self._sse("completed", {"status": "completed", "chapter_id": chapter_id})
        except deepseek.DeepSeekError as exc:
            self._sse("failed", {"code": exc.status or 0, "message": str(exc),
                                 "retryable": exc.retryable})

    def _generate_questions(self, chapter_id: str, n: int) -> None:
        chapter = STORE.chapter(chapter_id)
        if not chapter:
            self._error("章节不存在", 404)
            return
        n = max(1, min(n, 10))
        ctx = rag_context(f"{chapter['title']} 题目", subject=chapter.get("subject_name", ""))
        system = prompts.QUESTION_GEN_SYSTEM.format(n=n)
        user = f"章节：{chapter['title']}\n大纲：\n{chapter.get('outline', '')}\n"
        if ctx.evidence:
            user += f"\n参考资料：\n{ctx.evidence}"
        raw = client().complete([{"role": "system", "content": system},
                                 {"role": "user", "content": user}], max_tokens=1600)
        log_usage("questions", [{"content": system}, {"content": user}], raw)
        items = _parse_questions(raw)
        created = []
        for item in items[:n]:
            created.append(STORE.add_question(
                chapter_id, item.get("stem", ""), item.get("options", []),
                item.get("answer", ""), item.get("explanation", "")))
        self._json({"questions": created}, 201)

    def _attempt(self, body: dict) -> None:
        chapter_id = body.get("chapter_id", "")
        question_id = body.get("question_id", "")
        picked = (body.get("answer") or "").strip().upper()[:1]
        chapter = STORE.chapter(chapter_id) if chapter_id else None
        question = next((q for q in STORE.questions(chapter_id) if q["id"] == question_id), None)
        if not question:
            self._error("题目不存在", 404)
            return
        correct = question["answer"].strip().upper()[:1]
        ok = picked == correct
        STORE.record_attempt(chapter_id, question_id, picked, ok)
        subject_name = chapter["subject_name"] if chapter else ""
        chapter_title = chapter["title"] if chapter else ""
        if not ok:
            STORE.add_mistake(
                subject=subject_name, chapter=chapter_title,
                stem=question["stem"], my_answer=picked, right_answer=correct,
                note=question.get("explanation", ""))
            # 进错题本的同时排进复习队列，保证"错过一次就不会忘"这条闭环成立
            STORE.add_review(stem=question["stem"], answer=correct, subject=subject_name,
                             chapter=chapter_title, note=question.get("explanation", ""),
                             kind="mistake", ref_id=question_id)
        STORE.touch_activity()
        self._json({"correct": ok, "right_answer": correct,
                    "explanation": question.get("explanation", "")})


    # ------------------------------------------------------------ 业务：资料文件
    def _material_detail(self, material_id: str) -> None:
        materials = [m for m in STORE.list_materials() if m["id"] == material_id]
        if not materials:
            self._error("资料不存在", 404)
            return
        item = materials[0]
        text = STORE.get_material_text(material_id)
        self._json({"material": item, "content": text[:20000],
                    "path": item.get("path", ""), "exists": bool(text)})

    def _serve_raw(self, material_id: str) -> None:
        materials = [m for m in STORE.list_materials() if m["id"] == material_id]
        if not materials:
            self._error("资料不存在", 404)
            return
        item = materials[0]
        path = Path(item.get("path", ""))
        if not path.is_file():
            self._error("源文件已丢失（可能被手动删除）", 404)
            return
        data = path.read_bytes()
        suffix = path.suffix.lower()
        ctype = {".md": "text/plain; charset=utf-8", ".txt": "text/plain; charset=utf-8",
                 ".json": "application/json; charset=utf-8",
                 ".csv": "text/csv; charset=utf-8",
                 ".html": "text/html; charset=utf-8"}.get(suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------ 业务：显示名 / 头像
    def _set_display_name(self, body: dict) -> None:
        """显示名 = 账号昵称：本机库与认证服务各存一份，认证服务连不上时只改本机。"""
        name = str(body.get("name") or "").strip()
        if not name or len(name) > 20:
            self._error("显示名需为 1–20 个字", 400)
            return
        notice = ""
        if AUTH is not None:
            try:
                AUTH.update_nickname(name)
            except auth_client.AuthFailed as exc:
                self._error(exc.message, exc.status, code=exc.code)
                return
            except auth_client.AuthUnavailable:
                notice = "认证服务暂时连不上，显示名只在本机生效"
        STORE.set_meta({"name": name})
        self._json({"ok": True, "name": name, "notice": notice, "auth": auth_status()})

    def _serve_avatar(self) -> None:
        path = STORE.avatar_file()
        if not path:
            self._error("还没有设置头像", 404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png" if path.suffix == ".png" else "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


    # ------------------------------------------------------------ 业务：工具型 AI
    def _agent_stream(self, body: dict) -> None:
        """资料管理 / 科目学习里的 AI 对话框：模型调工具改软件。"""
        scope = body.get("scope") or "materials"
        if scope not in ("materials", "study"):
            self._error("未知场景", 400)
            return
        text = (body.get("text") or "").strip()
        if not text:
            self._error("指令不能为空", 400)
            return
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return

        system = (prompts.AGENT_MATERIALS_SYSTEM if scope == "materials"
                  else prompts.AGENT_STUDY_SYSTEM)
        ctx = tools.ToolContext(store=STORE, retriever_factory=get_retriever)
        specs = tools.tools_for_scope(scope)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": text}]

        self._sse_start()
        self._sse("status", {"stage": "thinking", "scope": scope})
        final, steps = "", 0
        try:
            for _round in range(5):
                msg = client().chat_with_tools(messages, specs)
                calls = msg.get("tool_calls") or []
                if not calls:
                    final = msg.get("content") or ""
                    break
                messages.append({"role": "assistant",
                                 "content": msg.get("content") or "",
                                 "tool_calls": calls})
                for call in calls:
                    fn = (call.get("function") or {}).get("name", "")
                    raw_args = (call.get("function") or {}).get("arguments") or "{}"
                    try:
                        args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        args = {}
                    result = tools.run_tool(scope, fn, args, ctx)
                    steps += 1
                    self._sse("step", {"tool": fn, "args": args,
                                       "ok": result.get("ok"),
                                       "need_confirm": result.get("need_confirm", False),
                                       "summary": result.get("summary", "")})
                    messages.append({"role": "tool",
                                     "tool_call_id": call.get("id", ""),
                                     "content": json.dumps(result, ensure_ascii=False)[:4000]})
            else:
                final = "动作有点多，我先停在这里。你可以让我继续，或者把要求说得更具体一些。"

            for i in range(0, len(final), 8):
                self._sse("delta", {"text": final[i:i + 8]})
            self._sse("completed", {"status": "completed", "steps": steps})
        except deepseek.DeepSeekError as exc:
            self._sse("failed", {"code": exc.status or 0, "message": str(exc),
                                 "retryable": exc.retryable})
        except BrokenPipeError:
            return

    # ------------------------------------------------------------ 业务：章节总结
    def _chapter_summary(self, chapter_id: str) -> None:
        chapter = STORE.chapter(chapter_id)
        if not chapter:
            self._error("章节不存在", 404)
            return
        stats = STORE.chapter_stats(chapter_id)
        if stats["attempts"] == 0:
            self._error("这一章还没有作答记录，先做几道题再总结", 400)
            return
        wrongs = STORE.wrong_questions(chapter_id)
        detail = "\n".join(
            f"- 题目：{w['stem'][:60]}；正确答案 {w['answer']}；你选了 {w['my_answer']}"
            for w in wrongs) or "（没有错题）"
        prompt = (f"章节：{chapter['subject_name']} / {chapter['title']}\n"
                  f"作答 {stats['attempts']} 题，正确 {stats['correct']} 题，"
                  f"正确率 {stats['rate']}%，错题 {stats['wrong']} 道。\n"
                  f"错题清单：\n{detail}\n\n"
                  "请给这位学生写一段本章学习小结，包含：掌握情况判断、错题暴露的薄弱点、"
                  "接下来 3 天该复习什么。控制在 300 字以内，中文，不要客套话。")
        text = client().complete([{"role": "user", "content": prompt}], max_tokens=700)
        log_usage("chapter_summary", [{"content": prompt}], text)
        saved = STORE.add_summary("chapter", f"{chapter['subject_name']} · {chapter['title']} 小结",
                                  text, "")
        self._json({"summary": saved, "stats": stats}, 201)

    # ------------------------------------------------------------ 业务：推荐学习视频
    def _chapter_videos(self, chapter_id: str) -> None:
        chapter = STORE.chapter(chapter_id)
        if not chapter:
            self._error("章节不存在", 404)
            return
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return
        prompt = (
            f"科目：{chapter['subject_name']}\n章节：{chapter['title']}\n"
            f"大纲：\n{chapter.get('outline', '')}\n\n"
            "请推荐 4 个适合本科生的学习视频方向。**只输出 JSON 数组**，不要代码块标记，元素格式：\n"
            '{"title": "视频主题（不要编造具体视频标题或BV号）", '
            '"platform": "哔哩哔哩 或 中国大学MOOC 或 其他", '
            '"keyword": "用于站内搜索的关键词", '
            '"reason": "为什么推荐它，20字以内"}\n'
            "严禁编造具体视频链接、BV 号或 UP 主名，只能给搜索关键词。")
        raw = client().complete([{"role": "user", "content": prompt}], max_tokens=900)
        videos = _parse_videos(raw)
        self._json({"videos": videos, "chapter": chapter["title"]})

    # ------------------------------------------------------------ 业务：用户档案
    def _generate_profile(self, month: str | None) -> None:
        summaries = STORE.list_summaries()[:10]
        convs = STORE.list_conversations()[:5]
        if not summaries and not convs:
            self._error("还没有足够的对话记录来生成画像", 400)
            return
        material = "\n\n".join(f"[{s['title']}]\n{s['content'][:800]}" for s in summaries)
        titles = "、".join(c["title"] for c in convs)
        meta_line = STORE.meta_summary()
        prompt = (f"学习者基本信息：{meta_line or '（未填写）'}\n\n"
                  f"以下是这位学生最近的学习总结与会话标题。\n\n{material}\n\n"
                  f"最近的会话：{titles}\n\n请生成一份学习者画像。")
        text = client().complete(
            [{"role": "system", "content": prompts.PROFILE_SYSTEM},
             {"role": "user", "content": prompt}], max_tokens=800)
        log_usage("profile", [{"content": prompts.PROFILE_SYSTEM}, {"content": prompt}], text)
        saved = STORE.save_profile(text, month)
        self._json({"ok": True, **saved, "content": text}, 201)

    # ------------------------------------------------------------ 业务：易错提示本
    def _mistake_tips(self) -> None:
        mistakes = STORE.list_mistakes()
        if not mistakes:
            self._error("易错本还是空的，先做几道题", 400)
            return
        lines = "\n".join(
            f"- [{m.get('subject','')} / {m.get('chapter','')}] {m['stem'][:60]}；"
            f"正确答案 {m['right_answer']}；你选了 {m['my_answer']}" for m in mistakes[:20])
        text = client().complete(
            [{"role": "system", "content": prompts.MISTAKE_SYSTEM},
             {"role": "user", "content": lines}], max_tokens=800)
        log_usage("tips", [{"content": prompts.MISTAKE_SYSTEM}, {"content": lines}], text)
        saved = STORE.add_summary("tips", "易错提示本", text, "")
        self._json({"summary": saved}, 201)


# ---------------------------------------------------------------- 扩展：看板 / 检索 / 报告 / 上传
    def _dashboard(self) -> dict:
        mastery = STORE.mastery()
        return {
            "streak": STORE.streak(),
            "due": STORE.due_review_count(),
            "reviews": STORE.list_due_reviews(limit=10),
            "recommend": STORE.recommendations(),
            "mastery": mastery,
            "usage": STORE.usage_stats(days=7),
            "forecast": STORE.review_forecast(7),
            "activity": STORE.activity_map(weeks=12),
            "pending": len(STORE.pending_materials()),
            "stale": len(STORE.stale_materials()),
            "stats": STORE.stats(),
        }

    def _public_search(self, query: str, k: int = 8) -> dict:
        """用户侧全文检索：返回命中片段与定位信息，供前端高亮展示。"""
        if not (query or "").strip():
            return {"query": query, "hits": [], "queries": []}
        retriever = get_retriever()
        hits, queries = rag.search_multi(retriever, query, k=k)
        return {"query": query, "queries": queries,
                "hits": [h.as_dict() for h in hits]}

    def _graph(self) -> dict:
        """章节—资料关系图：节点是章节与资料，边是"标题/大纲词共现"。

        纯本地计算（分词后取交集），不调模型；节点数控制在上限内，保证前端画得动。
        """
        subjects = STORE.subjects()
        materials = STORE.list_materials()
        nodes: list[dict] = []
        links: list[dict] = []
        chapter_tokens: dict[str, set[str]] = {}
        for sub in subjects:
            for ch in sub["chapters"]:
                cid = f"ch:{ch['id']}"
                chapter_tokens[cid] = set(rag.tokenize(
                    f"{ch['title']} {ch.get('outline') or ''}"))
                nodes.append({"id": cid, "label": ch["title"][:16], "type": "chapter",
                              "group": sub["name"], "weight": 2})
        for m in materials:
            mid = f"mat:{m['id']}"
            toks = set(rag.tokenize(m["title"]))
            nodes.append({"id": mid, "label": m["title"][:18], "type": "material",
                          "group": m.get("subject") or "未分类",
                          "weight": 1 + min(3, (m.get("bytes") or 0) // 8000)})
            best, best_n = "", 0
            for cid, ctoks in chapter_tokens.items():
                n = len(toks & ctoks)
                if n > best_n:
                    best, best_n = cid, n
            if best and best_n >= 2:
                links.append({"source": best, "target": mid, "weight": min(3, best_n)})
        linked = {x["source"] for x in links} | {x["target"] for x in links}
        if len(nodes) > 70:                            # 节点太多，只留有连线的
            nodes = [n for n in nodes if n["id"] in linked]
        return {"nodes": nodes, "links": links,
                "subjects": [s["name"] for s in subjects]}

    def _download(self, data: bytes, filename: str,
                  ctype: str = "application/vnd.openxmlformats-officedocument"
                               ".wordprocessingml.document") -> None:
        quoted = urllib.parse.quote(filename)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted}")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _import_upload(self, body: dict) -> None:
        """上传导入：支持 .docx / .txt / .md / .csv；老式 .doc 明确拒绝。"""
        filename = (body.get("filename") or "").strip()
        low = filename.lower()
        title = (body.get("title") or "").strip() or re.sub(r"\.[^.]+$", "", filename) or "导入资料"
        text = (body.get("text") or "").strip()
        if not text and body.get("content"):
            try:
                raw = extras.b64decode(body["content"])
            except Exception:                          # noqa: BLE001
                self._error("上传内容不是合法的 base64", 400)
                return
            if low.endswith(".docx"):
                try:
                    text = extras.docx_to_text(raw)
                except Exception as exc:               # noqa: BLE001
                    self._error(f"解析 .docx 失败：{exc}", 400)
                    return
            elif low.endswith(".doc"):
                self._error("老式 .doc 无法直接解析，请先在 Word 里另存为 .docx", 400)
                return
            else:
                text = raw.decode("utf-8", "replace")
        if not text.strip():
            self._error("文件里没有可用的文字内容", 400)
            return
        status = "pending" if body.get("review") else "approved"
        material = STORE.add_material(
            title=title[:120], text=text, subject=body.get("subject", ""),
            folder_id=body.get("folder_id", ""), ext=".md", status=status)
        chunks = rag.chunk_text(text)
        STORE.replace_chunks(material["id"], chunks)
        if not body.get("review"):
            STORE.touch_activity()
        self._json({"material": material, "chunks": len(chunks),
                    "chars": len(text), "status": status}, 201)

    def _refresh_material(self, material_id: str) -> None:
        """按来源链接重新抓取，用内容 hash 判断"到底变没变"，变了才重建索引。"""
        rows = [m for m in STORE.list_materials() if m["id"] == material_id]
        if not rows:
            self._error("资料不存在", 404)
            return
        item = rows[0]
        url = item.get("source_url") or ""
        if not url:
            self._error("这份资料没有来源链接，无法重新抓取", 400)
            return
        try:
            text = tools.fetch_url(url)
        except Exception as exc:                       # noqa: BLE001
            self._error(f"重新抓取失败：{exc}", 502)
            return
        old = STORE.get_material_text(material_id)
        new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        changed = bool(old.strip()) and old.strip() != text.strip()
        path = Path(item.get("path") or "")
        if changed and path.is_file():
            path.write_text(text, encoding="utf-8")
            STORE.replace_chunks(material_id, rag.chunk_text(text))
        STORE.update_material_meta(
            material_id, hash=new_hash, fetched_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            bytes=path.stat().st_size if path.is_file() else item.get("bytes", 0))
        self._json({"changed": changed, "old_hash": item.get("hash", ""),
                    "new_hash": new_hash, "chars": len(text)})

    def _find_chapter_id(self, subject: str, chapter: str) -> str:
        for sub in STORE.subjects():
            if subject and sub["name"] != subject:
                continue
            for ch in sub["chapters"]:
                if ch["title"] == chapter:
                    return ch["id"]
        return ""

    def _make_variant(self, mistake_id: str) -> None:
        mistake = next((m for m in STORE.list_mistakes() if m["id"] == mistake_id), None)
        if not mistake:
            self._error("错题不存在", 404)
            return
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return
        ctx = rag_context(f"{mistake.get('subject', '')} {mistake.get('chapter', '')} "
                          f"{mistake['stem']}")
        user = (f"科目：{mistake.get('subject') or '未分类'}\n"
                f"章节：{mistake.get('chapter') or '未指定'}\n"
                f"原题：{mistake['stem']}\n正确答案：{mistake.get('right_answer', '')}\n"
                f"学生当时选了：{mistake.get('my_answer', '')}\n"
                f"原题解析：{mistake.get('note', '')}\n")
        if ctx.evidence:
            user += f"\n参考资料：\n{ctx.evidence}"
        messages = [{"role": "system", "content": prompts.VARIANT_SYSTEM},
                    {"role": "user", "content": user}]
        started = time.time()
        raw = client().complete(messages, max_tokens=900)
        log_usage("variant", messages, raw, 0, int((time.time() - started) * 1000))
        item = _parse_one(raw)
        if not item or not item.get("stem"):
            self._error("模型没有给出可解析的题目，请重试", 502)
            return
        chapter_id = self._find_chapter_id(mistake.get("subject", ""),
                                           mistake.get("chapter", ""))
        saved = None
        if chapter_id:
            saved = STORE.add_question(chapter_id, item["stem"], item.get("options", []),
                                       item.get("answer", "A"),
                                       item.get("explanation", ""))
        self._json({"question": saved or item, "changed": item.get("changed", ""),
                    "saved": bool(saved), "chapter_id": chapter_id})

    def _feynman(self, body: dict) -> None:
        text = (body.get("text") or "").strip()
        if not text:
            self._error("先写一段你自己的复述", 400)
            return
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return
        chapter = STORE.chapter(body.get("chapter_id")) if body.get("chapter_id") else None
        topic = chapter["title"] if chapter else (body.get("topic") or "本知识点").strip()
        ctx = rag_context(f"{topic} {body.get('subject', '')}")
        user = f"知识点：{topic}\n\n学生复述：\n{text}\n"
        if ctx.evidence:
            user += f"\n参考资料（可作为判断依据）：\n{ctx.evidence}"
        messages = [{"role": "system", "content": prompts.FEYNMAN_SYSTEM},
                    {"role": "user", "content": user}]
        started = time.time()
        out = client().complete(messages, max_tokens=700)
        log_usage("feynman", messages, out, 0, int((time.time() - started) * 1000))
        STORE.touch_activity()
        self._json({"feedback": out, "topic": topic, "citations": ctx.citations[:3]})


# ---------------------------------------------------------------- 回答缓存 / 指代消解
# 同一问题（同一上下文、同一风格）在半小时内重复提问，直接重放上次答案：
# 省 token、省等待，且答案与被引用的资料完全一致，不会出现"同问不同答"。
_ANSWER_CACHE: dict[str, dict] = {}
CACHE_TTL = 1800.0
CACHE_MAX = 64
_PRONOUNS = ("它", "这个", "那个", "这些", "那些", "上面", "刚才", "上述", "该", "这题", "这条")


def cache_key(text: str, style: str, history: list[dict]) -> str:
    """按实际回答上下文隔离缓存；索引、配置或档案变化后自然失效。"""
    context = {
        "text": text,
        "style": style,
        "history": history,
        "index_revision": STORE.rev(),
        "config": STORE.get_config(),
        "learner": STORE.meta_summary(),
        "system": prompts.chat_system(style),
        "mock": deepseek.MOCK,
    }
    # 不删除空白或折叠大小写：代码、标识符中的这些差异可能改变含义。
    # 配置仅参与摘要计算，缓存键不包含明文凭证。
    raw = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_get(key: str) -> dict | None:
    item = _ANSWER_CACHE.get(key)
    if not item:
        return None
    if time.time() - item.get("ts", 0) > CACHE_TTL:
        _ANSWER_CACHE.pop(key, None)
        return None
    return item


def cache_put(key: str, payload: dict) -> None:
    if len(_ANSWER_CACHE) >= CACHE_MAX:
        oldest = min(_ANSWER_CACHE, key=lambda k: _ANSWER_CACHE[k].get("ts", 0))
        _ANSWER_CACHE.pop(oldest, None)
    payload["ts"] = time.time()
    _ANSWER_CACHE[key] = payload


def resolve_query(text: str, history: list[dict]) -> str:
    """多轮追问里的"它 / 这个 / 刚才那个"补上前一轮的问题，再拿去检索。

    只影响检索，发给模型和存库的仍是学生原话；补全结果也会写进检索详情。
    """
    text = (text or "").strip()
    if not history or len(text) > 16:
        return text
    if not any(p in text for p in _PRONOUNS):
        return text
    prev = next((m.get("content") or "" for m in reversed(history)
                 if m.get("role") == "user"), "")
    prev = prev.strip()
    if not prev:
        return text
    return f"{prev[:60]} {text}"


# ---------------------------------------------------------------- 工具函数
def _pending_summary() -> dict | None:
    """启动时是否该询问"要不要生成近期总结"：最近对话有内容、且比最近总结更新。"""
    convs = STORE.list_conversations()
    if not convs:
        return None
    latest = convs[0]
    messages = STORE.messages(latest["id"])
    if len(messages) < 4:
        return None
    summaries = STORE.list_summaries("recent")
    if summaries and summaries[0]["created_at"] >= latest["updated_at"]:
        return None
    return {"conversation_id": latest["id"], "title": latest["title"],
            "messages": len(messages), "updated_at": latest["updated_at"]}


def _parse_videos(raw: str) -> list[dict]:
    """解析模型给的视频推荐；把关键词转成搜索链接，避免它编造具体 BV 号。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        keyword = str(item.get("keyword") or "").strip()
        if not keyword:
            continue
        platform = str(item.get("platform") or "").strip() or "哔哩哔哩"
        if "mooc" in platform.lower() or "大学" in platform:
            url = "https://www.icourse163.org/search.htm?search=" + urllib.parse.quote(keyword)
            kind = "MOOC"
        else:
            url = "https://search.bilibili.com/all?keyword=" + urllib.parse.quote(keyword)
            kind = "B站"
        out.append({"title": str(item.get("title") or keyword)[:80],
                    "platform": platform[:30], "kind": kind,
                    "keyword": keyword[:60], "url": url,
                    "reason": str(item.get("reason") or "")[:60]})
    return out[:6]


def _parse_questions(raw: str) -> list[dict]:
    """从模型输出里抠出 JSON 数组；容忍 ```json 包裹和前后废话。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not item.get("stem"):
            continue
        options = item.get("options") or []
        if not isinstance(options, list) or len(options) < 2:
            continue
        out.append({
            "stem": str(item["stem"])[:500],
            "options": [str(o)[:300] for o in options[:6]],
            "answer": str(item.get("answer", "A"))[:1].upper(),
            "explanation": str(item.get("explanation", ""))[:600],
        })
    return out


def _parse_one(raw: str) -> dict:
    """从模型输出里抠出单个 JSON 对象（变式题用）。"""
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start < 0:
        return {}
    try:
        data, _end = json.JSONDecoder().raw_decode(text[start:])   # 只取第一个完整对象
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    options = data.get("options") or []
    if not isinstance(options, list) or len(options) < 2:
        return {}
    return {"stem": str(data.get("stem", ""))[:500],
            "options": [str(o)[:300] for o in options[:6]],
            "answer": str(data.get("answer", "A"))[:1].upper(),
            "explanation": str(data.get("explanation", ""))[:600],
            "changed": str(data.get("changed", ""))[:200]}


def main() -> int:
    ap = argparse.ArgumentParser(description="计算机课程学习助手本地服务")
    ap.add_argument("--port", type=int, default=8737)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--mock", action="store_true", help="离线演示模式，不需要 API Key")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--exit-on-close", action="store_true",
                    help="浏览器页面关闭后自动停止服务")
    ap.add_argument("--idle-visible", type=float, default=25.0,
                    help="页面可见时的空闲上限秒数（配合 --exit-on-close）")
    ap.add_argument("--idle-hidden", type=float, default=300.0,
                    help="页面切后台时的空闲上限秒数")
    ap.add_argument("--auth-server", default="",
                    help="账号认证服务地址，默认取 CSLA_AUTH_SERVER / data/client.json / "
                         + auth_client.DEFAULT_SERVER)
    ap.add_argument("--no-auth", action="store_true",
                    help="跳过登录，单用户模式（数据在 data/ 下，与旧版一致），仅供开发调试")
    args = ap.parse_args()

    global EXIT_ON_CLOSE, IDLE_VISIBLE, IDLE_HIDDEN, AUTH
    EXIT_ON_CLOSE = args.exit_on_close
    IDLE_VISIBLE = args.idle_visible
    IDLE_HIDDEN = args.idle_hidden

    if args.mock:
        deepseek.MOCK = True

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.no_auth:
        local_store = Store()
        samples, moved = init_store(local_store)
        STORE.bind(local_store)
        if moved:
            print(f"  已把 {moved} 份资料归入对应文件夹")
        if samples:
            print(f"  已导入内置示例资料 {samples} 份（可在界面里删除）")
    else:
        AUTH = auth_client.AuthClient(auth_client.resolve_server(args.auth_server, DATA_DIR),
                                      DATA_DIR / "session.json")
        try:
            sync_auth(force=True)
        except Exception as exc:                      # noqa: BLE001 - 启动不因账号问题失败
            print(f"  恢复登录状态失败：{exc}")

    try:
        httpd = QuietHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print("=" * 56)
        print(f"  启动失败：端口 {args.port} 已被占用（{exc}）")
        print("  可能已经有一个实例在运行。请先关掉那个窗口，")
        print(f"  或者用别的端口启动：python server.py --port {args.port + 1}")
        print("=" * 56)
        return 2

    httpd.flags = ["--verbose"] if args.verbose else []
    url = f"http://{args.host}:{args.port}"
    print("=" * 56)
    print("  计算机课程学习助手（本地版）")
    print(f"  地址：{url}")
    print(f"  数据目录：{DATA_DIR}")
    print(f"  模式：{'离线演示（--mock）' if deepseek.MOCK else 'DeepSeek API'}")
    if AUTH is None:
        print("  登录：关闭（--no-auth 单用户模式）")
    else:
        who = AUTH.user["username"] if AUTH.logged_in else "未登录"
        print(f"  认证服务：{AUTH.base_url}（当前：{who}{'，离线' if AUTH.offline else ''}）")
    print(f"  自动退出：{'开启（关闭浏览器页面后停止）' if EXIT_ON_CLOSE else '关闭'}")
    print("=" * 56)

    if EXIT_ON_CLOSE:
        threading.Thread(target=watchdog, args=(httpd,), daemon=True).start()
    if args.open:
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)),
                         daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
