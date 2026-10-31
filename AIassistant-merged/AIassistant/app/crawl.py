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
import subprocess
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
    ("CPU 是如何执行程序的",
     "https://www.xiaolincoding.com/os/1_hardware/how_cpu_run.html",
     "计算机组成原理", "小林coding（个人博客），仅本地学习使用"),
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
    ("TCP/IP 网络模型",
     "https://www.xiaolincoding.com/network/1_base/tcp_ip_model.html",
     "计算机网络", "小林coding（个人博客），仅本地学习使用"),
    ("HTTPS 与 TLS 优化",
     "https://www.xiaolincoding.com/network/2_http/https_optimize.html",
     "计算机网络", "小林coding（个人博客），仅本地学习使用"),
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
    ("深度优先搜索 DFS",
     "https://oi-wiki.org/graph/dfs/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("并查集",
     "https://oi-wiki.org/ds/dsu/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("前缀和与差分",
     "https://oi-wiki.org/basic/prefix-sum/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
    ("最短路问题",
     "https://oi-wiki.org/graph/shortest-path/",
     "数据结构", "OI Wiki（CC BY-SA 4.0）"),
]

VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "source", "col",
             "embed", "param", "track", "wbr", "area", "base"}
# 标签名或 class/id 命中这些词，整块跳过（导航、侧栏、页眉页脚、目录、评论…）
NAV_HINT = re.compile(
    r"(nav|menu|sidebar|side-bar|toc|catalog|breadcrumb|footer|header|aside|"
    r"comment|share|related|advert|banner|copyright|pagination|toolbar|drawer)",
    re.I)
