"""教材与长讲义回归。临时账号数据库、随机端口、模型桩；不调用真实模型。"""
from __future__ import annotations

import io
import base64
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import curriculum
import deepseek
import references
import seed
import server
from store import Store


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="csla-reference-test-")
        root = Path(self.tmp.name)
        self.store = Store(root / "user/csla.db", data_dir=root / "user")
        seed.seed(self.store)
        seed.ensure_folders(self.store)
        self.original = (server.STORE._store, server.AUTH, deepseek.MOCK)
        server.STORE.bind(self.store)
        server.AUTH = None
        deepseek.MOCK = False
        self.store.set_config("api_key", "isolated-test-key")
        self.httpd = server.QuietHTTPServer(("127.0.0.1", 0), server.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.folder = self.store.folder_by_slug("co")
        self.subject = next(s for s in self.store.subjects() if s["slug"] == "co")
        self.chapter = self.store.chapter(self.subject["chapters"][0]["id"])

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        server.STORE.bind(self.original[0])
        server.AUTH, deepseek.MOCK = self.original[1:]
        self.store.conn.close()
        self.tmp.cleanup()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode()
                return resp.status, json.loads(raw) if not path.endswith("/tutor") else raw
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def textbook(self, folder=None, status="approved"):
        mat = self.store.add_material("教材", "## 第一章 表示\n\nbinary integer\n## 第二章 运算\n\naddition",
                                      folder_id=(folder or self.folder)["id"], status=status)
        self.store.set_reference(mat["id"], True,
                                 [{"title": "表示", "page": 0}, {"title": "运算", "page": 0}])
        return self.store.material(mat["id"])

    def require_cached_books(self, *book_ids):
        books = [b for b in references.CATALOG if not book_ids or b["id"] in book_ids]
        missing = [b["id"] for b in books
                   if not (references.LIBRARY / b["filename"]).is_file()]
        if missing:
            self.skipTest("本地官方PDF未缓存；下载后可执行：" + ", ".join(missing))

    def test_curated_books_integrity_and_idempotent_seed(self):
        self.require_cached_books()
        total = len(references.CATALOG)
        self.assertEqual(references.seed_books(self.store), total)
        self.assertEqual(references.seed_books(self.store), 0)
        mats = [m for m in self.store.list_materials() if m["is_reference"]]
        self.assertEqual(len(mats), total)
        self.assertTrue(all(self.store.material_original(m["id"]).read_bytes().startswith(b"%PDF")
                            for m in mats))
        self.store.delete_material(mats[0]["id"])
        self.assertEqual(references.seed_books(self.store), 0)
        self.assertEqual(len(self.store.list_materials()), total - 1)

    def test_folder_isolation_and_pending(self):
        self.textbook()
        pending = self.textbook(status="pending")
        other = self.store.add_folder("独立文件夹")
        self.assertEqual(len(self.store.reference_materials(self.folder["id"])), 1)
        self.assertEqual(self.store.reference_materials(other["id"]), [])
        code, _ = self.call(f"/api/materials/{pending['id']}/reference", {"enabled": True})
        self.assertEqual(code, 400)

    def test_manual_reimport_restores_reference_without_duplicates(self):
        self.require_cached_books("co-matloff")
        first = references.import_book(self.store, "co-matloff", self.folder["id"])
        self.store.set_reference(first["id"], False)
        again = references.import_book(self.store, "co-matloff", self.folder["id"])
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(again["is_reference"], 1)
        self.assertEqual(len(self.store.list_materials()), 1)

    def test_manual_upload_of_large_algorithm_textbook(self):
        self.require_cached_books("ds-erickson")
        book, raw, _ = references.get_book("ds-erickson")
        self.assertGreater(len(raw), 20 * 1024 * 1024)
        self.assertLessEqual(len(raw), server.IMPORT_MAX)
        code, result = self.call("/api/materials/import",
            {"filename": book["filename"], "content": base64.b64encode(raw).decode("ascii"),
             "folder_id": self.folder["id"], "is_reference": True})
        self.assertEqual(code, 201)
        self.assertEqual(result["pages"], 472)
        self.assertTrue(result["material"]["is_reference"])
        self.assertEqual(self.store.material_original(result["material"]["id"]).stat().st_size, len(raw))

    def test_preview_append_duplicate_and_preserve_outline(self):
        mat = self.textbook()
        path = f"/api/materials/{mat['id']}/reference/chapters"
        before = len(self.store.chapters("co"))
        code, result = self.call(path, {"subject_id": self.subject["id"]})
        self.assertEqual(code, 200)
        self.assertEqual(len(result["chapters"]), 2)
        self.assertEqual(len(self.store.chapters("co")), before)
        _, result = self.call(path, {"subject_id": self.subject["id"], "apply": True})
        self.assertEqual(len(result["created"]), 2)
        _, again = self.call(path, {"subject_id": self.subject["id"], "apply": True})
        self.assertEqual(again["created"], [])
        self.assertEqual(again["skipped"], 2)
        self.assertEqual(self.store.chapter(self.chapter["id"])["outline"], self.chapter["outline"])

    def test_wrong_subject_and_core_permissions(self):
        core = self.store.folder_by_slug("shared")
        mat = self.textbook(core)
        server.AUTH = SimpleNamespace(user={"role": "student"})
        for path, body in (
            (f"/api/materials/{mat['id']}/reference", {"enabled": False}),
            (f"/api/materials/{mat['id']}/reference/chapters", {"subject_id": self.subject["id"], "apply": True}),
            ("/api/references/download", {"book_id": "co-matloff", "folder_id": core["id"]}),
        ):
            self.assertEqual(self.call(path, body)[0], 403)
        server.AUTH = None
        self.assertEqual(self.call(f"/api/materials/{mat['id']}/reference/chapters",
                                  {"subject_id": self.subject["id"]})[0], 400)

    def test_directory_validation(self):
        for bad in ([{"title": ""}], [{"title": "a", "page": -1}], "a|x", [{}] * 513,
                    [{"title": "a", "page": 20}, {"title": "b", "page": 10}]):
            with self.assertRaises(ValueError):
                references.clean_toc(bad)
        self.assertEqual(references.detect_toc("# 第一章\n## 第二章")[0]["title"], "第一章")

    def test_new_textbook_chapter_stays_editable_after_reopen(self):
        chapter = self.store.add_chapter(self.subject["id"], "教材新增章节")
        self.store._migrate()
        self.assertEqual(self.store.chapter(chapter["id"])["is_builtin"], 0)
        self.assertEqual(self.store.chapter(self.chapter["id"])["is_builtin"], 1)
        self.store.delete_chapter(chapter["id"])

    def test_page_scoped_bilingual_retrieval_and_review(self):
        mat = self.store.add_material("自编教材", "## 第 1 页\nbinary complement example\n"
                                      "## 第 2 页\naddition binary\n## 第 3 页\nsecret unrelated",
                                      folder_id=self.folder["id"])
        self.store.set_reference(mat["id"], True,
                                  [{"title": "表示", "original_title": "binary", "page": 1},
                                   {"title": "其他", "page": 3}])
        self.store.link_chapter_reference(self.chapter["id"], mat["id"], "表示")
        evidence, cites = references.evidence(self.store, self.store.chapter(self.chapter["id"]), "补码", 2)
        self.assertIn("binary", evidence)
        self.assertNotIn("secret", evidence)
        self.assertTrue(all(c["page"] < 3 for c in cites))
        self.store.set_material_status(mat["id"], "pending")
        self.assertEqual(references.evidence(self.store, self.store.chapter(self.chapter["id"]), "binary", 0),
                         ("", []))

    @staticmethod
    def full_section():
        return "\n\n".join("### " + h + "\n" +
                           "以八位补码为例，先确定位宽与符号，再计算编码并验证表示范围。" * 10
                           for h in ["学习目标与前置知识", "概念与原理", "公式或实现步骤",
                                     "例题与逐步解析", "易错点与自测解析"])

    def generate(self, section=None, reason="stop"):
        def stream(_client, messages, temperature=0.3, max_tokens=0, on_finish=None):
            self.assertEqual(max_tokens, 4096)
            yield section if section is not None else self.full_section()
            on_finish(reason)
        with patch.object(deepseek.DeepSeekClient, "stream_chat", stream):
            return self.call(f"/api/chapters/{self.chapter['id']}/tutor", {})

    def test_complete_26_units_persists_separate_lecture(self):
        code, raw = self.generate()
        self.assertEqual(code, 200)
        self.assertIn("event: completed", raw)
        saved = self.store.chapter(self.chapter["id"])
        self.assertGreater(len(saved["lecture"]), 8400)
        self.assertEqual(saved["outline"], self.chapter["outline"])
        self.assertEqual(json.loads(saved["lecture_meta"])["completed_units"], 26)
        self.assertEqual(len(curriculum.units(self.chapter)), 26)

    def test_fine_chapters_preserve_repeated_titles_and_page_ranges(self):
        mat = self.store.add_material("分层教材", "## 第 1 页\nalpha binary\n"
                                      "## 第 2 页\nalpha addition\n"
                                      "## 第 3 页\nbeta memory\n"
                                      "## 第 4 页\nbeta paging",
                                      folder_id=self.folder["id"])
        toc = [{"title": "第一章", "page": 1, "level": 1},
               {"title": "引言", "original_title": "alpha", "page": 1, "level": 2},
               {"title": "运算", "page": 2, "level": 2},
               {"title": "第二章", "page": 3, "level": 1},
               {"title": "引言", "original_title": "beta", "page": 3, "level": 2},
               {"title": "分页", "page": 4, "level": 2}]
        self.store.set_reference(mat["id"], True, toc)
        path = f"/api/materials/{mat['id']}/reference/chapters"
        _, result = self.call(path, {"subject_id": self.subject["id"], "granularity": "section", "apply": True})
        self.assertEqual(len(result["created"]), 4)
        target = next(c for c in result["created"] if c["title"] == "第二章 / 引言")
        chapter = self.store.chapter(target["id"])
        evidence, cites = references.evidence(self.store, chapter, "alpha beta", 0)
        self.assertIn("beta", evidence)
        self.assertNotIn("alpha", evidence)
        self.assertEqual({c["page"] for c in cites}, {3})
        coarse = references.chapter_plan(self.store, mat["id"], self.subject["id"])
        self.assertIn("引言 | alpha", coarse[0]["outline"])
        self.assertEqual(len(curriculum.units(coarse[0])), 2)
        self.assertEqual(self.call(path, {"subject_id": self.subject["id"], "granularity": "invalid"})[0], 400)

    def test_chinese_guides_persist_sources_and_respect_deletion(self):
        self.assertEqual(references.seed_guides(self.store), 4)
        self.assertEqual(references.seed_guides(self.store), 0)
        mat = self.store.reference_materials(self.folder["id"])[0]
        text = self.store.get_material_text(mat["id"])
        self.assertIn("0xC1540000", text)
        self.assertIn("不是出版社教材", text)
        self.assertTrue(self.store.material_original(mat["id"]).name.endswith(".md"))
        self.store.delete_material(mat["id"])
        self.assertEqual(references.seed_guides(self.store), 0)

    def test_supplementary_references_beyond_first_four_are_retrieved(self):
        for n in range(5):
            mat = self.store.add_material(f"教材{n}", "unrelated" if n < 4 else "banker safe need allocation",
                                          folder_id=self.folder["id"])
            self.store.set_reference(mat["id"], True, [])
        evidence, cites = references.evidence(self.store, self.chapter, "banker allocation", 20)
        self.assertIn("教材4", evidence)
        self.assertEqual(len(cites), 1)
        self.assertEqual(cites[0]["citation_id"], "c401")
        self.assertNotIn("PDF第0页", evidence)

    def test_context_budget_never_exposes_unprovided_citations(self):
        for n in range(6):
            mat = self.store.add_material(f"书{n}", "## 第 1 页\n" + ("cache memory " * 1400),
                                          folder_id=self.folder["id"])
            self.store.set_reference(mat["id"], True, [])
        evidence, cites = references.evidence(self.store, self.chapter, "cache memory", 0)
        self.assertLessEqual(len(evidence), 14000)
        self.assertLessEqual(len(cites), 18)
        self.assertTrue(all("[" + c["citation_id"] + "]" in evidence for c in cites))

    def test_markdown_repeated_heading_is_scoped_to_its_parent(self):
        mat = self.store.add_material("中文", "## 第一\n### 原理\nalpha old\n"
                                      "## 第二\n### 原理\nbeta correct\n### 自测\nhidden",
                                      folder_id=self.folder["id"])
        self.store.set_reference(mat["id"], True,
            [{"title": "第一", "level": 1}, {"title": "原理", "level": 2},
             {"title": "第二", "level": 1}, {"title": "原理", "level": 2},
             {"title": "自测", "level": 2}])
        self.store.link_chapter_reference(self.chapter["id"], mat["id"], "第二 / 原理")
        evidence, cites = references.evidence(self.store, self.store.chapter(self.chapter["id"]), "alpha beta hidden", 0)
        self.assertIn("beta correct", evidence)
        self.assertNotIn("alpha", evidence)
        self.assertNotIn("hidden", evidence)
        self.assertTrue(all(c["page"] == 0 for c in cites))

    def test_short_truncated_and_invalid_citation_do_not_overwrite(self):
        self.store.set_lecture(self.chapter["id"], "原有完整讲义", {"completed_units": 12})
        for section, reason in (("短回复", "stop"), (self.full_section(), "length"),
                                (self.full_section() + "[c99999]", "stop")):
            _, raw = self.generate(section, reason)
            self.assertIn("event: failed", raw)
            self.assertNotIn("event: completed", raw)
            self.assertEqual(self.store.chapter(self.chapter["id"])["lecture"], "原有完整讲义")
            self.assertFalse(server.TUTOR_JOBS)

    def test_account_switch_during_generation_never_saves(self):
        other_dir = Path(self.tmp.name) / "other"
        other = Store(other_dir / "csla.db", data_dir=other_dir)
        def stream(_client, messages, temperature=0.3, max_tokens=0, on_finish=None):
            yield self.full_section()
            server.STORE.bind(other)
            on_finish("stop")
        with patch.object(deepseek.DeepSeekClient, "stream_chat", stream):
            _, raw = self.call(f"/api/chapters/{self.chapter['id']}/tutor", {})
        self.assertIn("event: failed", raw)
        self.assertEqual(self.store.chapter(self.chapter["id"])["lecture"], "")
        self.assertEqual(other.subjects(), [])
        server.STORE.bind(self.store)
        other.conn.close()

    def test_stream_finish_reason_is_reported(self):
        class Response(io.BytesIO):
            pass
        finish = []
        raw = b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n'
        self.assertEqual(list(deepseek._iter_sse(Response(raw), finish.append)), ["hello"])
        self.assertEqual(finish, ["length"])

    def test_mock_uses_each_units_actual_citation_ids(self):
        references.seed_books(self.store)
        deepseek.MOCK = True
        _, raw = self.call(f"/api/chapters/{self.chapter['id']}/tutor", {})
        self.assertIn("event: completed", raw)
        self.assertIn("[演示模式]", self.store.chapter(self.chapter["id"])["lecture"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
