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

    def test_sessions_list_and_revoke(self):
        self.register("nina_14")
        first = call(self.base, "POST", "/auth/login",
                     {"username": "nina_14", "password": PASSWORD, "device": "PC-A · Windows"})[1]
        second = call(self.base, "POST", "/auth/login",
                      {"username": "nina_14", "password": PASSWORD, "device": "MAC-B · macOS"})[1]
        third = self.login("nina_14")[1]
        a1, a2, a3 = (d["tokens"]["access_token"] for d in (first, second, third))
        status, data = call(self.base, "GET", "/auth/sessions", token=a1)
        self.assertEqual(status, 200)
        rows = data["sessions"]
        self.assertEqual(len(rows), 3)
        self.assertTrue(rows[0]["current"] and rows[0]["device"] == "PC-A · Windows")
        self.assertIn("未命名设备", [r["device"] for r in rows])
        self.assertNotIn("access_hash", rows[0])

        # 不能用"下线"踢自己；踢不存在的设备 404
        self.assertEqual(call(self.base, "POST", "/auth/sessions/revoke",
                              {"session_id": rows[0]["id"]}, token=a1)[0], 400)
        self.assertEqual(call(self.base, "POST", "/auth/sessions/revoke",
                              {"session_id": "nope"}, token=a1)[0], 404)
        mac = next(r for r in rows if r["device"] == "MAC-B · macOS")
        status, data = call(self.base, "POST", "/auth/sessions/revoke", {"session_id": mac["id"]}, token=a1)
        self.assertEqual((status, data["revoked"]), (200, 1))
        self.assertEqual(call(self.base, "GET", "/auth/me", token=a2)[0], 401)

        # 刷新轮换后设备名与登录时间不变
        status, rotated = call(self.base, "POST", "/auth/refresh",
                               {"refresh_token": first["tokens"]["refresh_token"]})
        self.assertEqual(status, 200)
        a1 = rotated["tokens"]["access_token"]
        cur = call(self.base, "GET", "/auth/sessions", token=a1)[1]["sessions"][0]
        self.assertEqual((cur["device"], cur["login_at"]), ("PC-A · Windows", rows[0]["login_at"]))

        status, data = call(self.base, "POST", "/auth/sessions/revoke", {"others": True}, token=a1)
        self.assertEqual((status, data["revoked"]), (200, 1))
        self.assertEqual(call(self.base, "GET", "/auth/me", token=a3)[0], 401)
        self.assertEqual(len(call(self.base, "GET", "/auth/sessions", token=a1)[1]["sessions"]), 1)
        self.assertEqual(call(self.base, "GET", "/auth/sessions")[0], 401)

    def test_delete_account(self):
        self.register("oscar_15")
        access = self.login("oscar_15")[1]["tokens"]["access_token"]
        other = self.login("oscar_15")[1]["tokens"]["access_token"]
        status, data = call(self.base, "POST", "/auth/delete", {"password": "wrong123"}, token=access)
        self.assertEqual((status, data["error"]["code"]), (401, "invalid_credentials"))
        self.assertEqual(call(self.base, "GET", "/auth/me", token=access)[0], 200)   # 密码错不影响登录
        status, data = call(self.base, "POST", "/auth/delete", {"password": PASSWORD}, token=access)
        self.assertEqual(status, 200)
        self.assertTrue(data["user_id"])
        for token in (access, other):
            self.assertEqual(call(self.base, "GET", "/auth/me", token=token)[0], 401)
        self.assertEqual(self.login("oscar_15")[0], 401)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id=?", (data["user_id"],)).fetchone()[0], 0)
        self.assertEqual(self.register("oscar_15")[0], 201)                        # 用户名已释放

    def test_delete_account_rate_limited(self):
        self.register("paul_16")
        access = self.login("paul_16")[1]["tokens"]["access_token"]
        for _ in range(auth_server.LOGIN_USER_LIMIT):
            call(self.base, "POST", "/auth/delete", {"password": "wrong123"}, token=access)
        status, _ = call(self.base, "POST", "/auth/delete", {"password": PASSWORD}, token=access)
        self.assertEqual(status, 429)
        self.assertEqual(call(self.base, "GET", "/auth/me", token=access)[0], 200)


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

    def test_client_sessions_and_delete(self):
        self.register("quinn_17")
        c = self.client("s6.json")
        c.login("quinn_17", PASSWORD)
        other = self.client("s7.json")
        other.login("quinn_17", PASSWORD)
        rows = c.sessions()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["device"], auth_client.device_name())
        self.assertEqual(c.revoke_sessions(others=True), 1)
        other.verify(force=True)
        self.assertFalse(other.logged_in)
        with self.assertRaises(auth_client.AuthFailed):
            c.delete_account("wrong123")
        self.assertTrue(c.logged_in)
        uid = c.delete_account(PASSWORD)
        self.assertTrue(uid)
        self.assertFalse(c.logged_in)
        self.assertFalse((self.tmp / "s6.json").exists())

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

    def test_meta_validation(self):
        path = "/api/profile/meta"
        for bad in ({"age": "abc"}, {"age": "5"}, {"age": "101"}, {"age": "2.5"},
                    {"major": "x" * 31}, {"gender": "x" * 31}, {"needs": "x" * 201}, {"major": 3}):
            self.assertEqual(call(self.base, "POST", path, bad)[0], 400, bad)
        self.assertEqual(call(self.base, "POST", path, {"age": " 021 ", "major": " 计算机 "})[0], 201)
        user = self.server.STORE.ensure_user()
        self.assertEqual((user["age"], user["major"]), ("21", "计算机"))
        self.assertEqual(call(self.base, "POST", path, {"age": "", "major": ""})[0], 201)  # 允许清空
        self.assertEqual(self.server.STORE.ensure_user()["age"], "")

    def test_material_meta(self):
        s = self.server
        subject = s.STORE.subjects()[0]["name"]
        mat = s.STORE.add_material("原标题", "edit me " * 80, ext=".md")
        path = f"/api/materials/{mat['id']}/meta"
        status, data = call(self.base, "POST", path, {"title": " 新标题 ", "subject": subject})
        self.assertEqual(status, 200)
        self.assertEqual((data["material"]["title"], data["material"]["subject"]), ("新标题", subject))
        self.assertEqual(call(self.base, "POST", path, {"subject": ""})[0], 200)       # 取消科目
        self.assertEqual(s.STORE.material(mat["id"])["subject"], "")
        self.assertEqual(call(self.base, "POST", path, {"subject": "不存在的科目"})[0], 400)
        self.assertEqual(call(self.base, "POST", path, {"title": " "})[0], 400)
        self.assertEqual(call(self.base, "POST", path, {"title": "x" * 81})[0], 400)
        self.assertEqual(call(self.base, "POST", path, {})[0], 400)
        self.assertEqual(call(self.base, "POST", "/api/materials/nope/meta", {"title": "a"})[0], 404)

        core = s.STORE.add_material("核心 · 测试", "core " * 80, source_url="内置示例资料（可删除）")
        core_path = f"/api/materials/{core['id']}/meta"
        self.assertEqual(call(self.base, "POST", core_path, {"title": "改掉"})[0], 403)
        self.assertEqual(call(self.base, "POST", core_path, {"subject": subject})[0], 200)  # 科目可改

    def test_material_batch(self):
        s = self.server
        folder = s.STORE.add_folder("批量目标")
        ids = [s.STORE.add_material(f"批量{i}", f"batch {i} " * 80)["id"] for i in range(3)]
        path = "/api/materials/batch"
        status, data = call(self.base, "POST", path,
                            {"action": "move", "ids": ids + ["nope", ids[0]], "folder_id": folder["id"]})
        self.assertEqual((status, data["done"], data["missing"]), (200, 3, 1))
        self.assertTrue(all(s.STORE.material(i)["folder_id"] == folder["id"] for i in ids))
        for bad in ({"action": "copy", "ids": ids}, {"action": "delete", "ids": []},
                    {"action": "delete", "ids": "abc"}, {"action": "delete", "ids": [1]},
                    {"action": "delete", "ids": ["x"] * 201}):
            self.assertEqual(call(self.base, "POST", path, bad)[0], 400, bad)
        self.assertEqual(call(self.base, "POST", path,
                              {"action": "move", "ids": ids, "folder_id": "nope"})[0], 404)
        status, data = call(self.base, "POST", path, {"action": "delete", "ids": ids[:2]})
        self.assertEqual((status, data["done"]), (200, 2))
        self.assertIsNone(s.STORE.material(ids[0]))
        self.assertTrue(s.STORE.material(ids[2]))

    def test_purge_user_data(self):
        s = self.server
        for bad in ("", "../users", "a/b", "not-here"):
            self.assertFalse(s.purge_user_data(bad), bad)
        self.assertTrue(s.USERS_DIR.is_dir())
        s.deactivate_user(close=True)
        self.assertTrue(s.purge_user_data("uid-local"))
        self.assertFalse((s.USERS_DIR / "uid-local").exists())

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

    def test_docx_upload_keeps_original_and_renders(self):
        import base64
        import extras
        doc = extras.build_docx("测试文档", [
            ("h2", "第一章 <script>"), ("p", "正文段落"), ("bullet", "要点一"),
            ("table", [["列A", "列B"], ["1", "2"]])])
        status, data = call(self.base, "POST", "/api/materials/import", {
            "filename": "课件.docx", "content": base64.b64encode(doc).decode()})
        self.assertEqual(status, 201)
        mid = data["material"]["id"]
        status, detail = call(self.base, "GET", f"/api/materials/{mid}")
        self.assertEqual((status, detail["format"], detail["has_original"]), (200, "docx", True))
        html = detail["html"]
        for piece in ("<li>要点一", "<table>", "<td>", "正文段落"):
            self.assertIn(piece, html)
        self.assertIn("&lt;script&gt;", html)               # 文字一律转义
        self.assertNotIn("<script>", html)
        self.assertIn("第一章", detail["content"])          # 抽出的文字照旧建索引
        status, headers, body = self.raw("GET", f"/api/materials/{mid}/original")
        self.assertEqual((status, body), (200, doc))
        self.assertIn("attachment", headers["Content-Disposition"])
        original = self.server.STORE.material_original(mid)
        self.assertTrue(original and original.is_file())
        self.assertEqual(self.raw("DELETE", f"/api/materials/{mid}")[0], 200)
        self.assertFalse(original.exists())                 # 删资料时原文件一起删

    def test_markdown_material_has_no_original(self):
        mat = self.server.STORE.add_material("笔记", "# 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |", ext=".md")
        status, detail = call(self.base, "GET", f"/api/materials/{mat['id']}")
        self.assertEqual((status, detail["format"], detail["has_original"], detail["html"]),
                         (200, "markdown", False, ""))
        self.assertEqual(self.raw("GET", f"/api/materials/{mat['id']}/original")[0], 404)
        self.assertEqual(call(self.base, "GET", "/api/materials/nope")[0], 404)


