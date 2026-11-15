#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线检索评测：只用本地资料与本地 BM25，不调用任何模型、不写库。

用途：给"AI 优化"提供一个可以复现的数字，而不是凭感觉说"更准了"。

    python eval_retrieval.py            # 默认跑三种配置对比
    python eval_retrieval.py --k 8

指标：
    Recall@k  正确资料（出题的那一份）是否出现在前 k 条里
    MRR       正确资料出现位置的倒数的平均值，越接近 1 越好

两类查询：
    标题型   直接用资料标题当查询（模拟"我知道名字，想找它"）
    片段型   取某一片段的前 30 字当查询（模拟"我记得这句话，想找原文"）
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from store import Store
import rag

CONFIGS = [
    ("BM25 基线", dict(expand=False, diversify=False)),
    ("+同义词扩展", dict(expand=True, diversify=False)),
    ("+同义词+去重", dict(expand=True, diversify=True)),
]

# 第二组：学生用"中文全称 / 别称"提问，而资料里写的是缩写或另一种叫法。
# 这一组专门用来量化同义词扩展的价值——基线在这类查询上直接召不回。
ABBREV_QUERIES = [
    ("传输控制协议", "tcp"),
    ("中央处理器", "cpu"),
    ("只读存储器", "rom"),
    ("快表", "tlb"),
    ("进程控制块", "pcb"),
    ("用户数据报协议", "udp"),
    ("散列表", "哈希"),
    ("最短路径算法", "最短路径"),
]


def build_queries(chunks: list[dict], limit: int = 60) -> list[dict]:
    """按资料生成两类查询，并记下标准答案（material_id）。"""
    by_material: dict[str, list[dict]] = {}
    for c in chunks:
        by_material.setdefault(c["material_id"], []).append(c)
    rng = random.Random(20261031)
    queries: list[dict] = []
    for mid, items in by_material.items():
        title = items[0]["title"]
        queries.append({"q": title, "gold": mid, "kind": "标题型"})
        text = items[0]["text"].replace("\n", " ").strip()
        if len(text) >= 30:
            start = rng.randint(0, max(0, len(text) - 30))
            queries.append({"q": text[start:start + 30], "gold": mid, "kind": "片段型"})
    return queries[: limit * 2]


def evaluate(chunks: list[dict], queries: list[dict], k: int, **flags) -> dict:
    retriever = rag.Retriever(chunks)
    hit = 0
    rr = 0.0
    per_kind = {"标题型": [0, 0], "片段型": [0, 0]}
    for item in queries:
        hits = retriever.search(item["q"], k=k, **flags)
        rank = next((i for i, h in enumerate(hits, start=1)
                     if h.material_id == item["gold"]), 0)
        if rank:
            hit += 1
            rr += 1.0 / rank
        per_kind[item["kind"]][1] += 1
        if rank:
            per_kind[item["kind"]][0] += 1
    total = len(queries) or 1
    return {
        "recall": hit / total, "mrr": rr / total, "n": len(queries),
        "by_kind": {k2: (v[0] / v[1] if v[1] else 0.0) for k2, v in per_kind.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="离线检索评测")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()

    store = Store()
    chunks = store.all_chunks()
    if not chunks:
        print("库里没有已审核的资料，无法评测。")
        return 2
    queries = build_queries(chunks, args.limit)
    print(f"资料 {len({c['material_id'] for c in chunks})} 份 / 切片 {len(chunks)} 段 / "
          f"查询 {len(queries)} 条 / k={args.k}\n")
    header = f"{'配置':<14}{'Recall@'+str(args.k):>12}{'MRR':>10}{'标题型':>10}{'片段型':>10}"
    print(header)
    print("-" * len(header.encode("gbk", errors="replace")))
    results = []
    for name, flags in CONFIGS:
        r = evaluate(chunks, queries, args.k, **flags)
        results.append((name, r))
        print(f"{name:<14}{r['recall'] * 100:>11.1f}%{r['mrr']:>10.3f}"
              f"{r['by_kind']['标题型'] * 100:>9.1f}%{r['by_kind']['片段型'] * 100:>9.1f}%")
    best = max(results, key=lambda x: (x[1]["recall"], x[1]["mrr"]))
    base = results[0][1]
    print(f"\n最佳：{best[0]}，Recall 提升 {(best[1]['recall'] - base['recall']) * 100:+.1f} 个百分点")

    # ---- 第二组：术语写法不一致的查询
    # 标准答案不按标题猜，而是"正文里真的出现该缩写的资料"，避免把不存在的目标算成未命中。
    print("\n术语不一致的查询（学生说中文全称，资料里写缩写）")

    def gold_material(keyword: str) -> str:
        for chunk in chunks:
            if keyword in (chunk["text"] or "").lower():
                return chunk["material_id"]
        return ""

    retriever = rag.Retriever(chunks)
    rows = []
    for query, keyword in ABBREV_QUERIES:
        gold = gold_material(keyword)
        if not gold:
            continue

        def rank_of(expand: bool) -> int:
            for pos, hit in enumerate(retriever.search(query, k=5, expand=expand,
                                                       diversify=False), start=1):
                if hit.material_id == gold:
                    return pos
            return 0

        rows.append((query, keyword, rank_of(False), rank_of(True)))
    print(f"{'查询':<12}{'资料里的写法':<14}{'基线排名':>10}{'+扩展排名':>10}")
    for query, keyword, base_rank, exp_rank in rows:
        print(f"{query:<12}{keyword:<14}{base_rank or '未命中':>10}{exp_rank or '未命中':>10}")
    base_ok = sum(1 for _, _, b, _ in rows if b)
    exp_ok = sum(1 for _, _, _, e in rows if e)
    print(f"\n命中率：基线 {base_ok}/{len(rows)}，加同义词 {exp_ok}/{len(rows)}")
    if base_ok == exp_ok:
        print("结论：这一组没有差异——同义词扩展不是万灵药，"
              "只有问法与资料写法完全对不上时才有用；中文二元切分已经兜住了大部分情况。")

    # ---- 第三组：多轮指代（"它 / 这个"单独检索是噪声，补上上文才有意义）
    print("\n多轮指代的检索差异")
    prev_q = "TCP 为什么需要三次握手"
    follow_q = "它和四次挥手有什么区别"
    alone = retriever.search(follow_q, k=3, diversify=True)
    merged = retriever.search(f"{prev_q} {follow_q}", k=3, diversify=True)
    print(f"  追问「{follow_q}」单独检索 → 首位：{alone[0].title if alone else '无'}")
    print(f"  补上上文后检索 → 首位：{merged[0].title if merged else '无'}")

    # ---- 第四组：来源多样性（同一份资料占满 8 条，模型看到的信息其实很窄）
    sample = "进程 线程 调度 死锁 内存 页表 缓存 中断"
    plain = retriever.search(sample, k=8, diversify=False)
    diverse = retriever.search(sample, k=8, diversify=True)
    print("\n来源多样性（top-8 涉及几份资料）")
    print(f"  不去重：{len({h.material_id for h in plain})} 份")
    print(f"  去重后：{len({h.material_id for h in diverse})} 份")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
