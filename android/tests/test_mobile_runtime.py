"""Integration regressions use temporary storage and a fake in-memory key vault.
No external requests, model charges or modifications to any existing user data.
"""
import base64
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO / "android/app/src/main/python"),
                str(REPO / "AIassistant-v4/AIassistant/app")]
import mobile_runtime


class FakeVault:
    value = ""
    def readKey(self):
        return self.value
    def writeKey(self, value):
        self.value = value


class MobileIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="csla-mobile-test-")
        cls.root = Path(cls.temp.name).resolve()
        os.environ["CSLA_DATA_DIR"] = str(cls.root)
        os.environ["CSLA_REFERENCE_DIR"] = str(cls.root / "reference_library")
        import store
        before = store.Store(cls.root / "csla.db", cls.root)
        before.conn.execute("""CREATE TABLE mobile_jobs (
            chapter_id TEXT PRIMARY KEY, section_id TEXT, status TEXT,
            updated_at TEXT, message TEXT)""")
        subject = before.add_subject("重启恢复测试", is_builtin=False)
        cls.recovered_id = before.add_chapter(subject["id"], "实际存在的章节")["id"]
        before.conn.execute("INSERT INTO mobile_jobs VALUES (?,'one','running','','')", (cls.recovered_id,))
        before.conn.execute("INSERT INTO mobile_jobs VALUES ('deleted-before-restart','one','running','','')")
        before.conn.commit()
        before.conn.close()
        cls.vault = FakeVault()
        cls.info = json.loads(mobile_runtime.start(cls.root, cls.vault))
        cls.base = cls.info["url"]
        cls.cookie = cls.info["cookie"].split(";")[0]
        import server
        cls.server = server
        cls.store = server.STORE

    @classmethod
    def tearDownClass(cls):
        mobile_runtime._server.shutdown()
        mobile_runtime._server.server_close()
        mobile_runtime._server = None
        cls.store._store.conn.close()
        cls.temp.cleanup()

    def request(self, path, method="GET", data=None, headers=None, authorized=True):
        header = {"Content-Type": "application/json"}
        if authorized:
            header["Cookie"] = self.cookie
        header.update(headers or {})
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, body, header, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers

    def test_loopback_guards_static_api_origin_host_and_auth_routes(self):
        for path in ("/", "/app.js", "/api/state", "/api/materials"):
            self.assertEqual(self.request(path, authorized=False)[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Cookie": "csla_phone=wrong"})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Origin": "https://example.com"})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Host": "example.com"})[0], 403)
        self.assertEqual(self.request("/api/auth/login", "POST", {})[0], 404)
        self.assertEqual(self.request("/api/admin/users")[0], 404)

    def test_offline_first_state_and_all_data_beneath_phone_root(self):
        status, body, headers = self.request("/api/state")
        state = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(state["auth"]["local"])
        self.assertFalse(state["auth"]["is_admin"])
        self.assertFalse(state["mock"])
        self.assertIn("object-src 'none'", headers["Content-Security-Policy"])
        for mat in self.store.list_materials():
            for field in ("path", "original"):
                if mat.get(field):
                    self.assertIn(self.root, Path(mat[field]).parents)
        self.assertEqual(self.store.db_path.parent, self.root)

    def test_model_key_never_in_sqlite_files_or_state(self):
        secret = "sk-test-mobile-never-store-in-sqlite"
        self.store.set_config("api_key", secret)
        self.assertTrue(self.store.has_api_key())
        self.assertEqual(self.vault.value, secret)
        self.assertEqual(self.store._store.conn.execute(
            "SELECT count(*) FROM config WHERE key='api_key'").fetchone()[0], 0)
        self.assertNotIn(secret.encode(), self.request("/api/state")[1])
        for file in self.root.rglob("*"):
            if file.is_file():
                self.assertNotIn(secret.encode(), file.read_bytes(), str(file))
        self.assertEqual(self.request("/api/mobile/key/clear", "POST", {})[0], 200)
        self.assertFalse(self.store.has_api_key())

    def test_running_job_recovered_as_interrupted(self):
        jobs = json.loads(self.request("/api/mobile/status")[1])["jobs"]
        self.assertEqual(next(j for j in jobs if j["chapter_id"] == self.recovered_id)["status"], "interrupted")
        self.assertFalse(any(j["chapter_id"] == "deleted-before-restart" for j in jobs))

    def test_outline_parser_cancellation_preserves_saved_outline_and_retry(self):
        """Use the real SSE parser, including cancellation at DONE/exhaustion."""
        import lessons
        sid = self.store.add_subject("后台大纲隔离测试", is_builtin=False)["id"]
        cid = self.store.add_chapter(sid, "旧目录", outline="- 已保存小节")["id"]
        meta = lessons.plan(self.store.chapter(cid))
        meta["sections"][0].update(content="已保存讲义" * 100, revision="old")
        lessons.publish(self.store, cid, meta)
        self.store.set_config("api_key", "sk-test-in-memory")
        original = self.store.chapter(cid)
        text = json.dumps([{"title": "新小节", "query": "新小节"}], ensure_ascii=False)
        content_line = ("data: " + json.dumps({"choices": [
            {"delta": {"content": text}, "finish_reason": "stop"}]}, ensure_ascii=False) + "\n").encode()

        class Response:
            closed = False
            def __init__(self, cancel, tail):
                self.cancel, self.tail = cancel, tail
            def __iter__(self):
                yield content_line
                if self.cancel:
                    mobile_runtime.set_foreground(False)
                    mobile_runtime.set_foreground(True)
                if self.tail:
                    yield b"data: [DONE]\n"
            def close(self):
                self.closed = True

        try:
            for tail in (True, False):
                with self.subTest(done_line=tail):
                    response = Response(True, tail)
                    with patch.object(self.server.deepseek.DeepSeekClient, "_request", return_value=response), \
                         patch.object(self.server.references, "evidence", return_value=("", [])):
                        code, data, _ = self.request(f"/api/chapters/{cid}/tutor", "POST", {"action": "outline"})
                    self.assertEqual(code, 200)
                    self.assertNotIn(b"event: completed", data)
                    self.assertTrue(response.closed)
                    current = self.store.chapter(cid)
                    for field in ("outline", "lecture", "lecture_meta"):
                        self.assertEqual(current[field], original[field])
                    jobs = json.loads(self.request("/api/mobile/status")[1])["jobs"]
                    self.assertEqual(next(j for j in jobs if j["chapter_id"] == cid)["status"], "interrupted")
            response = Response(False, True)
            with patch.object(self.server.deepseek.DeepSeekClient, "_request", return_value=response), \
                 patch.object(self.server.references, "evidence", return_value=("", [])):
                _, data, _ = self.request(f"/api/chapters/{cid}/tutor", "POST", {"action": "outline"})
            self.assertIn(b"event: completed", data)
            self.assertEqual(lessons.plan(self.store.chapter(cid))["sections"][0]["title"], "新小节")
        finally:
            mobile_runtime.set_foreground(True)
            self.store.set_config("api_key", "")
            self.request(f"/api/subjects/{sid}", "DELETE")

    def test_deleted_chapter_and_subject_jobs_cannot_return_from_late_callback(self):
        sid = self.store.add_subject("任务清理隔离测试", is_builtin=False)["id"]
        cid = self.store.add_chapter(sid, "删除中的章节", outline="- 小节")["id"]
        other = self.store.add_chapter(sid, "随科目删除")["id"]
        self.store.set_config("api_key", "sk-test-in-memory")
        conn = self.store._store.conn
        conn.execute("INSERT INTO mobile_jobs VALUES (?,'','running','','')", (other,))
        conn.commit()

        def deleted_stream(client, messages, **kwargs):
            self.assertEqual(self.request(f"/api/chapters/{cid}", "DELETE")[0], 200)
            yield "尚未完成"
        try:
            with patch.object(self.server.deepseek.DeepSeekClient, "stream_chat", deleted_stream):
                self.request(f"/api/chapters/{cid}/tutor", "POST", {})
            jobs = json.loads(self.request("/api/mobile/status")[1])["jobs"]
            self.assertFalse(any(j["chapter_id"] == cid for j in jobs))
            self.assertTrue(any(j["chapter_id"] == other for j in jobs))
            self.assertEqual(self.request(f"/api/subjects/{sid}", "DELETE")[0], 200)
            jobs = json.loads(self.request("/api/mobile/status")[1])["jobs"]
            self.assertFalse(any(j["chapter_id"] == other for j in jobs))
        finally:
            self.store.set_config("api_key", "")
            if self.store.subject(sid):
                self.request(f"/api/subjects/{sid}", "DELETE")

    def test_import_read_download_and_path_escape_rejection(self):
        content = "# 手机测试资料\n\n补码是模运算中的有符号表示。\n" * 30
        code, payload, _ = self.request("/api/import", "POST", {
            "filename": "手机测试.md",
            "content": base64.b64encode(content.encode()).decode()})
        # The shared desktop API is /api/materials/import in V4.
        if code == 404:
            code, payload, _ = self.request("/api/materials/import", "POST", {
                "filename": "手机测试.md",
                "content": base64.b64encode(content.encode()).decode()})
        self.assertEqual(code, 201, payload)
        mat = json.loads(payload)["material"]
        mid = mat["id"]
        try:
            info = json.loads(mobile_runtime.source_info(mid))
            self.assertIn(self.root, Path(info["path"]).parents)
            self.assertIn("补码".encode(), self.request(f"/api/materials/{mid}/source")[1])
            self.assertEqual(self.request(f"/api/materials/{mid}/source?download=1")[0], 200)
            self.store._store.conn.execute("UPDATE materials SET original=?,path=? WHERE id=?",
                ("/etc/hosts", "/etc/hosts", mid))
            self.store._store.conn.commit()
            with self.assertRaises(ValueError):
                mobile_runtime.source_info(mid)
        finally:
            # Restore safe paths before deletion (never delete the escape target).
            self.store._store.conn.execute("UPDATE materials SET original=?,path=? WHERE id=?",
                (mat.get("original", ""), mat["path"], mid))
            self.store._store.conn.commit()
            self.request(f"/api/materials/{mid}", "DELETE")

    def test_mobile_tutor_one_section_saved_then_background_cancel_and_retry(self):
        import curriculum
        import lessons
        sid = self.store.add_subject("手机隔离测试", is_builtin=False)["id"]
        chapter = self.store.add_chapter(sid, "模运算", outline="- 补码\n- 溢出")
        cid = chapter["id"]
        self.store.set_config("api_key", "sk-test-in-memory")
        text = "## 知识点\n" + "解释补码的模运算意义。" * 80
        calls = []

        def fake_stream(client, messages, **kwargs):
            calls.append(messages)
            yield text
            kwargs["on_finish"]("stop")

        try:
            with patch.object(self.server.deepseek.DeepSeekClient, "stream_chat", fake_stream), \
                 patch.object(curriculum, "valid_section", return_value=True):
                code, data, _ = self.request(f"/api/chapters/{cid}/tutor", "POST", {})
                self.assertEqual(code, 200, data)
                self.assertIn(b"event: completed", data)
                current = self.store.chapter(cid)
                meta = lessons.plan(current)
                self.assertEqual(sum(bool(u.get("content")) for u in meta["sections"]), 1)
                self.assertEqual(len(calls), 1)
                saved = current["lecture"]

                def interrupted(client, messages, **kwargs):
                    mobile_runtime.set_foreground(False)
                    mobile_runtime.set_foreground(True)
                    yield "未完成内容"
                with patch.object(self.server.deepseek.DeepSeekClient, "stream_chat", interrupted):
                    self.request(f"/api/chapters/{cid}/tutor", "POST", {})
                self.assertEqual(self.store.chapter(cid)["lecture"], saved)
                jobs = json.loads(self.request("/api/mobile/status")[1])["jobs"]
                self.assertEqual(next(j for j in jobs if j["chapter_id"] == cid)["status"], "interrupted")
                self.request(f"/api/chapters/{cid}/tutor", "POST", {})
                meta = lessons.plan(self.store.chapter(cid))
                self.assertEqual(sum(bool(u.get("content")) for u in meta["sections"]), 2)
        finally:
            mobile_runtime.set_foreground(True)
            self.store.set_config("api_key", "")
            self.request(f"/api/subjects/{sid}", "DELETE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
