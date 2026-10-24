#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资料采集脚本：从公开站点抓取学习资料并导入本地知识库。

    python crawl.py                 # 抓取全部（已抓过的会跳过）
    python crawl.py --list          # 只看清单
    python crawl.py --only 计算机网络
    python crawl.py --force         # 即使已存在也重新抓

说明：
  · 只抓白名单里的页面，不递归爬站，不带参数改动目标站点。
  · 每篇只保留前 --max-chars 个字符（默认 4000），并记录原始 URL 作为出处。
  · 内容版权归各站点所有，仅供个人学习使用；资料管理里可逐条删除。
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.error
import urllib.request

import rag
from store import Store

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CSLA-LocalStudy/1.0"

# (标题, URL, 科目, 出处/许可说明)
SOURCES: list[tuple[str, str, str, str]] = [
    # ---- 计算机网络 ----
    ("TCP 三次握手与四次挥手 · 图解",
     "https://www.xiaolincoding.com/network/3_tcp/tcp_interview.html",
     "计算机网络", "小林coding（个人博客），仅本地学习使用"),
    ("HTTP 面试题 · 报文与版本演进",
     "https://www.xiaolincoding.com/network/2_http/http_interview.html",
     "计算机网络", "小林coding（个人博客），仅本地学习使用"),
    ("从输入 URL 到页面显示发生了什么",
     "https://www.xiaolincoding.com/network/1_base/what_happen_url.html",
     "计算机网络", "小林coding（个人博客），仅本地学习使用"),
    ("IP 基础、子网掩码与 CIDR",
     "https://www.xiaolincoding.com/network/4_ip/ip_base.html",
     "计算机网络", "小林coding（个人博客），仅本地学习使用"),
    # ---- 操作系统 ----
    ("进程与线程基础",
     "https://www.xiaolincoding.com/os/4_process/process_base.html",
     "操作系统", "小林coding（个人博客），仅本地学习使用"),
    ("虚拟内存与页表",
     "https://www.xiaolincoding.com/os/3_memory/vmem.html",
     "操作系统", "小林coding（个人博客），仅本地学习使用"),
    ("设备管理与 I/O、中断",
     "https://www.xiaolincoding.com/os/7_device/device.html",
     "操作系统", "小林coding（个人博客），仅本地学习使用"),
    # ---- 计算机组成原理 ----
    ("存储结构：寄存器、Cache 与内存",
     "https://www.xiaolincoding.com/os/1_hardware/storage.html",
     "计算机组成原理", "小林coding（个人博客），仅本地学习使用"),
    ("位运算基础",
     "https://oi-wiki.org/math/bit/",
     "计算机组成原理", "OI Wiki（CC BY-SA 4.0）"),
    # ---- 数据结构 ----
    ("栈",
     "https://oi-wiki.org/ds/stack/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("队列",
     "https://oi-wiki.org/ds/queue/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("树与树的遍历",
     "https://oi-wiki.org/graph/tree-basic/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("最小生成树",
     "https://oi-wiki.org/graph/mst/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("排序算法简介",
     "https://oi-wiki.org/basic/sort-intro/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("哈希表",
     "https://oi-wiki.org/string/hash/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("最短路问题",
     "https://oi-wiki.org/graph/shortest-path/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("二叉树",
     "https://oi-wiki.org/ds/binary-tree/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
]

DROP_BLOCKS = re.compile(
    r"<(script|style|nav|header|footer|aside|form|noscript|svg)[^>]*>.*?</\1>",
    re.S | re.I)
TAG = re.compile(r"<[^>]+>")
SPACE = re.compile(r"[ \t\u00a0]+")


def html_to_text(raw: str) -> str:
    text = DROP_BLOCKS.sub(" ", raw)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6]|tr|section|article)>", "\n", text, flags=re.I)
    text = TAG.sub(" ", text)
    text = html.unescape(text)
    text = SPACE.sub(" ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln and len(ln) > 1]
    return "\n".join(lines)


def fetch(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    pos = max(cut.rfind("。"), cut.rfind("\n"))
    return cut[:pos + 1] if pos > limit * 0.6 else cut


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取公开学习资料并导入本地知识库")
    ap.add_argument("--only", default="", help="只抓某科目")
    ap.add_argument("--max-chars", type=int, default=6000)
    ap.add_argument("--force", action="store_true", help="已有同标题资料时重新抓取")
    ap.add_argument("--list", action="store_true", help="只打印清单")
    ap.add_argument("--crawl", action="store_true", help="允许联网抓取（默认需显式开启）")
    args = ap.parse_args()

    if args.list or not args.crawl:
        for title, url, subject, lic in SOURCES:
            print(f"[{subject}] {title}\n    {url}\n    {lic}")
        if not args.crawl:
            print("\n这是预览模式。加 --crawl 才会真的联网抓取：python crawl.py --crawl")
        return 0

    store = Store()
    existing = {m["title"] for m in store.list_materials()}
    ok = skip = fail = 0

    for title, url, subject, lic in SOURCES:
        if args.only and args.only != subject:
            continue
        if title in existing and not args.force:
            print(f"[跳过] {title}（已存在，--force 可重抓）")
            skip += 1
            continue
        try:
            raw = fetch(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            print(f"[失败] {title}：{exc}")
            fail += 1
            continue
        text = trim(html_to_text(raw), args.max_chars)
        if len(text) < 200:
            print(f"[失败] {title}：正文太短（{len(text)} 字），可能页面结构变化")
            fail += 1
            continue
        body = f"# {title}\n\n来源：{url}\n许可/说明：{lic}\n\n{text}\n"
        folder = store.folder_by_name(subject) or store.folder_by_slug("shared") or {}
        material = store.add_material(title=title, text=body, subject=subject,
                                     folder_id=folder.get("id", ""),
                                     source_url=url, ext=".md")
        chunks = rag.chunk_text(body)
        store.replace_chunks(material["id"], chunks)
        print(f"[OK] {title} · {len(text)} 字 · {len(chunks)} 片")
        ok += 1

    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
