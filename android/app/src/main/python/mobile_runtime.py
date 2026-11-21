"""Android-only adapter. No account server; persistent state stays in noBackupFilesDir.

The native process alone receives the random loopback credential. API keys are
read/written through a Java Keystore vault, never through SQLite or JS getters.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path

_server = None
_foreground = threading.Event()
_foreground.set()
_cancel_epoch = 0
_start_lock = threading.Lock()


def set_foreground(visible):
    global _cancel_epoch
    if visible:
        _foreground.set()
    else:
        _cancel_epoch += 1
        _foreground.clear()


def start(root, vault):
    global _server
    with _start_lock:
        if _server:
            return json.dumps({"url": _server.origin, "cookie": _server.cookie})
        root = Path(str(root)).resolve()
        root.mkdir(parents=True, exist_ok=True)
        os.environ["CSLA_DATA_DIR"] = str(root)
        os.environ["CSLA_REFERENCE_DIR"] = str(root / "reference_library")
        # Ignore desktop development configuration in the embedded application.
        os.environ.pop("CSLA_MOCK", None)
        os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
        import server
        import store
        import deepseek
        deepseek.MOCK = False
        deepseek.BASE_URL = "https://api.deepseek.com"
        def cancellation_check():
            epoch = _cancel_epoch
            def check():
                if not _foreground.is_set() or epoch != _cancel_epoch:
                    raise deepseek.DeepSeekError(
                        "应用曾进入后台；本次生成已中断，请回到前台重试", 409, retryable=True)
            return check
        deepseek.CANCELLATION_CHECK_FACTORY = cancellation_check

        class VaultStore(store.Store):
            def get_config(self):
                cfg = super().get_config()
                try:
                    cfg["api_key"] = str(vault.readKey())
                except Exception:
                    # A damaged Keystore key must not make offline reading fail.
                    cfg["api_key"] = ""
                return cfg

            def set_config(self, key, value):
                if key == "api_key":
                    vault.writeKey(str(value))
                else:
                    super().set_config(key, value)

            def delete_chapter(self, chapter_id):
                with server.STORE._lock:
                    result = super().delete_chapter(chapter_id)
                    self.conn.execute("DELETE FROM mobile_jobs WHERE chapter_id=?", (chapter_id,))
                    self.conn.commit()
                    return result

            def delete_subject(self, subject_id):
                with server.STORE._lock:
                    result = super().delete_subject(subject_id)
                    self.conn.execute("DELETE FROM mobile_jobs WHERE chapter_id NOT IN (SELECT id FROM chapters)")
                    self.conn.commit()
                    return result

        owner = VaultStore(root / "csla.db", data_dir=root)
        owner.conn.execute("DELETE FROM config WHERE key='api_key'")
        owner.conn.execute("""CREATE TABLE IF NOT EXISTS mobile_jobs (
            chapter_id TEXT PRIMARY KEY, section_id TEXT, status TEXT,
            updated_at TEXT, message TEXT)""")
        owner.conn.execute("DELETE FROM mobile_jobs WHERE chapter_id NOT IN (SELECT id FROM chapters)")
        owner.conn.execute("""UPDATE mobile_jobs SET status='interrupted',
            message='应用曾退出；已保存小节可离线阅读，请重试未完成小节'
            WHERE status='running'""")
        owner.conn.commit()
        # Avoid startup re-importing shared material which the owner deleted.
        if not owner.get_config().get("mobile_seed_v1"):
            server.init_store(owner)
            owner.set_config("mobile_seed_v1", "1")
        owner.ensure_user()
        server.STORE.bind(owner)
        server.AUTH = None
        server.CURRENT_UID = "phone"
        server.auth_status = lambda: {
            "enabled": False, "logged_in": True, "user": None,
            "offline": False, "auth_server": "", "notice": "",
            "is_admin": False, "local": True}
        # Local owner may edit their bundled material; no server admin API exists.
        server.is_admin = lambda: False
        server.reset_caches()
        tutor_lock = threading.Lock()
        uploads = {}
        upload_lock = threading.Lock()
        preference_keys = ("tooltips", "motion", "pointer", "mascot", "math",
                           "largeText", "wrapCode", "outlineExpanded", "confirmDelete")

        def saved_json(key):
            try:
                value = json.loads(owner.get_config().get(key) or "{}")
                return value if isinstance(value, dict) else {}
            except (ValueError, TypeError):
                return {}

        def clean_session(body):
            views = ("home", "chat", "study", "materials", "reader", "lesson",
                     "dashboard", "summary", "mistakes", "review", "usage",
                     "search", "profile", "preferences")
            result = {"view": body.get("view") if body.get("view") in views else "home"}
            for key in ("subject_id", "chapter_id", "folder_id", "conversation_id", "material_id"):
                value = body.get(key, "")
                if isinstance(value, str) and re.fullmatch(r"[\w-]{0,80}", value):
                    result[key] = value
            draft = body.get("chat_draft", "")
            result["chat_draft"] = draft[:12000] if isinstance(draft, str) else ""
            return result

        def job(chapter_id, section_id, status, message=""):
            with server.STORE._lock:
                if not owner.chapter(chapter_id):
                    return
                owner.conn.execute(
                    "INSERT OR REPLACE INTO mobile_jobs VALUES (?,?,?,?,?)",
                    (chapter_id, section_id, status, store.now(), message))
                owner.conn.commit()

        class MobileHandler(server.Handler):
            def _static(self, path):
                if path in ("/", "", "/ui.js"):
                    if path == "/ui.js":
                        prefs = {k: v for k, v in saved_json("mobile_preferences_v1").items()
                                 if k in preference_keys and isinstance(v, bool)}
                        body = "window.CSLA_MOBILE_PREFERENCES=" + json.dumps(prefs) + ";\n"
                        body += (server.STATIC_DIR / "ui.js").read_text(encoding="utf-8")
                        mime = "application/javascript"
                    else:
                        body = (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
                        body = body.replace('<html lang="zh-CN">', '<html lang="zh-CN" data-platform="android">')
                        mime = "text/html"
                    raw = body.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", mime + "; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                super()._static(path)

            def end_headers(self):
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy",
                    "default-src 'self'; script-src 'self'; "
                    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                    "font-src 'self'; connect-src 'self'; frame-src 'self'; "
                    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
                super().end_headers()

            def _need_login(self, path):
                # Applies to static resources too, before any body is read.
                cookie = SimpleCookie()
                try:
                    cookie.load(self.headers.get("Cookie", ""))
                    value = cookie.get("csla_phone")
                    secret = value.value if value else ""
                except Exception:
                    secret = ""
                if (self.headers.get("Host") != self.server.host
                    or not hmac.compare_digest(secret, self.server.secret)
                    or self.headers.get("Origin", self.server.origin) != self.server.origin
                    or self.headers.get("Sec-Fetch-Site", "same-origin") == "cross-site"):
                    self._error("仅允许本机学习应用访问", 403)
                    self.close_connection = True
                    return True
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if not 0 <= length <= 46 * 1024 * 1024:
                    self._error("上传内容过大或长度无效", 413)
                    self.close_connection = True
                    return True
                if path.startswith(("/api/auth/", "/api/admin/")):
                    self._error("手机端使用本地用户，无在线账号管理", 404)
                    return True
                return False

            def _can_edit_core(self):
                return True

            def do_POST(self):
                if urllib.parse.urlparse(self.path).path != "/api/mobile/import":
                    return super().do_POST()
                if self._need_login("/api/mobile/import"):
                    return
                token, claimed = "", False
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= server.IMPORT_MAX:
                        self._error("文件不能为空且不能超过 32 MB", 413)
                        self.close_connection = True
                        return
                    token = self.headers.get("X-CSLA-Upload", "")
                    with upload_lock:
                        entry = uploads.get(token)
                        available = entry and not entry.get("running")
                        if available:
                            entry["running"] = True
                            claimed = True
                    if not available or entry["expires"] < time.monotonic():
                        self._error("导入已取消或过期，请重新选择文件", 409)
                        self.close_connection = True
                        return
                    if length != entry["size"] or self.headers.get("Content-Type") != "application/octet-stream":
                        self._error("上传大小或类型不匹配", 400)
                        self.close_connection = True
                        return
                    self.connection.settimeout(60)
                    raw = self.rfile.read(length)
                    with upload_lock:
                        current = uploads.pop(token, None)
                    if not current or current.get("cancelled"):
                        self._error("已取消导入", 409)
                        return
                    if len(raw) != length:
                        self._error("文件传输未完成，请重新导入", 400)
                        return
                    self._import_upload(entry["metadata"], raw_upload=raw)
                except (OSError, TimeoutError):
                    self.close_connection = True
                except Exception as exc:
                    self._error(f"导入失败：{exc}", 400)
                finally:
                    if claimed:
                        with upload_lock:
                            uploads.pop(token, None)

            def _api_get(self, path, query):
                if path == "/api/mobile/status":
                    with server.STORE._lock:
                        jobs = [dict(r) for r in owner.conn.execute(
                            "SELECT * FROM mobile_jobs ORDER BY updated_at DESC")]
                    self._json({"local_only": True, "can_edit_core": True, "jobs": jobs})
                    return
                if path == "/api/mobile/session":
                    self._json(clean_session(saved_json("mobile_session_v1")))
                    return
                if path == "/api/mobile/preferences":
                    self._json(saved_json("mobile_preferences_v1"))
                    return
                super()._api_get(path, query)

            def _api_post(self, path, body):
                if path == "/api/mobile/preferences":
                    if not isinstance(body, dict):
                        self._error("偏好参数无效", 400)
                        return
                    prefs = {k: v for k, v in body.items()
                             if k in preference_keys and isinstance(v, bool)}
                    owner.set_config("mobile_preferences_v1", json.dumps(prefs))
                    self._json({"ok": True})
                    return
                if path == "/api/mobile/session":
                    if not isinstance(body, dict):
                        self._error("会话参数无效", 400)
                        return
                    owner.set_config("mobile_session_v1", json.dumps(clean_session(body)))
                    self._json({"ok": True})
                    return
                if path == "/api/mobile/import/prepare":
                    if not isinstance(body, dict):
                        self._error("导入参数无效", 400)
                        return
                    size = body.get("size")
                    filename = body.get("filename")
                    if (not isinstance(size, int) or isinstance(size, bool)
                        or not 0 < size <= server.IMPORT_MAX
                        or not isinstance(filename, str) or len(filename) > 240
                        or Path(filename.lower()).suffix not in server.IMPORT_TYPES):
                        self._error("请选择不超过 32 MB 的 PDF、DOCX 或文本文件", 400)
                        return
                    metadata = {}
                    for key, limit in (("filename", 240), ("title", 120), ("text", 2 * 1024 * 1024),
                                       ("subject", 120), ("folder_id", 80)):
                        value = body.get(key, "")
                        if not isinstance(value, str) or len(value) > limit:
                            self._error("导入参数过长或类型无效", 400)
                            return
                        metadata[key] = value
                    for key in ("review", "is_reference"):
                        metadata[key] = body.get(key) is True
                    with upload_lock:
                        now = time.monotonic()
                        for old in list(uploads):
                            if uploads[old]["expires"] < now:
                                del uploads[old]
                        if len(uploads) >= 8:
                            self._error("待导入文件过多，请稍后重试", 429)
                            return
                        token = secrets.token_urlsafe(24)
                        uploads[token] = {"metadata": metadata, "size": size, "expires": now + 600}
                    self._json({"upload_id": token}, 201)
                    return
                if path == "/api/mobile/import/cancel":
                    with upload_lock:
                        token = body.get("upload_id", "")
                        current = uploads.get(token)
                        if current and current.get("running"):
                            current["cancelled"] = True
                        else:
                            uploads.pop(token, None)
                    self._json({"ok": True})
                    return
                if path == "/api/mobile/key/clear":
                    owner.set_config("api_key", "")
                    self._json({"ok": True})
                    return
                if path in ("/api/heartbeat", "/api/client-closed"):
                    self._json({"ok": True})
                    return
                # The desktop launcher uses subprocess; Android returns a local reader.
                match = re.fullmatch(r"/api/materials/([\w-]+)/open", path)
                if match:
                    mat = owner.material(match[1])
                    if not mat:
                        self._error("资料不存在", 404)
                        return
                    self._json({"ok": True, "mobile": True,
                                "reader": "/?view=reader&id=" + match[1]})
                    return
                super()._api_post(path, body)

            def _chapter_tutor(self, chapter_id, body):
                if not tutor_lock.acquire(blocking=False):
                    self._error("上一小节请求尚未结束，请稍后重试", 409)
                    return
                try:
                    self._mobile_tutor(chapter_id, body)
                finally:
                    tutor_lock.release()

            def _mobile_tutor(self, chapter_id, body):
                # One section per mobile request; the existing validator and
                # durable section publishing remain the source of truth.
                with server.STORE._lock:
                    chapter = owner.chapter(chapter_id)
                    if not chapter or not _foreground.is_set():
                        self._error("请在前台打开章节再生成", 409)
                        return
                    if (not body.get("section_id") and body.get("action") != "outline"
                        and body.get("all_sections") is not True):
                        meta = server.lessons.plan(chapter)
                        server.lessons.publish(owner, chapter_id, meta)
                        target = next((u for u in meta["sections"] if not u.get("content")), None)
                        if not target:
                            self._error("所有小节已保存", 409)
                            return
                        body = dict(body, section_id=target["id"])
                    if (id(owner), chapter_id) in server.TUTOR_JOBS:
                        self._error("本章上一请求尚未结束，请稍后重试", 409)
                        return
                    if not owner.has_api_key():
                        self._error("请在设置中填写 DeepSeek API Key", 401)
                        return
                    job(chapter_id, body.get("section_id", ""), "running")
                self.mobile_chapter = chapter_id
                self.mobile_epoch = _cancel_epoch
                self.mobile_completed = False
                try:
                    super()._chapter_tutor(chapter_id, body)
                finally:
                    if not self.mobile_completed:
                        job(chapter_id, body.get("section_id", ""), "interrupted",
                            "本节未完成；已保存内容保留，可再次生成")

            def _sse_start(self):
                self.stream_epoch = _cancel_epoch
                super()._sse_start()

            def _sse(self, event, data):
                if not _foreground.is_set() or getattr(self, "stream_epoch", _cancel_epoch) != _cancel_epoch:
                    raise BrokenPipeError("应用进入后台")
                if hasattr(self, "mobile_epoch"):
                    if not _foreground.is_set() or self.mobile_epoch != _cancel_epoch:
                        raise BrokenPipeError("应用进入后台")
                    if event == "completed":
                        job(self.mobile_chapter, "", "completed")
                        self.mobile_completed = True
                super()._sse(event, data)

        httpd = server.QuietHTTPServer(("127.0.0.1", 0), MobileHandler)
        httpd.host = f"127.0.0.1:{httpd.server_port}"
        httpd.origin = f"http://{httpd.host}"
        httpd.secret = secrets.token_urlsafe(32)
        httpd.cookie = f"csla_phone={httpd.secret}; Path=/; HttpOnly; SameSite=Strict"
        _server = httpd
        threading.Thread(target=httpd.serve_forever, daemon=True, name="csla-local").start()
        return json.dumps({"url": httpd.origin, "cookie": httpd.cookie})


def source_info(material_id):
    """Native PDF viewer receives only a verified application-owned path."""
    import server
    mat = server.STORE.material(str(material_id))
    if not mat:
        raise ValueError("资料不存在")
    root = server.STORE.data_dir.resolve()
    for key in ("original", "path"):
        path = Path(mat.get(key) or "").resolve()
        if root in path.parents and path.is_file():
            return json.dumps({"path": str(path), "name": path.name,
                               "pdf": path.suffix.lower() == ".pdf"})
    raise ValueError("源文件不存在")
