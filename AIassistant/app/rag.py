#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检索层：切片 + 中文 BM25 + 引用编号。

设计文档 04 章要求"带出处回答"，且"引用用服务端生成的片段编号，模型只能选择已给编号"。
DeepSeek 没有 embedding 接口，所以这里用词法检索（BM25 + 中文二元切分）实现，
不依赖任何第三方库，离线可跑。将来接上向量库只需替换 score 部分，接口不变。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

CJK = re.compile(r"[\u4e00-\u9fff]+")
WORD = re.compile(r"[a-zA-Z_][a-zA-Z0-9_+#.]*")
NUM = re.compile(r"\d+(?:\.\d+)?")

# 常见中文虚词，切二元时过滤掉纯虚词组合，减少噪声
STOP = set("的了和是在与及或就都而及其这个那个我们你们他们可以有会不很也要把被从对为以于")


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 约 1 token/字，其余 4 字符/token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk + (len(text) - cjk) / 4) + 1


def tokenize(text: str) -> list[str]:
    """中文用二元组，英文/数字用词，保留代码里的符号词。"""
    tokens: list[str] = []
    for run in CJK.findall(text):
        if len(run) == 1:
            tokens.append(run)
        for i in range(len(run) - 1):
            bigram = run[i:i + 2]
            if bigram not in STOP:
                tokens.append(bigram)
    tokens.extend(w.lower() for w in WORD.findall(text))
    tokens.extend(NUM.findall(text))
    return tokens


def chunk_text(text: str, target: int = 480, overlap: int = 80) -> list[str]:
    """按段落切片，尽量不拆散段落；超长段落按句子再切。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal buf, size
        if not buf:
            return
        chunks.append("\n\n".join(buf))
        if overlap > 0 and len(buf) > 1:
            tail, tail_size = [], 0
            for para in reversed(buf):
                tail.insert(0, para)
                tail_size += estimate_tokens(para)
                if tail_size >= overlap:
                    break
            buf, size = tail, tail_size
        else:
            buf, size = [], 0

    for para in paragraphs:
        psize = estimate_tokens(para)
        if psize > target * 2:                       # 超长段落按句号再切
            sentences = re.split(r"(?<=[。！？；;])", para)
            for sent in sentences:
                if not sent.strip():
                    continue
                if size + estimate_tokens(sent) > target:
                    flush()
                buf.append(sent.strip())
                size += estimate_tokens(sent)
            continue
        if size + psize > target:
            flush()
        buf.append(para)
        size += psize
    if buf:
        chunks.append("\n\n".join(buf))
    # 去掉因 overlap 造成的重复尾块
    dedup: list[str] = []
    for c in chunks:
        if not dedup or c.strip() != dedup[-1].strip():
            dedup.append(c)
    return dedup


@dataclass
class Hit:
    citation_id: str
    material_id: str
    title: str
    subject: str
    ord: int
    text: str
    score: float
    locator: str = ""

    def as_dict(self) -> dict:
        return {
            "citation_id": self.citation_id, "material_id": self.material_id,
            "title": self.title, "subject": self.subject, "ord": self.ord,
            "locator": self.locator or f"第 {self.ord + 1} 片",
            "score": round(self.score, 3),
            "snippet": self.text[:180].replace("\n", " "),
        }


class Retriever:
    """BM25 检索。索引在每次资料变动后重建（资料量在课程作业规模内，重建成本可接受）。"""

    K1 = 1.5
    B = 0.75

    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.docs: list[list[str]] = [tokenize(c["text"]) for c in chunks]
        self.df: dict[str, int] = {}
        for toks in self.docs:
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = (sum(len(d) for d in self.docs) / len(self.docs)) if self.docs else 0.0
        self.n = len(self.docs)

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n - df + 0.5) / (df + 0.5))

    def search(self, query: str, k: int = 12, subject: str | None = None) -> list[Hit]:
        if not self.docs:
            return []
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scored: list[tuple[float, int]] = []
        for i, toks in enumerate(self.docs):
            if subject and self.chunks[i].get("subject") not in ("", subject):
                continue
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            dl = len(toks)
            for t in q_tokens:
                f = tf.get(t)
                if not f:
                    continue
                denom = f + self.K1 * (1 - self.B + self.B * dl / (self.avgdl or 1))
                score += self._idf(t) * f * (self.K1 + 1) / denom
            if score > 0:
                scored.append((score, i))
        scored.sort(reverse=True)
        hits: list[Hit] = []
        for rank, (score, i) in enumerate(scored[:k], start=1):
            c = self.chunks[i]
            hits.append(Hit(
                citation_id=f"c{rank}", material_id=c["material_id"],
                title=c["title"], subject=c.get("subject", ""), ord=c["ord"],
                text=c["text"], score=score))
        return hits


def build_evidence(hits: list[Hit], budget_tokens: int = 3600) -> tuple[str, list[dict]]:
    """把命中片段拼成带编号的证据块；超预算截断。返回 (给模型看的文本, 引用清单)。"""
    used = 0
    blocks: list[str] = []
    citations: list[dict] = []
    for hit in hits:
        cost = estimate_tokens(hit.text) + 24
        if used + cost > budget_tokens:
            continue
        used += cost
        blocks.append(f"[{hit.citation_id}] 来源：{hit.title}（{hit.locator}）\n{hit.text}")
        citations.append(hit.as_dict())
    return "\n\n".join(blocks), citations


def validate_citations(answer: str, citations: list[dict]) -> dict:
    """校验模型回答里出现的编号是否都在允许集合内（服务端只认自己发出去的编号）。"""
    allowed = {c["citation_id"] for c in citations}
    used = set(re.findall(r"\[(c\d+)\]", answer or ""))
    invalid = sorted(used - allowed)
    return {
        "used": sorted(used),
        "invalid": invalid,
        "passed": not invalid,
        "verification": "passed" if not invalid else "failed",
        "items": [c for c in citations if c["citation_id"] in used] or citations[:3],
    }


def insufficient_evidence(hits: list[Hit], floor: float = 1.2) -> bool:
    """资料不足判定：最高分低于阈值即判为资料不足，不硬答也不编引用。"""
    return not hits or hits[0].score < floor


@dataclass
class RagContext:
    query: str
    hits: list[Hit] = field(default_factory=list)
    evidence: str = ""
    citations: list[dict] = field(default_factory=list)
    insufficient: bool = False

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "insufficient": self.insufficient,
            "hits": [h.as_dict() for h in self.hits],
            "citations": self.citations,
        }
