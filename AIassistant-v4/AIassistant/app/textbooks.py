"""开放教材来源：Open Textbook Library 检索与本地导入（仅标准库）。

Open Textbook Library（open.umn.edu）收录 2000 多本高校开放教材，提供 JSON 目录和
PDF/在线版本链接。这里把教材 PDF 下载到本地，解析正文后作为主要参考文献。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import deepseek
import pdftext
import rag
import references

SOURCE_NAME = "Open Textbook Library"
SOURCE_HOME = "https://open.umn.edu/opentextbooks"
API = "https://open.umn.edu/opentextbooks/textbooks.json"
MAX_BYTES = 80 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (compatible; CSLA/1.0; educational use)"

# 来源由项目维护，不接受前端传来的任意下载地址。
OPENSTAX_BOOKS = [{
    "title": "Introduction to Computer Science",
    "url": "https://openstax.org/details/books/introduction-computer-science",
    "pdf_urls": ["https://assets.openstax.org/oscms-prodcms/media/documents/Introduction_To_Computer_Science_-_WEB.pdf"],
    "license": "CC BY-NC-SA 4.0", "language": "English",
    "description": "OpenStax 计算机科学导论开放教材。",
    "publishers": ["OpenStax, Rice University"], "contributors": [],
}]


def _search_open_library(query: str, limit: int) -> list[dict]:
    return search(english_query(query), limit)


def _search_openstax(query: str, limit: int) -> list[dict]:
    terms = _terms(english_query(query))
    return [dict(book) for book in OPENSTAX_BOOKS
            if terms and all(term in book["title"].lower() for term in terms)][:limit]


# 新来源在这里注册：搜索函数返回教材记录，下载仍通过对应来源的搜索结果校验。
TEXTBOOK_SOURCES = {
    "open": {"name": "Open Textbook Library", "search": _search_open_library},
    "openstax": {"name": "OpenStax（精选）", "search": _search_openstax},
}


def list_sources() -> list[dict]:
    return [{"id": key, "name": value["name"]} for key, value in TEXTBOOK_SOURCES.items()]


def search_source(source: str, query: str, max_results: int = 8) -> list[dict]:
    """仅调用项目注册的来源；不接受前端指定任意网站或下载地址。"""
    provider = TEXTBOOK_SOURCES.get(source)
    if provider is None:
        raise ValueError("未知教材来源")
    return provider["search"](query, max_results)

COMMON_QUERIES = {
    "操作系统": "operating system",
    "计算机网络": "computer networks",
    "计网": "computer networks",
    "数据结构": "data structures",
    "计算机组成原理": "computer organization",
    "计组": "computer organization",
    "数据库": "database",
    "数据库系统": "database systems",
    "数据库系统概论": "database",
    "编译原理": "compiler",
    "计算机导论": "computer science",
    "计算机基础": "computer science",
    "数字电路": "digital circuit",
    "单片机": "microcontroller",
    "算法": "algorithms",
    "算法设计与分析": "algorithms",
    "机器学习": "machine learning",
    "深度学习": "deep learning",
    "人工智能": "artificial intelligence",
    "软件工程": "software engineering",
    "网络安全": "network security",
    "信息安全": "information security",
    "分布式系统": "distributed systems",
    "计算机图形学": "computer graphics",
    "密码学": "cryptography",
    "离散数学": "discrete mathematics",
    "数字逻辑": "digital logic",
    "计算机视觉": "computer vision",
    "自然语言处理": "natural language processing",
}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def _get(url: str, timeout: float = 30.0) -> tuple[bytes, str]:
    try:
        return _get_once(url, timeout)
    except Exception:
        # 少数 Python 环境缺少 open.umn.edu 的中间证书；公开目录退回 HTTP 读取。
        if url.startswith("https://open.umn.edu/"):
            return _get_once("http://" + url[len("https://"):], timeout)
        raise


def _get_once(url: str, timeout: float) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_BYTES + 1)
        ctype = resp.headers.get("Content-Type", "")
    if len(data) > MAX_BYTES:
        raise ValueError(f"文件超过 {MAX_BYTES // 1024 // 1024} MB")
    return data, ctype


def english_query(name: str, generator=None) -> str:
    text = (name or "").strip()
    if not text:
        return ""
    if text in COMMON_QUERIES:
        return COMMON_QUERIES[text]
    if re.fullmatch(r"[A-Za-z0-9 ,.+\-/]+", text):
        return text
    if generator is not None and not deepseek.MOCK:
        try:
            reply = "".join(generator.stream_chat([
                {"role": "system", "content": "把课程科目名翻译成英文教材检索词，"
                 "只输出 JSON：{\"query\":\"...\"}，最多 5 个单词，不要解释。"},
                {"role": "user", "content": text},
            ], max_tokens=100, temperature=0))
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip())
            query = str(json.loads(raw).get("query") or "").strip()
            if query:
                return query
        except Exception:
            pass
    return text


STOPWORDS = {"introduction", "to", "and", "the", "of", "for", "with", "a", "an",
             "using", "from", "in", "on", "practice"}
# 这些词太泛，不能单独证明教材对题（例如“系统生物学”不能被当成“操作系统”）。
GENERIC = {"system", "network", "structure", "organization", "computer", "data",
           "design", "principles", "programming", "science", "engineering"}


def _stem(word: str) -> str:
    word = word.lower()
    return word[:-1] if len(word) > 4 and word.endswith("s") else word


def _terms(query: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z]+", (query or "").lower())
            if len(t) > 2 and t not in STOPWORDS]


def _relevant(book: dict, query: str) -> int:
    """标题必须命中“有区分度”的词；系统/网络/数据这类泛词不能单独过关。"""
    terms = _terms(query)
    if not terms:
        return 0
    required = [t for t in terms if t not in GENERIC] or terms
    title = (book.get("title") or "").lower()
    title = title.replace("systems", "system").replace("structures", "structure")
    if all(term in title for term in required):
        return len(required) * 2 + sum(1 for t in terms if t in title)
    return 0


def search(query: str, max_results: int = 8) -> list[dict]:
    """按关键词检索开放教材，只保留标题确实匹配且有 PDF 版本的条目。"""
    if not query:
        return []
    params = urllib.parse.urlencode({"q": query, "per_page": max(8, min(max_results * 3, 24))})
    data = json.loads(_get(f"{API}?{params}")[0].decode("utf-8", "replace"))
    out = []
    for book in data.get("data", []):
        pdfs = [f.get("url") for f in book.get("formats", [])
                if f.get("type") == "PDF" and f.get("url")]
        if not pdfs:
            continue
        if not _relevant(book, query):
            continue
        out.append({"title": book.get("title") or "", "url": book.get("url") or "",
                    "pdf_urls": pdfs[:2], "license": book.get("license") or "",
                    "description": book.get("description") or "",
                    "language": book.get("language") or "",
                    "publishers": [x.get("name") for x in book.get("publishers", [])
                                   if isinstance(x, dict) and x.get("name")],
                    "contributors": [x.get("name") for x in book.get("contributors", [])
                                     if isinstance(x, dict) and x.get("name")]})
    return out


def _candidates(html: str, base: str) -> list[str]:
    parser = _Links()
    try:
        parser.feed(html)
    except Exception:
        return []
    scored = []
    for href in parser.hrefs:
        url = urllib.parse.urljoin(base, href)
        low = url.lower()
        if low.endswith(".pdf") or "type=pdf" in low or "download" in low and "pdf" in low:
            score = 3 if low.endswith(".pdf") else 2
            if "print_pdf" in low:
                score = 1
            scored.append((score, url))
    seen, out = set(), []
    for _, url in sorted(scored, reverse=True):
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out[:6]


def resolve_pdf(url: str, depth: int = 0) -> bytes:
    """把一个教材链接解析成 PDF 字节：支持直链、archive.org、GitHub Release 和下载页。"""
    if not url:
        raise ValueError("没有下载地址")
    parsed = urllib.parse.urlparse(url)
    # archive.org 的 ia*.us.archive.org 镜像换成稳定下载域名
    if parsed.hostname and parsed.hostname.endswith("archive.org") and "/items/" in parsed.path:
        url = "https://archive.org/download/" + parsed.path.split("/items/", 1)[1]
    # GitHub releases 页面通过 API 找 PDF 资产
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/releases", url)
    if m:
        api = f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/releases/latest"
        data = json.loads(_get(api)[0].decode("utf-8", "replace"))
        pdfs = [a.get("browser_download_url") for a in data.get("assets", [])
                if str(a.get("name", "")).lower().endswith(".pdf")]
        if not pdfs:
            raise ValueError("GitHub Release 没有 PDF 资产")
        url = pdfs[0]
    raw, ctype = _get(url)
    if raw.startswith(b"%PDF") or "application/pdf" in ctype.lower():
        return raw
    if depth >= 2:
        raise ValueError("下载页没有找到 PDF")
    html = raw.decode("utf-8", "replace")
    for candidate in _candidates(html, url):
        try:
            return resolve_pdf(candidate, depth + 1)
        except Exception:
            continue
    raise ValueError("下载页没有找到可用的 PDF")


def fetch_book(book: dict) -> dict:
    """下载并解析一本已检索到的教材。"""
    last = None
    for pdf_url in book.get("pdf_urls", []):
        try:
            raw = resolve_pdf(pdf_url)
            text, info = pdftext.pdf_to_text(raw)
            if not text.strip():
                continue
            return dict(book, pdf_url=pdf_url, raw=raw, text=text,
                        pages=info.get("pages", 0))
        except Exception as exc:                 # noqa: BLE001
            last = exc
    raise ValueError(f"教材 PDF 下载失败：{last}" if last else "没有可用的 PDF 下载地址")


def prefetch(query: str, limit: int = 1) -> list[dict]:
    """检索并下载教材，返回正文已解析的教材。单本失败会尝试下一本。"""
    books, seen = [], set()
    for book in search(query):
        if len(books) >= limit:
            break
        if book["title"] in seen:
            continue
        seen.add(book["title"])
        try:
            books.append(fetch_book(book))
        except Exception:
            continue
        time.sleep(0.5)
    return books


def import_books(store, books: list[dict], subject: str, folder: dict) -> list[dict]:
    """把下载好的教材写成科目文件夹里的主要参考文献。调用方负责加锁。"""
    results = []
    existing = {m["title"] for m in store.list_materials(folder["id"])}
    for book in books:
        title = book["title"][:120]
        if title in existing:
            results.append({"title": title, "ok": True, "skipped": True,
                            "reason": "同名资料已存在"})
            continue
        try:
            material = store.add_material(
                title=title, text=book["text"], subject=subject,
                folder_id=folder["id"], source_url=book["url"],
                ext=".md", original=book["raw"], original_ext=".pdf")
            store.replace_chunks(material["id"], rag.chunk_text(book["text"]))
            toc = references.detect_toc(book["text"], book["raw"])
            bib = {"pages": book.get("pages", 0), "license": book.get("license", ""),
                   "description": (book.get("description") or "")[:600],
                   "language": book.get("language", ""),
                   "author": "、".join(book.get("contributors", [])[:3]),
                   "institution": " / ".join(book.get("publishers", [])[:2]),
                   "source": book.get("url", "")}
            store.set_reference(material["id"], True, toc, bib)
            results.append({"title": title, "ok": True, "pages": book.get("pages", 0),
                            "toc": len(toc), "url": book["url"],
                            "license": book.get("license", "")})
        except Exception as exc:             # noqa: BLE001
            results.append({"title": title, "ok": False, "reason": str(exc)[:160]})
        existing.add(title)
    return results