class DocxHtmlTest(unittest.TestCase):
    """docx → HTML：标题样式、有序/无序列表、粗斜体、链接只放行 http(s)、合并单元格。"""

    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'

    def make(self, body: str) -> bytes:
        import io
        import zipfile
        styles = (f'<w:styles {self.W}><w:style w:type="paragraph" w:styleId="1">'
                  '<w:name w:val="heading 1"/></w:style>'
                  '<w:style w:type="paragraph" w:styleId="a5"><w:name w:val="标题 2"/></w:style></w:styles>')
        numbering = (f'<w:numbering {self.W}>'
                     '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl>'
                     '<w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
                     '<w:num w:numId="3"><w:abstractNumId w:val="0"/></w:num></w:numbering>')
        rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId9" Type="hyperlink" Target="https://example.com/a?b=1&amp;c=2" TargetMode="External"/>'
                '<Relationship Id="rId8" Type="hyperlink" Target="javascript:alert(1)" TargetMode="External"/>'
                '</Relationships>')
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", f"<w:document {self.W}><w:body>{body}</w:body></w:document>")
            zf.writestr("word/styles.xml", styles)
            zf.writestr("word/numbering.xml", numbering)
            zf.writestr("word/_rels/document.xml.rels", rels)
        return buf.getvalue()

    @staticmethod
    def p(text: str, ppr: str = "", rpr: str = "") -> str:
        return f'<w:p><w:pPr>{ppr}</w:pPr><w:r><w:rPr>{rpr}</w:rPr><w:t>{text}</w:t></w:r></w:p>'

    def test_structure(self):
        import extras
        num = lambda lvl: f'<w:numPr><w:ilvl w:val="{lvl}"/><w:numId w:val="3"/></w:numPr>'  # noqa: E731
        body = (self.p("章", '<w:pStyle w:val="1"/>') + self.p("节", '<w:pStyle w:val="a5"/>')
                + self.p("一", num(0)) + self.p("子", num(1)) + self.p("二", num(0))
                + self.p("粗", rpr="<w:b/>") + self.p("不粗", rpr='<w:b w:val="0"/><w:i/>')
                + '<w:p><w:hyperlink r:id="rId9"><w:r><w:t>好链接</w:t></w:r></w:hyperlink>'
                  '<w:hyperlink r:id="rId8"><w:r><w:t>坏链接</w:t></w:r></w:hyperlink></w:p>'
                + '<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>' + self.p("合并")
                + '</w:tc></w:tr><w:tr><w:tc>' + self.p("a") + '</w:tc><w:tc>' + self.p("b")
                + '</w:tc></w:tr></w:tbl>')
        html = extras.docx_to_html(self.make(body))
        self.assertIn("<h1>章</h1><h2>节</h2>", html)
        self.assertIn("<ol><li>一<ul><li>子</li></ul></li><li>二</li></ol>", html)
        self.assertIn("<p><strong>粗</strong></p><p><em>不粗</em></p>", html)
        self.assertIn('<a href="https://example.com/a?b=1&amp;c=2"', html)
        self.assertNotIn("javascript", html)
        self.assertIn("坏链接", html)
        self.assertIn('<td colspan="2"><p>合并</p></td>', html)

    def test_rejects_non_docx(self):
        import extras
        with self.assertRaises(Exception):
            extras.docx_to_html(b"not a zip")


if __name__ == "__main__":
    unittest.main(verbosity=2)
