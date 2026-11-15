"""Versioned chapter plans, incremental lessons and grounded practice (standard library)."""
import json
import re
import uuid
from difflib import SequenceMatcher

import curriculum
import deepseek
import prompts
import rag
import references


def uid():
    return uuid.uuid4().hex


def plan(chapter):
    meta = json.loads(chapter.get('lecture_meta') or '{}')
    if 'sections' in meta:
        return meta
    sections = []
    # Preserve previously completed whole-chapter lessons during the upgrade.
    chunks = re.split(r'(?m)^## \d+\. ', chapter.get('lecture') or '')[1:]
    for unit in curriculum.units(chapter):
        content = next((c.split('\n', 1)[1].strip() for c in chunks
                        if c.split('\n', 1)[0].strip() == unit['title']), '')
        sections.append(dict(id=uid(), title=unit['title'], query=unit['query'],
                             content=content, revision=uid() if content else '',
                             citations=meta.get('citations', []) if content else []))
    return dict(meta, sections=sections, outline_revision=uid(),
                legacy_lecture=chapter.get('lecture') or '')


def publish(store, chapter_id, meta):
    sections = meta['sections']
    meta['completed_units'] = sum(bool(s.get('content')) for s in sections)
    meta['units'] = [s['title'] for s in sections]
    meta['citations'] = [c for s in sections for c in s.get('citations', [])]
    lecture = '\n\n'.join(f"## {i+1}. {s['title']}\n\n{s['content']}"
                          for i, s in enumerate(sections) if s.get('content'))
    lecture = lecture or meta.get('legacy_lecture', '')
    store.set_lecture(chapter_id, lecture, meta)


def full_response(generator, messages, limit=4096, temperature=0.3):
    finish = []
    text = ''.join(generator.stream_chat(messages, max_tokens=limit,
                                         temperature=temperature, on_finish=finish.append))
    if finish != ['stop'] or not text.strip():
        raise ValueError('模型输出中断或达到长度上限，未覆盖已保存内容，请重试此小节')
    return text


def json_value(text):
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    return json.loads(text)


def new_outline(generator, chapter, meta, evidence):
    if deepseek.MOCK:
        units = curriculum.units(chapter)
    else:
        raw = full_response(generator, [
            {'role': 'system', 'content': prompts.LESSON_OUTLINE_SYSTEM},
            {'role': 'user', 'content': json.dumps({'chapter': chapter['title'],
                'subject': chapter['subject_name'], 'coverage': [s['title'] for s in meta['sections']],
                'reference': evidence}, ensure_ascii=False)}], 4096)
        units = json_value(raw)
    if not isinstance(units, list) or not 1 <= len(units) <= 40:
        raise ValueError('大纲需要1到40个独立小节')
    result, seen = [], set()
    for u in units:
        title = str(u.get('title', '')).strip() if isinstance(u, dict) else ''
        if not title or len(title) > 160 or title in seen:
            raise ValueError('大纲有空标题、重复标题或过长标题，请重新生成')
        seen.add(title)
        # A new outline changes section boundaries: retain old lessons in the archive.
        result.append(dict(id=uid(), title=title, query=str(u.get('query') or title),
                           content='', revision='', citations=[]))
    return dict(meta, sections=result, outline_revision=uid(),
                archived_sections=meta.get('archived_sections', []) + meta['sections'])


def backfill_citations(store, chapter, meta):
    """给已保存但没有出处的小节补上参考来源（只补空，不改已有引用）。"""
    changed = False
    for index, section in enumerate(meta.get('sections', [])):
        if not section.get('content') or section.get('citations'):
            continue
        try:
            _, allowed = references.evidence(store, chapter,
                                             section.get('query') or section['title'], index)
        except Exception:
            allowed = []
        if allowed:
            section['citations'] = [dict(c, auto=True) for c in allowed[:2]]
            changed = True
    return changed


def question_source(question, meta):
    source = json.loads(question.get('source_meta') or '{}')
    section = next((s for s in meta['sections'] if s['id'] == source.get('section_id')), None)
    return dict(source, stale=bool(source) and
                (section is None or section.get('revision') != source.get('revision')))


def similar(stem, existing):
    return any(SequenceMatcher(None, re.sub(r'\W', '', stem), re.sub(r'\W', '', old)).ratio() > .82
               for old in existing)


def practice(generator, chapter, section, existing, count):
    """Retry rejected/near duplicate candidates; never invent source identifiers."""
    result, excluded = [], [q['stem'] for q in existing]
    allowed = section.get('citations', [])
    for attempt in range(3):
        if len(result) >= count:
            break
        if deepseek.MOCK and getattr(generator, 'model', '') != 'Qwen3-4B-Instruct-2507-local':
            candidates = [{'stem': f"[演示模式] {section['title']}：{angle}",
                           'options': ['A. 示例一', 'B. 示例二', 'C. 示例三', 'D. 示例四'],
                           'answer': 'B', 'explanation': '演示用占位解析，不代表正式题目。',
                           'citation_ids': [c['citation_id'] for c in allowed[:1]]}
                          for angle in ['计算过程中首先需要确认的条件是什么？', '实际应用出现异常时，应怎样定位错误原因？', '比较两种方案时哪一项体现其适用范围的区别？']]
        else:
            raw = full_response(generator, [
                {'role': 'system', 'content': prompts.GROUNDED_QUESTION_SYSTEM},
                {'role': 'user', 'content': json.dumps({'count': count-len(result),
                    'chapter': chapter['title'], 'section': section['title'],
                    'lecture': section['content'], 'sources': allowed,
                    'avoid_questions': excluded, 'variation_round': attempt}, ensure_ascii=False)}], 4096, 0.8)
            candidates = json_value(raw)
        if not isinstance(candidates, list):
            raise ValueError('出题结果格式错误')
        for item in candidates:
            if not isinstance(item, dict):
                continue
            stem = str(item.get('stem') or '').strip()
            options, answer = item.get('options'), item.get('answer')
            if not stem or not isinstance(options, list) or len(options) != 4 or answer not in list('ABCD'):
                continue
            if not all(isinstance(o, str) and o.strip() for o in options):
                continue
            if similar(stem, excluded):
                continue
            ids = item.get('citation_ids', [])
            known = {c['citation_id'] for c in allowed}
            if not isinstance(ids, list) or any(not isinstance(x, str) or x not in known for x in ids):
                continue
            if known and not ids:
                continue
            item['source'] = dict(section_id=section['id'], section_title=section['title'],
                                  revision=section['revision'], lecture=section['content'],
                                  citations=[c for c in allowed if c['citation_id'] in ids])
            result.append(item); excluded.append(stem)
            if len(result) >= count:
                break
    if not result:
        raise ValueError('候选题与已有题过于相似或来源不合规，请换一个小节再试')
    return result
