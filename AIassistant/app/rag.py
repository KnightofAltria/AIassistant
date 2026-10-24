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
# 逐字停用集：由两个停用字组成的二元组直接丢弃（"不能""什么""怎么""如何"…）。
# 这是中文检索的关键一步：不加的话，长文档靠虚词堆分就能压过真正相关的短文档。
STOP_CHARS = set("的了和是在与及或就都而及其这个那们你他她它可有会不很也要把被从对为以于么什怎如样才吗呢吧啊呀嘛"
                 "我你您之此该等能-")


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：CJK 约 1 token/字，其余 4 字符/token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk + (len(text) - cjk) / 4) + 1


def tokenize(text: str) -> list[str]:
    """中文用二元组，英文/数字用词，保留代码里的符号词。

    二元组里"两个都是虚词字"的直接丢掉（不能、什么、怎么、如何…），
    否则长文档靠虚词堆积就能压过真正相关的片段。
    """
    tokens: list[str] = []
    for run in CJK.findall(text):
        # 单字也是有效检索词（栈、树、图、锁、页…），必须进索引，
        # 否则"栈和队列有什么区别"这种问法会完全匹配不到"栈"这一篇。
        for ch in run:
            if ch not in STOP_CHARS:
                tokens.append(ch)
        for i in range(len(run) - 1):
            bigram = run[i:i + 2]
            if bigram in STOP:
                continue
            if bigram[0] in STOP_CHARS and bigram[1] in STOP_CHARS:
                continue
            tokens.append(bigram)
    tokens.extend(w.lower() for w in WORD.findall(text))
    tokens.extend(NUM.findall(text))
    return tokens


def strip_meta(text: str) -> str:
    """剥掉文件头的标题/来源/许可等元信息，避免它们被当成"证据"检索出来。

    导入的资料统一以 "# 标题" 开头，紧跟 "来源：…""许可/说明：…"，这些行对回答没有
    信息量，却因为标题里常出现关键词而占据 top1，导致引用的片段是一片"文件头"。
    """
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        if (line.startswith("# ") or line.startswith("来源：") or line.startswith("来源:")
                or line.startswith("许可") or line.startswith(">")):
            i += 1
            continue
        break
    body = "\n".join(lines[i:]).strip()
    return body or text.strip()


def chunk_text(text: str, target: int = 480, overlap: int = 80) -> list[str]:
    """按段落切片，尽量不拆散段落；超长段落按句子再切。"""
    text = strip_meta(text)
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
        # 标题单独存一份，命中标题的词额外加分：标题是人工命名，信噪比最高
        self.titles: list[set[str]] = [set(tokenize(c.get("title", ""))) for c in chunks]
        self.df: dict[str, int] = {}
        for toks in self.docs:
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = (sum(len(d) for d in self.docs) / len(self.docs)) if self.docs else 0.0
        self.n = len(self.docs)

    TITLE_BOOST = 3.0

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
            title_hits = len(set(q_tokens) & self.titles[i])
            for t in q_tokens:
                f = tf.get(t)
                if not f:
                    continue
                denom = f + self.K1 * (1 - self.B + self.B * dl / (self.avgdl or 1))
                score += self._idf(t) * f * (self.K1 + 1) / denom
            if title_hits:
                # 标题命中的词，按 IDF 加权再补一次
                score += self.TITLE_BOOST * sum(self._idf(t) for t in (set(q_tokens) & self.titles[i]))
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


def validate_citations(answer: str, citations: list[dict],
                       insufficient: bool = False) -> dict:
    """校验模型回答里出现的编号是否都在允许集合内（服务端只认自己发出去的编号）。

    insufficient=True 时，模型按要求不应引用任何编号；即便正文里出现编号（例如它在说明
    "这些资料讲的是 TCP/UDP"，或写了区间 [c1]–[c6]），也不作为引用展示，
    避免把"列举资料"误判成"引用证据"。
    """
    allowed = {c["citation_id"] for c in citations}
    used = sorted(set(re.findall(r"\[(c\d+)\]", answer or "")))
    invalid = [u for u in used if u not in allowed]
    passed = not invalid
    if insufficient:
        return {
            "used": used, "invalid": invalid, "passed": passed,
            "verification": "passed" if passed else "failed",
            "note": "检索到的资料相关性不足，未采用任何引用",
            "items": [],
        }
    return {
        "used": used, "invalid": invalid, "passed": passed,
        "verification": "passed" if passed else "failed",
        "items": [c for c in citations if c["citation_id"] in used] or citations[:3],
    }


# 资料不足的判定。
# 只用 BM25 绝对分会误判：长文档靠虚词堆分也能过线。所以再加一道"词覆盖"闸门——
# 查询里的有效词有多少比例真的出现在候选片段里。两个阈值由离线校准得到：
# 相关问题的覆盖度在 0.62~1.00，无关问题在 0.25~0.57（分数也低）。
INSUFFICIENCY_FLOOR = 6.0        # 绝对分下限
WEAK_COVER = 0.60               # 覆盖度低于此值视为可疑
WEAK_FLOOR = 25.0               # 可疑时还需要多高的分才算数


def token_coverage(query: str, hit: "Hit") -> float:
    qt = set(tokenize(query))
    if not qt:
        return 0.0
    ht = set(tokenize(hit.text)) | set(tokenize(hit.title))
    return len(qt & ht) / len(qt)


def insufficient_evidence(hits: list["Hit"], query: str = "",
                          floor: float = INSUFFICIENCY_FLOOR) -> bool:
    """资料不足判定：分数过低、或分数不高且词覆盖太差，都判为不足，不硬答也不编引用。"""
    if not hits:
        return True
    top = hits[0]
    if top.score < floor:
        return True
    if query and token_coverage(query, top) < WEAK_COVER and top.score < WEAK_FLOOR:
        return True
    return False


def route_subject(retriever: "Retriever", query: str, k: int = 12) -> str:
    """按检索结果自动判断问题属于哪个科目，避免跨科目混检。"""
    hits = retriever.search(query, k=k)
    if not hits:
        return ""
    agg: dict[str, float] = {}
    for hit in hits:
        if hit.subject:
            agg[hit.subject] = agg.get(hit.subject, 0.0) + hit.score
    if not agg:
        return ""
    best = max(agg, key=agg.get)
    # 该科目至少要占明显优势才采信，否则交给全库检索
    return best if agg[best] >= sum(agg.values()) * 0.45 else ""


@dataclass
class RagContext:
    query: str
    subject: str = ""
    hits: list[Hit] = field(default_factory=list)
    evidence: str = ""
    citations: list[dict] = field(default_factory=list)
    insufficient: bool = False

    @property
    def top_score(self) -> float:
        return self.hits[0].score if self.hits else 0.0

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "subject": self.subject,
            "insufficient": self.insufficient,
            "top_score": round(self.top_score, 2),
            "hits": [h.as_dict() for h in self.hits],
            "citations": self.citations,
        }
