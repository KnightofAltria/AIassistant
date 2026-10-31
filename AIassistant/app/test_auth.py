#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""登录注册回归测试（不调模型、不碰 data/ 里的真实数据）。

    python test_auth.py

认证服务在临时目录 + 随机端口里起一个线程，本机数据目录也指到临时目录，跑完全部删除。
对应 文档/登录注册方案/登录注册与本地部署流程.md 第 10 节的自动化测试项。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("CSLA_PBKDF2_ITERATIONS", "1000")      # 测试里不需要真实强度

APP = Path(__file__).resolve().parent
sys.path.insert(0, str(APP.parent / "auth_server"))
sys.path.insert(0, str(APP))

import auth_client                     # noqa: E402
import auth_server                     # noqa: E402

PASSWORD = "abc12345"


def call(base: str, method: str, path: str, body: dict | None = None, token: str = ""):
    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class AuthTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="csla-auth-test-"))
        cls.store = auth_server.AuthStore(cls.tmp / "auth.db")
        cls.httpd = auth_server.build_server(cls.store, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.store.conn.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        # 每个用例重新计数，避免互相触发限流
        self.store.limiter = auth_server.RateLimiter()

    def register(self, username: str, password: str = PASSWORD, nickname: str = ""):
        return call(self.base, "POST", "/auth/register",
                    {"username": username, "password": password, "nickname": nickname})

    def login(self, username: str, password: str = PASSWORD):
        return call(self.base, "POST", "/auth/login", {"username": username, "password": password})


class AuthServerTest(AuthTestBase):
    def test_register_and_duplicate(self):
        status, data = self.register("Alice_1", nickname="小艾")
        self.assertEqual(status, 201)
        self.assertEqual(data["user"]["username"], "Alice_1")
        self.assertEqual(data["user"]["nickname"], "小艾")
        self.assertNotIn("password_hash", data["user"])
        status, data = self.register("alice_1")              # 大小写不敏感判重
        self.assertEqual((status, data["error"]["code"]), (409, "username_taken"))

    def test_register_invalid_input(self):
        cases = [("ab", PASSWORD), ("bad name", PASSWORD), ("用户名", PASSWORD),
                 ("valid_user", "short1"), ("valid_user", "onlyletters"),
                 ("valid_user", "12345678"), ("valid_user", "a1" * 33)]
        for username, password in cases:
            status, data = self.register(username, password)
            self.assertEqual((status, data["error"]["code"]), (400, "invalid_input"),
                             (username, password))
        status, data = self.register("valid_user", nickname="x" * 21)
        self.assertEqual(status, 400)

    def test_login_errors_are_uniform(self):
        self.register("bob_2")
        s1, d1 = self.login("bob_2", "wrong1234")
        s2, d2 = self.login("nobody_here", "wrong1234")
        self.assertEqual((s1, d1["error"]), (s2, d2["error"]))
        self.assertEqual(d1["error"]["code"], "invalid_credentials")
        self.assertEqual(self.login("BOB_2")[0], 200)          # 登录也不区分大小写

    def test_rate_limit(self):
        self.register("carol_3")
        for _ in range(auth_server.LOGIN_USER_LIMIT):
            self.assertEqual(self.login("carol_3", "wrong1234")[0], 401)
        status, data = self.login("carol_3")                 # 密码对也要等
        self.assertEqual((status, data["error"]["code"]), (429, "rate_limited"))

    def test_me_refresh_logout(self):
        self.register("dave_4")
        _, data = self.login("dave_4")
        tokens = data["tokens"]
        status, me = call(self.base, "GET", "/auth/me", token=tokens["access_token"])
        self.assertEqual((status, me["user"]["username"]), (200, "dave_4"))
        self.assertEqual(call(self.base, "GET", "/auth/me", token="garbage")[0], 401)

        status, fresh = call(self.base, "POST", "/auth/refresh",
                             {"refresh_token": tokens["refresh_token"]})
        self.assertEqual(status, 200)
        new = fresh["tokens"]
        self.assertNotEqual(new["access_token"], tokens["access_token"])
        # 轮换后旧的两枚 token 都失效
        self.assertEqual(call(self.base, "GET", "/auth/me", token=tokens["access_token"])[0], 401)
        self.assertEqual(call(self.base, "POST", "/auth/refresh",
                              {"refresh_token": tokens["refresh_token"]})[0], 401)

        self.assertEqual(call(self.base, "POST", "/auth/logout", token=new["access_token"])[0], 200)
        self.assertEqual(call(self.base, "GET", "/auth/me", token=new["access_token"])[0], 401)

    def test_change_password_revokes_other_sessions(self):
        self.register("erin_5")
        a = self.login("erin_5")[1]["tokens"]["access_token"]
        b = self.login("erin_5")[1]["tokens"]["access_token"]
        status, data = call(self.base, "POST", "/auth/password",
                            {"old_password": "wrong1234", "new_password": "new12345"}, token=a)
        self.assertEqual((status, data["error"]["code"]), (401, "invalid_credentials"))
        status, _ = call(self.base, "POST", "/auth/password",
                         {"old_password": PASSWORD, "new_password": "new12345"}, token=a)
        self.assertEqual(status, 200)
        self.assertEqual(call(self.base, "GET", "/auth/me", token=a)[0], 200)   # 当前会话保留
        self.assertEqual(call(self.base, "GET", "/auth/me", token=b)[0], 401)   # 其他会话失效
        self.assertEqual(self.login("erin_5")[0], 401)
        self.assertEqual(self.login("erin_5", "new12345")[0], 200)

    def test_disable_account(self):
        self.register("frank_6")
        access = self.login("frank_6")[1]["tokens"]["access_token"]
        self.assertTrue(self.store.set_status("frank_6", "disabled"))
        self.assertEqual(call(self.base, "GET", "/auth/me", token=access)[0], 401)
        status, data = self.login("frank_6")
        self.assertEqual((status, data["error"]["code"]), (403, "account_disabled"))
        self.store.set_status("frank_6", "active")
        self.assertEqual(self.login("frank_6")[0], 200)

    def test_no_plaintext_in_db(self):
        self.register("grace_7", password="Secret999x")
        tokens = self.login("grace_7", "Secret999x")[1]["tokens"]
        raw = (self.tmp / "auth.db").read_bytes()
        for secret in ("Secret999x", tokens["access_token"], tokens["refresh_token"]):
            self.assertNotIn(secret.encode(), raw)
        row = self.store.conn.execute(
            "SELECT password_hash FROM users WHERE username_key='grace_7'").fetchone()
        self.assertTrue(row[0].startswith("pbkdf2_sha256$"))

    def test_unknown_path_and_bad_json(self):
        self.assertEqual(call(self.base, "GET", "/auth/nothing")[0], 404)
        req = urllib.request.Request(self.base + "/auth/login", data=b"not json", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_update_nickname(self):
        self.register("nick_12", nickname="旧名")
        access = self.login("nick_12")[1]["tokens"]["access_token"]
        status, data = call(self.base, "POST", "/auth/profile", {"nickname": "新名字"}, token=access)
        self.assertEqual((status, data["user"]["nickname"]), (200, "新名字"))
        self.assertEqual(call(self.base, "GET", "/auth/me", token=access)[1]["user"]["nickname"], "新名字")
        status, data = call(self.base, "POST", "/auth/profile", {"nickname": "x" * 21}, token=access)
        self.assertEqual((status, data["error"]["code"]), (400, "invalid_input"))
        self.assertEqual(call(self.base, "POST", "/auth/profile", {"nickname": "a"})[0], 401)


class AuthClientTest(AuthTestBase):
    def client(self, name: str = "session.json") -> auth_client.AuthClient:
        return auth_client.AuthClient(self.base, self.tmp / name)

    def test_session_persisted_and_restored(self):
        self.register("henry_8")
        c = self.client("s1.json")
        c.login("henry_8", PASSWORD)
        path = self.tmp / "s1.json"
        self.assertTrue(path.is_file())
        if os.name == "posix":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        again = self.client("s1.json")                       # 模拟重启本机服务
        again.verify(force=True)
        self.assertTrue(again.logged_in)
        self.assertEqual(again.user["username"], "henry_8")
        again.logout()
        self.assertFalse(path.exists())

    def test_expired_access_is_refreshed(self):
        self.register("ivy_9")
        c = self.client("s2.json")
        c.login("ivy_9", PASSWORD)
        old_refresh = c.session["tokens"]["refresh_token"]
        c.session["tokens"]["access_expires_at"] = 0
        c.verify(force=True)
        self.assertTrue(c.logged_in)
        self.assertNotEqual(c.session["tokens"]["refresh_token"], old_refresh)

    def test_revoked_session_is_cleared(self):
        self.register("jack_10")
        c = self.client("s3.json")
        c.login("jack_10", PASSWORD)
        self.store.set_status("jack_10", "disabled")
        c.verify(force=True)
        self.assertFalse(c.logged_in)
        self.assertTrue(c.notice)
        self.assertFalse((self.tmp / "s3.json").exists())

    def test_update_nickname_persisted(self):
        self.register("lily_13")
        c = self.client("s5.json")
        c.login("lily_13", PASSWORD)
        self.assertEqual(c.update_nickname("莉莉")["nickname"], "莉莉")
        self.assertEqual(self.client("s5.json").user["nickname"], "莉莉")   # 写回了 session.json

    def test_offline_grace(self):
        self.register("kate_11")
        c = self.client("s4.json")
        c.login("kate_11", PASSWORD)
        c.base_url = "http://127.0.0.1:9"                   # 连不上
        c.timeout = 0.5
        c.verify(force=True)
        self.assertTrue(c.logged_in)
        self.assertTrue(c.status()["offline"])
        c.session["last_verified"] = time.time() - auth_client.OFFLINE_GRACE - 1
        c.verify(force=True)
        self.assertFalse(c.logged_in)
        self.assertIn("7 天", c.notice)

    def test_resolve_server(self):
        d = self.tmp / "resolve"
        d.mkdir()
        old = os.environ.pop("CSLA_AUTH_SERVER", None)
        try:
            self.assertEqual(auth_client.resolve_server("", d), auth_client.DEFAULT_SERVER)
            (d / "client.json").write_text('{"auth_server": "http://cfg:1/"}', encoding="utf-8")
            self.assertEqual(auth_client.resolve_server("", d), "http://cfg:1")
            os.environ["CSLA_AUTH_SERVER"] = "http://env:2"
            self.assertEqual(auth_client.resolve_server("", d), "http://env:2")
            self.assertEqual(auth_client.resolve_server("http://cli:3/", d), "http://cli:3")
        finally:
            os.environ.pop("CSLA_AUTH_SERVER", None)
            if old is not None:
                os.environ["CSLA_AUTH_SERVER"] = old


class TempDataTest(unittest.TestCase):
    """把 server 的数据目录整个指到临时目录，跑完删掉。"""

    def setUp(self):
        import server
        import store as store_mod
        self.server, self.store_mod = server, store_mod
        self.tmp = Path(tempfile.mkdtemp(prefix="csla-iso-test-"))
        self.saved = (server.DATA_DIR, server.USERS_DIR, server.LEGACY_MARK, server.CURRENT_UID)
        server.DATA_DIR = self.tmp
        server.USERS_DIR = self.tmp / "users"
        server.LEGACY_MARK = server.USERS_DIR / ".legacy_migrated"
        server.CURRENT_UID = ""
        server.STORE.bind(None)

    def tearDown(self):
        s = self.server
        s.STORE.bind(None)
        s.DATA_DIR, s.USERS_DIR, s.LEGACY_MARK, s.CURRENT_UID = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)


class DataIsolationTest(TempDataTest):
    """按账号隔离与旧数据迁移。"""

    def make_legacy(self) -> str:
        legacy = self.store_mod.Store(self.tmp / "csla.db", data_dir=self.tmp)
        legacy.add_material("旧资料-迁移测试", "legacy text " * 50, ext=".md")
        legacy.conn.close()
        return "旧资料-迁移测试"

    def titles(self) -> set:
        return {m["title"] for m in self.server.STORE.list_materials()}

    def test_unbound_store_raises(self):
        with self.assertRaises(self.server.AuthRequired):
            self.server.STORE.list_materials()

    def test_isolation_and_legacy_migration(self):
        s = self.server
        title = self.make_legacy()
        s.activate_user({"id": "uid-a", "username": "alice", "nickname": "小艾"})
        self.assertIn(title, self.titles())
        self.assertFalse((self.tmp / "csla.db").exists())
        self.assertTrue(s.LEGACY_MARK.exists())
        moved = [m for m in s.STORE.list_materials() if m["title"] == title][0]
        self.assertTrue(str(moved["path"]).startswith(str(self.tmp / "users" / "uid-a")))
        self.assertTrue(Path(moved["path"]).is_file())
        self.assertEqual(s.STORE.ensure_user()["name"], "小艾")

        s.STORE.add_material("只属于A", "aaa " * 200, ext=".md")
        s.deactivate_user()
        self.assertFalse(s.STORE.bound)

        s.activate_user({"id": "uid-b", "username": "bob", "nickname": ""})
        self.assertNotIn(title, self.titles())                # 旧数据只给第一个账号
        self.assertNotIn("只属于A", self.titles())
        self.assertEqual(s.STORE.ensure_user()["name"], "bob")

        s.activate_user({"id": "uid-a", "username": "alice"})
        self.assertIn("只属于A", self.titles())

    def test_reject_bad_uid(self):
        with self.assertRaises(ValueError):
            self.server.activate_user({"id": "../evil", "username": "x"})
        self.assertFalse((self.tmp / "evil").exists())


class LocalApiTest(TempDataTest):
    """个人信息 / 资料管理新接口：本机服务跑在随机端口，--no-auth 单用户，数据在临时目录。"""

    def setUp(self):
        super().setUp()
        s = self.server
        self.saved_auth = s.AUTH
        s.AUTH = None
        s.activate_user({"id": "uid-local", "username": "tester"})
        self.httpd = s.QuietHTTPServer(("127.0.0.1", 0), s.Handler)
        self.httpd.flags = []
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.server.AUTH = self.saved_auth
        super().tearDown()

    def raw(self, method: str, path: str, data: bytes | None = None):
        req = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def test_display_name(self):
        status, data = call(self.base, "POST", "/api/profile/name", {"name": "新显示名"})
        self.assertEqual((status, data["name"]), (200, "新显示名"))
        self.assertEqual(call(self.base, "GET", "/api/state")[1]["user"]["name"], "新显示名")
        self.assertEqual(call(self.base, "POST", "/api/profile/name", {"name": " "})[0], 400)
        self.assertEqual(call(self.base, "POST", "/api/profile/name", {"name": "x" * 21})[0], 400)

    def test_avatar_upload_and_reset(self):
        import base64
        png = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
        status, data = call(self.base, "POST", "/api/profile/avatar",
                            {"content": base64.b64encode(png).decode()})
        self.assertEqual(status, 201)
        self.assertTrue(data["avatar"])
        self.assertEqual(call(self.base, "GET", "/api/state")[1]["avatar"], data["avatar"])
        status, headers, body = self.raw("GET", "/api/profile/avatar")
        self.assertEqual((status, headers["Content-Type"], body), (200, "image/png", png))
        for bad in ({"content": "!!!"},                                         # 不是 base64
                    {"content": base64.b64encode(b"GIF89a" + b"\0" * 10).decode()},   # 不是 PNG/JPG
                    {"content": base64.b64encode(b"\xff\xd8\xff" + b"\0" * (1024 * 1024)).decode()}):
            self.assertEqual(call(self.base, "POST", "/api/profile/avatar", bad)[0], 400)
        self.assertEqual(self.raw("DELETE", "/api/profile/avatar")[0], 200)
        self.assertEqual(call(self.base, "GET", "/api/state")[1]["avatar"], "")
        self.assertEqual(self.raw("GET", "/api/profile/avatar")[0], 404)

    def test_profile_month_view_and_download(self):
        s = self.server
        s.STORE.save_profile("# 九月档案", "2026-09")
        s.STORE.save_profile("# 十月档案", "2026-10")
        status, data = call(self.base, "GET", "/api/profile/2026-09")
        self.assertEqual((status, data["content"]), (200, "# 九月档案"))
        status, headers, body = self.raw("GET", "/api/profile/2026-10/download")
        self.assertEqual((status, body.decode("utf-8")), (200, "# 十月档案"))
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(call(self.base, "GET", "/api/profile/2026-08")[0], 404)
        for bad in ("2026-13", "2026-1", "abc"):
            self.assertEqual(call(self.base, "GET", f"/api/profile/{bad}")[0], 400, bad)
            self.assertEqual(self.raw("DELETE", f"/api/profile/{bad}")[0], 400, bad)
        self.assertEqual(self.raw("GET", "/api/profile/..%2F..%2Fcsla.db")[0], 404)   # 路由就不匹配
        self.assertEqual(self.raw("DELETE", "/api/profile/2026-09")[0], 200)
        self.assertEqual([f["month"] for f in call(self.base, "GET", "/api/profile")[1]["files"]],
                         ["2026-10"])

    def test_folder_rename_rules(self):
        s = self.server
        _, data = call(self.base, "GET", "/api/materials")
        builtin = [f for f in data["folders"] if f.get("slug")]
        self.assertTrue(builtin and not any(f["renamable"] for f in builtin))
        status, _ = call(self.base, "POST", f"/api/folders/{builtin[0]['id']}/rename", {"name": "改名"})
        self.assertEqual(status, 403)

        mine = s.STORE.add_folder("我的笔记")
        other = s.STORE.add_folder("别的文件夹")
        _, data = call(self.base, "GET", "/api/materials")
        self.assertTrue(next(f for f in data["folders"] if f["id"] == mine["id"])["renamable"])
        path = f"/api/folders/{mine['id']}/rename"
        self.assertEqual(call(self.base, "POST", path, {"name": "别的文件夹"})[0], 409)
        self.assertEqual(call(self.base, "POST", path, {"name": ""})[0], 400)
        self.assertEqual(call(self.base, "POST", path, {"name": "x" * 41})[0], 400)
        status, data = call(self.base, "POST", path, {"name": "期末笔记"})
        self.assertEqual((status, data["folder"]["name"]), (200, "期末笔记"))
        self.assertEqual(call(self.base, "POST", "/api/folders/nope/rename", {"name": "a"})[0], 404)
        self.assertTrue(other)

    def test_move_material(self):
        s = self.server
        folder = s.STORE.add_folder("移动目标")
        mat = s.STORE.add_material("待移动资料", "move me " * 80, ext=".md")
        status, _ = call(self.base, "POST", f"/api/materials/{mat['id']}/move", {"folder_id": folder["id"]})
        self.assertEqual(status, 200)
        self.assertEqual(s.STORE.material(mat["id"])["folder_id"], folder["id"])
        self.assertEqual(call(self.base, "POST", f"/api/materials/{mat['id']}/move",
                              {"folder_id": "nope"})[0], 404)
        self.assertEqual(call(self.base, "POST", "/api/materials/nope/move",
                              {"folder_id": folder["id"]})[0], 404)

    def test_concurrent_requests(self):
        """页面加载时浏览器会并发发请求；共用一条 sqlite 连接时曾卡成 database is locked。"""
        statuses = []

        def worker(i):
            for j in range(10):
                if (i + j) % 3 == 0:
                    statuses.append(call(self.base, "POST", "/api/profile/meta", {"major": f"m{i}{j}"})[0])
                else:
                    statuses.append(call(self.base, "GET", ("/api/state", "/api/materials", "/api/profile")[j % 3])[0])

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(statuses), 80)
        self.assertNotIn(500, statuses)
        self.assertEqual(call(self.base, "POST", "/api/profile/meta", {"major": "ok"})[0], 201)


if __name__ == "__main__":
    unittest.main(verbosity=2)
