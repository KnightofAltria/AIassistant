"""回答缓存回归：不导入服务、不读用户库、不调用模型。"""
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest


class AnswerCacheTests(unittest.TestCase):
    def setUp(self):
        self.revision = 1
        self.config = {"model": "model-a", "refuse_threshold": "1"}
        self.learner = "计算机专业"
        tree = ast.parse(Path(__file__).with_name("server.py").read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "cache_key")
        env = dict(hashlib=hashlib, json=json,
                   STORE=SimpleNamespace(rev=lambda: self.revision,
                                         get_config=lambda: self.config,
                                         meta_summary=lambda: self.learner),
                   prompts=SimpleNamespace(chat_system=lambda style: style),
                   deepseek=SimpleNamespace(MOCK=True))
        exec(compile(ast.Module(body=[function], type_ignores=[]), "cache_key", "exec"), env)
        self.key = env["cache_key"]

    def test_unchanged_request_can_reuse_cache(self):
        self.assertEqual(self.key("问题", "concise", []), self.key("问题", "concise", []))

    def test_material_revision_invalidates_answer(self):
        before = self.key("问题", "concise", [])
        self.revision += 1  # 删除、审核、切片修改均推进索引版本
        self.assertNotEqual(before, self.key("问题", "concise", []))

    def test_full_history_including_assistant_and_long_messages(self):
        a = [{"role": "user", "content": "x" * 80 + "A"},
             {"role": "assistant", "content": "结论A"}]
        b = [dict(m) for m in a]
        b[1]["content"] = "结论B"
        self.assertNotEqual(self.key("为什么", "concise", a), self.key("为什么", "concise", b))
        b = [dict(m) for m in a]
        b[0]["content"] = "x" * 80 + "B"
        self.assertNotEqual(self.key("为什么", "concise", a), self.key("为什么", "concise", b))

    def test_config_and_learner_changes(self):
        before = self.key("问题", "concise", [])
        self.config["model"] = "model-b"
        after = self.key("问题", "concise", [])
        self.assertNotEqual(before, after)
        self.learner = "初学者"
        self.assertNotEqual(after, self.key("问题", "concise", []))

    def test_code_whitespace_and_case_are_significant(self):
        self.assertNotEqual(self.key("a b", "concise", []), self.key("ab", "concise", []))
        self.assertNotEqual(self.key("A", "concise", []), self.key("a", "concise", []))


if __name__ == "__main__":
    unittest.main()
