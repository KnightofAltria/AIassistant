"""开放教材源：检索词映射、相关性过滤与本地导入的离线回归。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import references
import textbooks
from store import Store


class TextbookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="csla-textbooks-test-")
        root = Path(self.tmp.name)
        self.store = Store(root / "csla.db", data_dir=root)
        self.folder = self.store.add_folder("测试科目", ord=50)
        self.store.add_subject("测试科目")

    def tearDown(self):
        self.store.conn.close()
        self.tmp.cleanup()

    def test_common_subject_maps_to_english(self):
        self.assertEqual(textbooks.english_query("操作系统"), "operating system")
        self.assertEqual(textbooks.english_query("Data Structures"), "Data Structures")

    def test_openstax_selected_catalog_and_unknown_source(self):
        books = textbooks.search_source("openstax", "计算机导论")
        self.assertEqual(len(books), 1)
        self.assertEqual(books[0]["license"], "CC BY-NC-SA 4.0")
        self.assertEqual(textbooks.search_source("openstax", "operating system"), [])
        with self.assertRaises(ValueError):
            textbooks.search_source("unknown", "computer science")

    def test_registered_provider_is_discoverable_and_receives_query(self):
        provider = {"name": "测试来源", "search": lambda query, limit: [{"title": query, "limit": limit}]}
        with patch.dict(textbooks.TEXTBOOK_SOURCES, {"example": provider}):
            self.assertIn({"id": "example", "name": "测试来源"}, textbooks.list_sources())
            self.assertEqual(textbooks.search_source("example", "算法", 3), [{"title": "算法", "limit": 3}])
            self.assertNotIn("search", textbooks.list_sources()[-1])

    def test_relevance_rejects_unrelated_titles(self):
        book = {"title": "Introduction to Systems Biology", "description": "cells"}
        self.assertEqual(textbooks._relevant(book, "operating system"), 0)
        self.assertGreaterEqual(textbooks._relevant(
            {"title": "Operating Systems and Middleware", "description": ""}, "operating system"), 2)

    def test_toc_falls_back_to_chapter_headings(self):
        text = ("## 第 1 页\nChapter 1\nintro\n"
                "## 第 5 页\nChapter 2\nbody\n"
                "## 第 9 页\nChapter 3\nmore")
        toc = references.detect_toc(text, b"")
        self.assertEqual([(x["title"], x["page"]) for x in toc],
                         [("Chapter 1", 1), ("Chapter 2", 5), ("Chapter 3", 9)])

    def test_import_book_as_reference(self):
        book = {"title": "A Test Textbook", "url": "https://open.umn.edu/test",
                "license": "CC BY", "raw": b"%PDF-1.4 test",
                "text": "## 第 1 页\n" + "process scheduling " * 80,
                "pages": 1, "pdf_url": "https://example.test/book.pdf"}
        result = textbooks.import_books(self.store, [book], "测试科目", self.folder)
        self.assertTrue(result[0]["ok"])
        mats = self.store.reference_materials(self.folder["id"])
        self.assertEqual(len(mats), 1)
        self.assertEqual(mats[0]["title"], "A Test Textbook")
        self.assertTrue(self.store.material_original(mats[0]["id"]).name.endswith(".pdf"))
        self.assertTrue(self.store.get_material_text(mats[0]["id"]).startswith("## 第 1 页"))


if __name__ == "__main__":
    unittest.main()
