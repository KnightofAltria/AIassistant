"""Phone business workflows; temporary database, real parsers, fake model only."""
import base64
import io
import json
import socket
import tempfile
import unittest
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch

import test_mobile_runtime as reliability
mobile_runtime = reliability.mobile_runtime


def pdf_fixture(text="Binary integer representation", encrypted=False):
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [5 0 R] /Count 1 >>",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else "0 0 m"
    objects.extend([f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
                    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    "/Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>"])
    result, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{i} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    encryption = " /Encrypt << /Filter /Standard >>" if encrypted else ""
    return result + f"trailer\n<< /Size 6 /Root 1 0 R{encryption} >>\nstartxref\n{xref}\n%%EOF\n".encode()


def full_section():
    return "\n\n".join("### " + h + "\n" +
        "以八位补码为例，先确定位宽与符号，再计算编码并验证表示范围。" * 10
        for h in ("学习目标与前置知识", "概念与原理", "公式或实现步骤",
                  "例题与逐步解析", "易错点与自测解析"))


class FullMigration(unittest.TestCase):
    request = reliability.MobileIntegration.request

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="csla-full-migration-")
        cls.root = Path(cls.temp.name)
        cls.vault = reliability.FakeVault()
        cls.vault.value = ""
        cls.info = json.loads(mobile_runtime.start(cls.root, cls.vault))
        cls.base = cls.info["url"]
        cls.cookie = cls.info["cookie"].split(";")[0]
        import server
        cls.server, cls.store = server, server.STORE

    @classmethod
    def tearDownClass(cls):
        mobile_runtime._server.shutdown()
        mobile_runtime._server.server_close()
        mobile_runtime._server = None
        cls.store._store.conn.close()
        cls.temp.cleanup()

    def data(self, path, method="GET", body=None, expected=200):
        status, raw, _ = self.request(path, method, body)
        self.assertEqual(status, expected, raw)
        return json.loads(raw)

    def upload(self, name, raw, **metadata):
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        prepared = self.data("/api/mobile/import/prepare", "POST",
                             dict(filename=name, size=len(raw), **metadata), 201)
        req = urllib.request.Request(self.base + "/api/mobile/import", raw, {
            "Cookie": self.cookie, "Content-Type": "application/octet-stream",
            "X-CSLA-Upload": prepared["upload_id"]}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as response:
            self.assertEqual(response.status, 201)
            return json.loads(response.read()), prepared["upload_id"]

    def new_chapter(self, name):
        subject = self.data("/api/subjects", "POST", {"name": name}, 201)["subject"]
        chapter = self.data(f"/api/subjects/{subject['id']}/chapters", "POST",
                            {"title": "整数表示", "outline": "- 补码\n- 溢出\n- 位宽"}, 201)["chapter"]
        self.addCleanup(lambda: self.request(f"/api/subjects/{subject['id']}", "DELETE"))
        return subject, chapter

    def test_offline_subject_chapter_edit_and_no_key_chat_is_atomic(self):
        self.store.set_config("api_key", "")
        before = len(self.store.list_conversations())
        self.assertEqual(self.request("/api/chat/stream", "POST", {"text": "未配密钥"})[0], 401)
        self.assertEqual(len(self.store.list_conversations()), before)
        _, chapter = self.new_chapter("离线手动科目")
        self.data(f"/api/chapters/{chapter['id']}", "PATCH", {"title": "改名章节", "outline": "- 手动大纲"})
        detail = self.data(f"/api/chapters/{chapter['id']}")["chapter"]
        self.assertEqual(detail["title"], "改名章节")
        self.assertEqual(detail["outline"], "- 手动大纲")

    def test_local_core_owner_crud_batch_order_and_account_isolation(self):
        folders = self.data("/api/materials")
        self.assertTrue(folders["can_edit_core"])
        self.assertFalse(folders["is_admin"])
        core = next(f for f in folders["folders"] if f["is_shared"])
        self.assertTrue(core["editable"])
        folder = self.data("/api/folders", "POST", {"name": "本地核心测试", "is_shared": True}, 201)["folder"]
        self.addCleanup(lambda: self.request(f"/api/folders/{folder['id']}?delete_materials=1", "DELETE"))
        mids = []
        for title in ("第一份", "第二份"):
            mat = self.data("/api/materials", "POST", {"title": title, "text": "补码二进制整数表示",
                             "folder_id": core["id"]}, 201)["material"]
            mids.append(mat["id"])
            self.addCleanup(lambda mid=mat["id"]: self.request(f"/api/materials/{mid}", "DELETE"))
        self.data(f"/api/materials/{mids[0]}/meta", "POST", {"title": "可编辑核心资料"})
        self.assertTrue(self.data(f"/api/folders/{core['id']}/references")["editable"])
        self.data("/api/materials/batch", "POST", {"action": "move", "ids": mids, "folder_id": folder["id"]})
        self.data("/api/materials/reorder", "POST", {"ids": list(reversed(mids))})
        ordered = self.data(f"/api/materials?folder={folder['id']}")["materials"]
        self.assertEqual([m["id"] for m in ordered], list(reversed(mids)))
        self.assertEqual(self.request("/api/admin/users", "POST", {"action": "create"})[0], 404)
        self.assertEqual(self.request("/api/auth/sessions")[0], 404)

    def test_binary_import_all_formats_originals_and_modified_text(self):
        from extras import build_docx
        docx = build_docx("手机 Word", [("p", "补码与溢出。")])
        examples = {"讲义.md": "# 第一章\n补码与溢出\n", "笔记.txt": "文本笔记",
                    "数据.csv": "a,b\n1,2", "数据.json": '{"topic":"补码"}', "提纲.markdown": "# 提纲\n整数"}
        binary = {"教材.pdf": pdf_fixture(), "课件.docx": docx}
        for name, raw in {**{k: v.encode() for k, v in examples.items()}, **binary}.items():
            with self.subTest(name=name):
                result, token = self.upload(name, raw)
                mid = result["material"]["id"]
                try:
                    self.assertEqual(self.request(f"/api/materials/{mid}/original")[1], raw)
                    self.assertGreater(result["chars"], 0)
                    if name.endswith(".pdf"):
                        self.assertEqual(result["pages"], 1)
                    # Consumed tokens cannot duplicate a successful import.
                    req = urllib.request.Request(self.base + "/api/mobile/import", raw,
                        {"Cookie": self.cookie, "Content-Type": "application/octet-stream",
                         "X-CSLA-Upload": token}, method="POST")
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(req)
                    self.assertEqual(error.exception.code, 409)
                finally:
                    self.request(f"/api/materials/{mid}", "DELETE")
        result, _ = self.upload("可编辑.txt", b"Original text", text="修改后的文本")
        mid = result["material"]["id"]
        try:
            self.assertIn("修改后的文本", self.store.get_material_text(mid))
            self.assertEqual(self.request(f"/api/materials/{mid}/original")[1], b"Original text")
        finally:
            self.request(f"/api/materials/{mid}", "DELETE")

    def test_binary_import_cancel_truncated_oversize_and_invalid_pdf_no_rows(self):
        before = len(self.store.list_materials())
        prepared = self.data("/api/mobile/import/prepare", "POST", {"filename": "取消.txt", "size": 64}, 201)
        self.data("/api/mobile/import/cancel", "POST", {"upload_id": prepared["upload_id"]})
        prepared = self.data("/api/mobile/import/prepare", "POST", {"filename": "中断.txt", "size": 64}, 201)
        origin = urllib.parse.urlparse(self.base)
        with socket.create_connection((origin.hostname, origin.port), timeout=5) as connection:
            header = (f"POST /api/mobile/import HTTP/1.1\r\nHost: {origin.netloc}\r\nCookie: {self.cookie}\r\n"
                      f"Content-Type: application/octet-stream\r\nX-CSLA-Upload: {prepared['upload_id']}\r\n"
                      "Content-Length: 64\r\nConnection: close\r\n\r\n")
            connection.sendall(header.encode() + b"incomplete")
            connection.shutdown(socket.SHUT_WR)
            self.assertIn(b"400", connection.recv(4096))
        self.assertEqual(self.request("/api/mobile/import/prepare", "POST",
                         {"filename": "超限.pdf", "size": 33 * 1024 * 1024})[0], 400)
        for raw in (pdf_fixture(""), pdf_fixture(encrypted=True), b"not a PDF"):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.upload("坏文件.pdf", raw)
            self.assertEqual(error.exception.code, 400)
        self.assertEqual(len(self.store.list_materials()), before)

    def test_preferences_and_session_survive_different_origin_and_sanitize(self):
        self.data("/api/mobile/preferences", "POST", {"motion": False, "largeText": True, "api_key": "ignored"})
        self.data("/api/mobile/session", "POST", {"view": "study", "chapter_id": "../../secret",
                                                "chat_draft": "中文草稿", "api_key": "ignored"})
        self.assertEqual(self.data("/api/mobile/preferences"), {"motion": False, "largeText": True})
        session = self.data("/api/mobile/session")
        self.assertEqual(session.get("chapter_id", ""), "")
        self.assertEqual(session["chat_draft"], "中文草稿")
        # Recreate the server on a fresh port against the same temporary database.
        mobile_runtime._server.shutdown()
        mobile_runtime._server.server_close()
        mobile_runtime._server = None
        self.store._store.conn.close()
        info = json.loads(mobile_runtime.start(self.root, self.vault))
        self.__class__.base = info["url"]
        self.__class__.cookie = info["cookie"].split(";")[0]
        self.assertEqual(self.data("/api/mobile/preferences"), {"motion": False, "largeText": True})
        self.assertEqual(self.data("/api/mobile/session")["chat_draft"], "中文草稿")
        self.assertIn(b'"largeText": true', self.request("/ui.js")[1])
        self.data("/api/mobile/session", "POST", {})

    def test_single_then_all_generation_real_validator_read_progress_and_markdown(self):
        import lessons
        _, chapter = self.new_chapter("整章生成测试")
        cid = chapter["id"]
        self.store.set_config("api_key", "in-memory-fake")
        self.addCleanup(lambda: self.store.set_config("api_key", ""))
        calls = []
        def stream(client, messages, **kwargs):
            calls.append(1)
            yield full_section()
            kwargs["on_finish"]("stop")
        with patch.object(self.server.deepseek.DeepSeekClient, "stream_chat", stream):
            self.assertIn(b"event: completed", self.request(f"/api/chapters/{cid}/tutor", "POST", {})[1])
            meta = lessons.plan(self.store.chapter(cid))
            self.assertEqual(meta["completed_units"], 1)
            first = self.root / "lectures" / cid / f"section-{meta['sections'][0]['id']}.md"
            stamp = first.stat().st_mtime_ns
            _, response, _ = self.request(f"/api/chapters/{cid}/tutor", "POST", {"all_sections": True})
            self.assertIn(b"event: completed", response)
            final = lessons.plan(self.store.chapter(cid))
            self.assertEqual(final["completed_units"], len(final["sections"]))
            self.assertEqual(first.stat().st_mtime_ns, stamp)
            self.assertEqual(len(calls), len(final["sections"]))
        self.data("/api/learning/read", "POST", {"chapter_id": cid,
                  "section_id": final["sections"][0]["id"], "checked": True})
        self.assertTrue(self.data(f"/api/chapters/{cid}")["chapter"]["learning_progress"])
        self.assertIn("八位补码".encode(), self.request(f"/api/chapters/{cid}/lecture")[1])

    def test_questions_detail_grading_mistakes_review_and_clear(self):
        import lessons
        _, chapter = self.new_chapter("练习复习测试")
        cid = chapter["id"]
        meta = lessons.plan(chapter)
        meta["sections"][0].update(content=full_section(), revision="fixture")
        lessons.publish(self.store, cid, meta)
        self.store.set_config("api_key", "fake-in-memory")
        self.addCleanup(lambda: self.store.set_config("api_key", ""))
        items = [{"stem": "八位补码能表示的最大整数是？", "options": ["127", "128", "255", "256"],
                  "answer": "A", "explanation": "最高位为符号位", "citation_ids": []}]
        def stream(client, messages, **kwargs):
            yield json.dumps(items, ensure_ascii=False)
            kwargs["on_finish"]("stop")
        with patch.object(self.server.deepseek.DeepSeekClient, "stream_chat", stream):
            qs = self.data(f"/api/chapters/{cid}/questions/generate", "POST",
                           {"n": 1, "section_id": meta["sections"][0]["id"]}, 201)["questions"]
        self.assertEqual(len(qs), 1)
        qid = qs[0]["id"]
        graded = self.data("/api/attempts", "POST", {"chapter_id": cid, "question_id": qid, "answer": "B"})
        self.assertFalse(graded["correct"])
        mistakes = self.data("/api/mistakes")["mistakes"]
        self.assertTrue(any(m["stem"] == items[0]["stem"] for m in mistakes))
        reviews = self.data("/api/review")["reviews"]
        review = next(r for r in reviews if r["ref_id"] == qid)
        next_review = self.data("/api/review/grade", "POST", {"id": review["id"], "quality": "easy"})["review"]
        self.assertGreater(next_review["stage"], review["stage"])
        def detail_stream(client, messages, **kwargs):
            yield "逐步解析：八位补码范围为 -128 到 127。"
            kwargs["on_finish"]("stop")
        with patch.object(self.server.deepseek.DeepSeekClient, "stream_chat", detail_stream):
            result = self.data(f"/api/chapters/{cid}/questions/{qid}/detail", "POST", {})
        self.assertIn("逐步解析", result["detail"])
        self.assertEqual(self.request("/api/records/clear", "POST", {"kinds": ["attempts"]})[0], 400)
        self.data("/api/records/clear", "POST", {"kinds": ["attempts"], "confirm": "确认清除"})
        self.assertTrue(self.store.questions(cid))
        self.data(f"/api/questions/{qid}", "DELETE")
        self.assertFalse(self.store.questions(cid))

    def test_chat_summary_profile_tips_variant_feynman_video_and_export(self):
        subject, chapter = self.new_chapter("聊天与档案")
        cid = chapter["id"]
        self.store.set_config("api_key", "fake-in-memory")
        self.addCleanup(lambda: self.store.set_config("api_key", ""))
        def stream(client, messages, **kwargs):
            yield "资料中没有找到足够依据。补充：补码用于整数编码。"
        with patch.object(self.server.deepseek.DeepSeekClient, "stream_chat", stream):
            _, raw, _ = self.request("/api/chat/stream", "POST", {"text": "补码是什么", "style": "detailed"})
        self.assertIn(b"event: retrieval", raw)
        self.assertIn(b"event: completed", raw)
        conv = self.store.list_conversations()[0]
        self.addCleanup(lambda: self.request(f"/api/conversations/{conv['id']}", "DELETE"))
        self.assertEqual(len(self.data(f"/api/conversations/{conv['id']}/messages")["messages"]), 2)
        self.data(f"/api/conversations/{conv['id']}/rename", "POST", {"title": "手机历史对话"})
        mistake = self.store.add_mistake(subject["name"], chapter["title"], "原始题", "B", "A", "简解")
        self.addCleanup(lambda: self.request(f"/api/mistakes/{mistake['id']}", "DELETE"))
        q = self.store.add_question(cid, "原始题", ["a", "b", "c", "d"], "A", "简解")
        self.data("/api/attempts", "POST", {"chapter_id": cid, "question_id": q["id"], "answer": "A"})
        with patch.object(self.server.deepseek.DeepSeekClient, "complete", return_value="模拟学习小结与复习建议"):
            self.data("/api/summaries/generate", "POST", {"conversation_id": conv["id"]}, 201)
            self.data(f"/api/chapters/{cid}/summary", "POST", {}, 201)
            self.data("/api/mistakes/tips", "POST", {}, 201)
            self.data("/api/profile/generate", "POST", {"month": "2026-11"}, 201)
            self.assertIn("模拟", self.data("/api/feynman", "POST",
                          {"chapter_id": cid, "text": "我的理解是补码使用模运算。"})["feedback"])
        variant = {"stem": "替换数字的变式题", "options": ["a", "b", "c", "d"],
                   "answer": "A", "explanation": "变式解析", "changed": "数字"}
        with patch.object(self.server.deepseek.DeepSeekClient, "complete", return_value=json.dumps(variant)):
            self.assertTrue(self.data(f"/api/mistakes/{mistake['id']}/variant", "POST", {})["saved"])
        videos = [{"title": "补码原理", "platform": "哔哩哔哩", "keyword": "补码 原理", "reason": "巩固概念"}]
        with patch.object(self.server.deepseek.DeepSeekClient, "complete", return_value=json.dumps(videos)):
            self.assertTrue(self.data(f"/api/chapters/{cid}/videos", "POST", {})["videos"])
        self.assertIn("模拟学习".encode(), self.request("/api/profile/2026-11/download")[1])
        status, raw, headers = self.request("/api/export/report")
        self.assertEqual(status, 200)
        self.assertIn("officedocument", headers["Content-Type"])
        with zipfile.ZipFile(io.BytesIO(raw)) as doc:
            self.assertIsNone(doc.testzip())
            self.assertIn("原始题", doc.read("word/document.xml").decode())

    def test_reference_directory_mapping_search_and_dashboard_graph(self):
        subject, chapter = self.new_chapter("参考教材测试")
        folder = self.store.folder_by_name(subject["name"])
        result, _ = self.upload("教材.md", "# 第一章 补码\n\n补码二进制整数表示\n# 第二章 溢出\n\n进位溢出",
                                folder_id=folder["id"], is_reference=True)
        mid = result["material"]["id"]
        self.addCleanup(lambda: self.request(f"/api/materials/{mid}", "DELETE"))
        self.assertTrue(self.store.material(mid)["is_reference"])
        self.data(f"/api/references/{mid}/toc", "POST", {"toc": [{"title": "补码", "page": 0}, {"title": "溢出", "page": 0}]})
        preview = self.data(f"/api/materials/{mid}/reference/chapters", "POST", {"subject_id": subject["id"]})
        self.assertEqual(len(preview["chapters"]), 2)
        self.data(f"/api/materials/{mid}/reference/chapters", "POST",
                  {"subject_id": subject["id"], "apply": True}, 201)
        self.assertTrue(self.data("/api/search?q=" + urllib.parse.quote("补码"))["hits"])
        dashboard = self.data("/api/dashboard")
        for key in ("mastery", "activity", "forecast", "recommend", "usage", "reviews"):
            self.assertIn(key, dashboard)
        graph = self.data("/api/graph")
        self.assertTrue(any(n["id"] == "ch:" + chapter["id"] for n in graph["nodes"]))
        self.assertTrue(any(n["id"] == "mat:" + mid for n in graph["nodes"]))
        self.assertEqual(self.request("/api/activity")[0], 200)
        self.assertEqual(self.request("/api/usage")[0], 200)

    def test_agent_can_manage_local_core_and_refresh_source_without_network(self):
        core = next(f for f in self.store.list_folders() if f["is_shared"])
        mat = self.store.add_material("智能管理测试", "旧内容", folder_id=core["id"],
                                      source_url="https://example.org/course")
        self.addCleanup(lambda: self.request(f"/api/materials/{mat['id']}", "DELETE"))
        target = self.data("/api/folders", "POST", {"name": "管理目标"}, 201)["folder"]
        self.addCleanup(lambda: self.request(f"/api/folders/{target['id']}", "DELETE"))
        self.store.set_config("api_key", "fake-in-memory")
        self.addCleanup(lambda: self.store.set_config("api_key", ""))
        with patch.object(self.server.tools, "fetch_url", return_value="更新后的补码课程"):
            self.assertTrue(self.data(f"/api/materials/{mat['id']}/refresh", "POST", {})["changed"])
        messages = [{"tool_calls": [{"id": "tool1", "type": "function", "function": {
                    "name": "move_material", "arguments": json.dumps({"title": mat["title"], "folder": target["name"]})}}]},
                    {"content": "已移动资料"}]
        with patch.object(self.server.deepseek.DeepSeekClient, "chat_with_tools", side_effect=messages):
            _, raw, _ = self.request("/api/agent/stream", "POST", {"scope": "materials", "text": "移动这份资料"})
        self.assertIn(b'"ok": true', raw)
        self.assertEqual(self.store.material(mat["id"])["folder_id"], target["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
