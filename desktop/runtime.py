"""Private, embedded services shared by both desktop editions."""
from __future__ import annotations

import hmac
import http.cookies
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from platform_support import DataLock, LockBusy

SOURCE = Path(__file__).resolve().parents[1] / "AIassistant-v4" / "AIassistant"
if not getattr(sys, "frozen", False):
    sys.path[:0] = [str(SOURCE / "app"), str(SOURCE / "auth_server")]


class AlreadyRunning(Exception):
    pass


class DesktopRuntime:
    def __init__(self, data_dir: Path, demo: bool = False):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.data_lock = DataLock(self.root / ".desktop.lock")
        except LockBusy:
            raise AlreadyRunning("学习助手已在运行，请切换到已有窗口。")
        self.closed = threading.Event()
        self.stopped = False
        self.services = []
        self.threads = []
        self.bootstrap_lock = threading.Lock()
        self.bootstrap_token = secrets.token_urlsafe(32)
        self.cookie_token = secrets.token_urlsafe(32)
        self.auth_secret = secrets.token_urlsafe(32)
        try:
            self._start(demo)
        except BaseException:
            self.stop()
            raise

    def _start(self, demo):
        os.environ["CSLA_DATA_DIR"] = str(self.root / "learning")
        os.environ["CSLA_REFERENCE_DIR"] = str(self.root / "reference_library")
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
        import server
        import store
        import references
        import deepseek
        import auth_client
        import auth_server
        self.app = server
        store.DATA_DIR = server.DATA_DIR = self.root / "learning"
        store.DB_PATH = store.DATA_DIR / "csla.db"
        store.MATERIAL_DIR = store.DATA_DIR / "materials"
        store.CONFIG_PATH = store.DATA_DIR / "config.json"
        server.USERS_DIR = server.DATA_DIR / "users"
        server.LEGACY_MARK = server.USERS_DIR / ".legacy_migrated"
        references.LIBRARY = self.root / "reference_library"
        server.EXIT_ON_CLOSE = False
        deepseek.MOCK = bool(demo)
        deepseek.BASE_URL = "https://api.deepseek.com"
        deepseek.CANCELLATION_CHECK_FACTORY = lambda: self._check_cancelled
        server.DATA_DIR.mkdir(parents=True, exist_ok=True)
        runtime = self

        class LocalAuthStore(auth_server.AuthStore):
            def __init__(self, path):
                super().__init__(path)
                self.registration_lock = threading.Lock()

            def register(self, body, ip=""):
                # Bootstrap applies only to this independent desktop account database.
                with self.registration_lock:
                    with self.lock:
                        first = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
                    result = super().register(body, ip)
                    if first:
                        self.set_role(result["user"]["username"], "admin")
                        result["user"]["role"] = "admin"
                    return result

        self.auth_store = LocalAuthStore(self.root / "accounts" / "auth.db")
        base_auth_handler = auth_server.make_handler(self.auth_store)

        class AuthHandler(base_auth_handler):
            def _dispatch(self, method):
                expected_host = f"127.0.0.1:{self.server.server_port}"
                if (self.headers.get("Host") != expected_host
                        or self.headers.get("Origin")
                        or not hmac.compare_digest(self.headers.get("X-CSLA-Desktop", ""),
                                                   runtime.auth_secret)):
                    self.close_connection = True
                    self._json({"error": {"message": "禁止访问"}}, 403)
                    return
                return super()._dispatch(method)

        auth_http = auth_server.QuietHTTPServer(("127.0.0.1", 0), AuthHandler)
        self._serve(auth_http)
        auth_url = f"http://127.0.0.1:{auth_http.server_port}"

        class LocalAuthClient(auth_client.AuthClient):
            def _call(self, method, path, body=None, token=""):
                data = json.dumps(body or {}).encode() if method == "POST" else None
                req = urllib.request.Request(self.base_url + path, data=data, method=method,
                    headers={"Content-Type": "application/json", "X-CSLA-Desktop": runtime.auth_secret,
                             "User-Agent": "CSLA-Desktop/0.2.0"})
                if token:
                    req.add_header("Authorization", "Bearer " + token)
                try:
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        return json.loads(resp.read())
                except urllib.error.HTTPError as exc:
                    err = json.loads(exc.read()).get("error", {})
                    raise auth_client.AuthFailed(err.get("code", "server_error"),
                                                 err.get("message", "认证失败"), exc.code)
                except (OSError, ValueError) as exc:
                    raise auth_client.AuthUnavailable(str(exc))

        server.AUTH = LocalAuthClient(auth_url, server.DATA_DIR / "session.json")
        server.sync_auth(force=True)

        class DesktopHandler(server.Handler):
            def _need_login(self, path):
                if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                    return self._forbidden()
                origin = self.headers.get("Origin")
                if origin and origin != runtime.url:
                    return self._forbidden()
                if path == "/_desktop_bootstrap" and self.command == "GET":
                    token = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("token", [""])[0]
                    with runtime.bootstrap_lock:
                        if not runtime.bootstrap_token or not hmac.compare_digest(token, runtime.bootstrap_token):
                            return self._forbidden()
                        runtime.bootstrap_token = ""
                    self.send_response(303)
                    self.send_header("Set-Cookie", f"csla_desktop={runtime.cookie_token}; Path=/; HttpOnly; SameSite=Strict")
                    self.send_header("Location", "/")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return True
                cookie = http.cookies.SimpleCookie()
                try:
                    cookie.load(self.headers.get("Cookie", ""))
                    value = cookie.get("csla_desktop")
                    permitted = value and hmac.compare_digest(value.value, runtime.cookie_token)
                except (http.cookies.CookieError, ValueError):
                    permitted = False
                if not permitted:
                    return self._forbidden()
                return super()._need_login(path)

            def _forbidden(self):
                self.close_connection = True
                self._error("请从桌面应用访问", 403, code="desktop_required")
                return True

            def _static(self, path):
                if path in ("/", "", "/desktop.js"):
                    if path == "/desktop.js":
                        data = (Path(__file__).resolve().parent / "desktop.js").read_bytes()
                        content_type = "application/javascript; charset=utf-8"
                    else:
                        html = (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")
                        html = html.replace('id="entry-choice" class="gate"',
                                            'id="entry-choice" class="gate hidden"')
                        data = html.replace("</body>", '<script src="/desktop.js"></script></body>').encode()
                        content_type = "text/html; charset=utf-8"
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                return super()._static(path)

        httpd = server.QuietHTTPServer(("127.0.0.1", 0), DesktopHandler)
        httpd.flags = []
        self.url = f"http://127.0.0.1:{httpd.server_port}"
        self.bootstrap_url = self.url + "/_desktop_bootstrap?token=" + self.bootstrap_token
        self._serve(httpd)

    def _serve(self, httpd):
        self.services.append(httpd)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.threads.append(thread)
        thread.start()

    def _check_cancelled(self):
        if self.closed.is_set():
            import deepseek
            raise deepseek.DeepSeekError("应用已关闭，停止生成", retryable=True)

    def request(self, path, body=None, method=None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("无效的本地地址")
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
            headers={"Cookie": "csla_desktop=" + self.cookie_token, "Origin": self.url,
                     "Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=30)

    def attachment(self, path):
        parsed = urllib.parse.urlsplit(path)
        if parsed.scheme or parsed.netloc or parsed.fragment or not re.fullmatch(
            r"/api/(?:export/report|profile/\d{4}-\d{2}/download|"
            r"materials/[\w-]+/source|chapters/[\w-]+/lecture)", parsed.path):
            raise ValueError("不支持导出此地址")
        if parsed.query not in ("", "download=1"):
            raise ValueError("无效的下载参数")
        with self.request(path) as response:
            disposition = response.headers.get("Content-Disposition", "")
            match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
            filename = urllib.parse.unquote(match.group(1)) if match else "CSLA导出文件"
            filename = Path(filename.replace("\\", "/")).name
            data = response.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise ValueError("导出文件超过 64 MB")
            return filename, data

    def stop(self):
        if self.stopped:
            return
        self.stopped = True
        self.closed.set()
        for service in self.services:
            service.shutdown()
            service.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        if hasattr(self, "app"):
            self.app.deactivate_user(close=True)
            self.app.AUTH = None
        if hasattr(self, "auth_store"):
            self.auth_store.conn.close()
        self.data_lock.release()