# 这些标签整块丢弃
DROP_TAGS = {"script", "style", "noscript", "svg", "iframe", "template", "form"}
BLOCK_TAGS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "main", "blockquote", "pre", "table", "br", "hr"}
TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)((?:\"[^\"]*\"|'[^']*'|[^>\"'])*)>", re.S)
TEX_SYMBOLS = {
    "\\geq": "≥", "\\leq": "≤", "\\neq": "≠", "\\approx": "≈", "\\equiv": "≡",
    "\\times": "×", "\\cdot": "·", "\\div": "÷", "\\pm": "±",
    "\\rightarrow": "→", "\\to": "→", "\\Rightarrow": "⇒", "\\leftarrow": "←",
    "\\infty": "∞", "\\sum": "Σ", "\\prod": "Π", "\\sqrt": "√", "\\in": "∈",
    "\\subseteq": "⊆", "\\cup": "∪", "\\cap": "∩", "\\forall": "∀", "\\exists": "∃",
    "\\alpha": "α", "\\beta": "β", "\\gamma": "γ", "\\delta": "δ", "\\theta": "θ",
    "\\lambda": "λ", "\\mu": "μ", "\\pi": "π", "\\sigma": "σ", "\\omega": "ω",
    "\\log": "log", "\\ln": "ln", "\\exp": "exp", "\\max": "max", "\\min": "min",
    "\\bmod": "mod", "\\pmod": "mod",
}
BOILER_LINES = {"跳转至", "OI Wiki", "编辑", "本页面最近更新", "贡献者", "回到顶部",
                "上一篇", "下一篇", "阅读更多", "目录", "分享", "评论"}


def _pick_main(html: str) -> str:
    """尽量只留正文容器；找不到就返回原文档。"""
    m = re.search(r"<article[^>]*>", html, re.I)
    if m:
        end = html.lower().rfind("</article>")
        return html[m.start():end + 10] if end > m.start() else html[m.start():]
    m = re.search(r"<main[^>]*>", html, re.I)
    if m:
        end = html.lower().rfind("</main>")
        return html[m.start():end + 7] if end > m.start() else html[m.start():]
    m = re.search(r'<div[^>]+class="[^"]*(md-content|markdown-body|post-content|'
                  r'article-content|entry-content|content-article)[^"]*"[^>]*>', html, re.I)
    if m:
        return html[m.start():]
    return html


def _flatten_mjx(doc: str) -> str:
    """MathJax 3 的渲染结果里，每个公式都带一份 data-latex（原始 TeX）。
    整块换成这份 TeX，既不会出现"𝑛n"重影，也不会丢公式。"""
    def repl(m):
        block = m.group(0)
        mm = re.search(r'data-latex="([^"]*)"', block) or re.search(r"data-latex=([^\s>]+)", block)
        if not mm:
            return " "
        tex = mm.group(1).strip()
        tex = tex.replace("\\displaystyle", "").replace("\\,", " ").replace("\\!", "")
        tex = re.sub(r"\\text\{([^{}]*)\}", r"\1", tex)
        return " " + tex + " "

    return re.sub(r"<mjx-container\b.*?</mjx-container>", repl, doc, flags=re.S | re.I)


def _flatten_math(doc: str) -> str:
    """MathJax/KaTeX 会把公式渲染两遍（字形 + TeX 注解），只保留注解，避免出现
    "𝑛n""𝑑𝑖𝑠(𝑢)dis(u)" 这种重影式的乱码。"""
    def repl(m):
        block = m.group(0)
        ann = re.search(r"<annotation[^>]*>(.*?)</annotation>", block, re.S)
        if ann:
            return " " + ann.group(1).strip() + " "
        return " "

    doc = re.sub(r"<math\b.*?</math>", repl, doc, flags=re.S | re.I)
    # KaTeX 的视觉层（katex-html）是重复内容，整块去掉
    doc = re.sub(r'<span[^>]+class="[^"]*katex-html[^"]*"[^>]*>.*?</span>', " ", doc, flags=re.S | re.I)
    return doc


def html_to_text(raw: str) -> str:
    """HTML 转纯文本：只取正文，按标签层级丢弃导航/侧栏/页脚等整块内容。"""
    doc = re.sub(r"<!--.*?-->", " ", raw, flags=re.S)
    doc = _pick_main(doc)
    doc = _flatten_mjx(doc)
    doc = _flatten_math(doc)

    parts: list[str] = []
    stack: list[tuple[str, bool, bool]] = []   # (tag, navish, droppable)
    pos = 0
    for m in TAG_RE.finditer(doc):
        piece = doc[pos:m.start()]
        skipping = any(nav or drop for _, nav, drop in stack)
        if piece and not skipping:
            parts.append(piece)
        pos = m.end()

        closing, tag, attrs = m.group(1) == "/", m.group(2).lower(), (m.group(3) or "")
        if tag in VOID_TAGS:
            if tag in ("br", "hr"):
                parts.append("\n")
            continue
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == tag:
                    was_block = tag in BLOCK_TAGS
                    del stack[i:]
                    if was_block and not any(nav or drop for _, nav, drop in stack):
                        parts.append("\n")
                    break
            continue

        navish = bool(NAV_HINT.search(tag) or NAV_HINT.search(attrs))
        droppable = (tag in DROP_TAGS
                     or bool(re.search(r"katex|mjx-|sr-only|visually-hidden|screen-reader",
                                       attrs, re.I)))
        stack.append((tag, navish, droppable))
        if tag in BLOCK_TAGS:
            parts.append("\n")

    tail = doc[pos:]
    if tail and not any(nav or drop for _, nav, drop in stack):
        parts.append(tail)

    text = html.unescape("".join(parts))
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = text.replace("\\displaystyle", "").replace("\\,", " ").replace("\\!", "")
    for k, v in TEX_SYMBOLS.items():
        text = text.replace(k, v)
    text = re.sub(r"\\text\{([^{}]*)\}", r"\1", text)
    lines = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln or len(ln) < 2:
            continue
        if ln in BOILER_LINES:
            continue
        lines.append(ln)
    return "\n".join(lines)


def _decode(raw: bytes) -> str:
    """按常见中文编码依次尝试。"""
    for enc in ("utf-8", "gb18030", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _fetch_urllib(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _decode(resp.read())


def _fetch_curl(url: str, timeout: float) -> str:
    """兜底：有些站点会掐掉 Python 的 TLS 握手，改用系统 curl。"""
    proc = subprocess.run(
        ["curl", "-sS", "-L", "--max-time", str(int(timeout)),
         "-A", UA, url],
        capture_output=True, timeout=timeout + 10)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError((proc.stderr or b"").decode("utf-8", "replace")[:200]
                           or f"curl 退出码 {proc.returncode}")
    return _decode(proc.stdout)


def fetch(url: str, timeout: float = 30.0) -> str:
    try:
        return _fetch_urllib(url, timeout)
    except Exception:                                    # noqa: BLE001
        return _fetch_curl(url, timeout)


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
        if title in existing and args.force:
            # 重抓时先删掉旧条目，否则会留下两份同名资料
            for old_m in store.list_materials():
                if old_m["title"] == title:
                    store.delete_material(old_m["id"])
            existing.discard(title)
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
