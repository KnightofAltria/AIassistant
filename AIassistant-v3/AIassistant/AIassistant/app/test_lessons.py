"""Incremental Markdown persistence and grounded practice, isolated temporary accounts."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import deepseek
import lessons
from store import Store
import test_references as reference_tests


class LessonTests(unittest.TestCase):
    setUp = reference_tests.ReferenceTests.setUp
    tearDown = reference_tests.ReferenceTests.tearDown
    call = reference_tests.ReferenceTests.call
    full_section = staticmethod(reference_tests.ReferenceTests.full_section)

    def plan(self):
        meta = lessons.plan(self.chapter)
        meta['sections'] = meta['sections'][:2]
        lessons.publish(self.store, self.chapter['id'], meta)
        return meta

    def tutor(self, body=None, response=None, reason='stop'):
        def stream(client, messages, **kwargs):
            yield response or self.full_section()
            kwargs['on_finish'](reason)
        with patch.object(deepseek.DeepSeekClient, 'stream_chat', stream) as mock:
            return self.call(f"/api/chapters/{self.chapter['id']}/tutor", body or {})

    def test_incremental_save_resume_and_reopen_markdown(self):
        meta = self.plan()
        folder = self.store.data_dir / 'lectures' / self.chapter['id']
        calls = []
        def stream(client, messages, **kwargs):
            calls.append(messages)
            if len(calls) == 2:
                self.assertTrue((folder / f"section-{meta['sections'][0]['id']}.md").exists())
                self.assertEqual(json.loads((folder/'manifest.json').read_text(encoding='utf-8'))['completed_units'], 1)
            yield self.full_section()
            kwargs['on_finish']('stop' if len(calls) == 1 else 'length')
        with patch.object(deepseek.DeepSeekClient, 'stream_chat', stream):
            _, raw = self.call(f"/api/chapters/{self.chapter['id']}/tutor", {})
        self.assertIn('event: saved', raw)
        self.assertIn('event: failed', raw)
        first = folder / f"section-{meta['sections'][0]['id']}.md"
        previous = first.stat().st_mtime_ns
        _, raw = self.tutor()
        self.assertIn('event: completed', raw)
        self.assertEqual(raw.count('event: progress'), 1)
        self.assertEqual(previous, first.stat().st_mtime_ns)
        self.assertEqual(len(list(folder.glob('section-*.md'))), 2)
        reopened = Store(self.store.db_path, data_dir=self.store.data_dir)
        try:
            first.write_text(first.read_text(encoding='utf-8').replace('以八位补码', '从文件读取的八位补码'), encoding='utf-8')
            self.assertIn('从文件读取', reopened.chapter(self.chapter['id'])['lecture'])
        finally:
            reopened.conn.close()

    def test_failed_regeneration_keeps_file_and_question_version(self):
        meta = self.plan(); self.tutor()
        section = lessons.plan(self.store.chapter(self.chapter['id']))['sections'][0]
        q = self.store.add_question(self.chapter['id'], '保留问题', ['a','b','c','d'], 'B', '简解')
        self.store.set_question_source(q['id'], dict(section_id=section['id'], revision=section['revision']))
        _, raw = self.tutor({'section_id':section['id']}, reason='length')
        self.assertIn('event: failed', raw)
        self.assertFalse(self.store.questions(self.chapter['id'])[0]['source']['stale'])
        self.tutor({'section_id':section['id']}, response=self.full_section()+'\n更新讲解')
        self.assertTrue(self.store.questions(self.chapter['id'])[0]['source']['stale'])
        self.assertEqual(len(self.store.questions(self.chapter['id'])), 1)
        self.assertTrue(list((self.store.data_dir/'lectures'/self.chapter['id']/'history').glob('*.md')))

    def test_outline_has_own_generation_and_archives_old_sections(self):
        self.plan(); self.tutor()
        old = lessons.plan(self.store.chapter(self.chapter['id']))['sections']
        self.tutor({'action':'outline'}, response=json.dumps([{'title':'新主题', 'query':'binary'}]))
        new = lessons.plan(self.store.chapter(self.chapter['id']))
        self.assertEqual(new['sections'][0]['title'], '新主题')
        self.assertEqual(new['completed_units'], 0)
        self.assertEqual(new['archived_sections'], old)
        self.assertIn('新主题', self.store.chapter(self.chapter['id'])['outline'])
        folder = self.store.data_dir/'lectures'/self.chapter['id']
        self.assertTrue((folder/f"section-{old[0]['id']}.md").exists())

    def test_grounded_practice_rejects_duplicates_and_false_sources(self):
        section = dict(id='abc', title='唯一小节', content='仅从已保存讲解出题', revision='v1',
                       citations=[dict(citation_id='c1', title='原教材', material_id='m', page=2)])
        base = dict(options=['a','b','c','d'], answer='B', explanation='简解')
        items = [dict(base, stem='现有题干', citation_ids=['c1']),
                 dict(base, stem='伪造资料的题目', citation_ids=['c9']),
                 dict(base, stem='针对该小节的新计算题', citation_ids=['c1'])]
        class Generator:
            def stream_chat(client, messages, **kw):
                payload = json.loads(messages[1]['content'])
                self.assertEqual(payload['lecture'], section['content'])
                self.assertIn('现有题干', payload['avoid_questions'])
                yield json.dumps(items)
                kw['on_finish']('stop')
        result = lessons.practice(Generator(), self.chapter, section, [{'stem':'现有题干'}], 3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['source']['citations'][0]['page'], 2)
        self.assertEqual(result[0]['source']['lecture'], section['content'])

    def test_detail_is_cached_and_uses_original_snapshot(self):
        self.plan(); self.tutor()
        q = self.store.add_question(self.chapter['id'], '计算题', ['a','b','c','d'], 'B', '简解')
        self.store.set_question_source(q['id'], dict(lecture='出题时快照', citations=[]))
        called = []
        def stream(client, messages, **kw):
            self.assertIn('出题时快照', messages[1]['content'])
            called.append(1)
            yield '逐步推导及干扰项解释'
            kw['on_finish']('stop')
        path = f"/api/chapters/{self.chapter['id']}/questions/{q['id']}/detail"
        with patch.object(deepseek.DeepSeekClient, 'stream_chat', stream):
            for _ in range(2):
                status, result = self.call(path, {})
                self.assertEqual(status, 200)
                self.assertIn('逐步推导', result['detail'])
        self.assertEqual(len(called), 1)

    def test_no_practice_without_saved_lesson(self):
        status, _ = self.call(f"/api/chapters/{self.chapter['id']}/questions/generate", {'n':3})
        self.assertEqual(status, 400)


if __name__ == '__main__':
    unittest.main()
