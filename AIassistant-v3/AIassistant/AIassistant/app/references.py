"""主要参考文献：官方开放教材、本地目录和有页码的原文检索（仅标准库）。"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pdftext
import rag

APP = Path(__file__).resolve().parent
LIBRARY = APP / "reference_library"
CATALOG = json.loads((APP / "reference_catalog.json").read_text(encoding="utf-8"))
CACHE_LOCK = threading.Lock()
MAX_BYTES = 32 * 1024 * 1024


def catalog() -> list[dict]:
    return [dict(b, cached=(LIBRARY / b["filename"]).is_file()) for b in CATALOG]


def clean_toc(value) -> list[dict]:
    """JSON目录或「标题 | PDF页码 | 层级」，页码以阅读器页码为准。"""
    if isinstance(value, str):
        lines = [s.split("|") for s in value.splitlines() if s.strip()]
        value = [{"title": s[0].strip(), "page": s[1].strip() if len(s) > 1 else 0,
                  "level": s[2].strip() if len(s) > 2 else 1} for s in lines]
    if not isinstance(value, list) or len(value) > 512:
        raise ValueError("目录需为列表，最多512个章节/小节")
    out = []
    last_page = 0
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("目录条目格式不正确")
        title = str(item.get("title") or "").strip()
        try:
            page = int(item.get("page") or 0)
            level = int(item.get("level") or 1)
        except (ValueError, TypeError):
            raise ValueError("目录页码和层级需为整数")
        if not title or len(title) > 180 or not 0 <= page <= 10000 or not 1 <= level <= 6:
            raise ValueError("目录标题或页码不合法")
        if page and page < last_page:
            raise ValueError("目录页码应按阅读顺序递增")
        last_page = page or last_page
        out.append({"title": title, "original_title": str(item.get("original_title") or "")[:180],
                    "page": page, "level": level})
    return out


def stored_toc(material: dict) -> list[dict]:
    return clean_toc(json.loads(material.get("reference_toc") or "[]"))


def section_paths(toc: list[dict]) -> list[str]:
    stack, paths = [], []
    for section in toc:
        while stack and stack[-1]["level"] >= section["level"]:
            stack.pop()
        stack.append(section)
        paths.append(" / ".join(s["title"] for s in stack))
    return paths


def _plausible_toc(items: list[dict]) -> bool:
    """PDF 书签可能是页码占位符；没有文字或没有页码时改用正文标题。"""
    if len(items) < 3:
        return False
    readable = [t for t in items if re.search(r"[A-Za-z\u4e00-\u9fff]", t["title"])]
    paged = [t for t in items if t["page"]]
    return len(readable) >= len(items) * 0.7 and len(paged) >= max(2, len(items) * 0.5)


def detect_toc(text: str, raw: bytes = b"") -> list[dict]:
    """优先PDF书签，缺少书签时使用文本标题；扫描件需用户手工填目录。"""
    out = []
    if raw.startswith(b"%PDF"):
        try:
            doc = pdftext.PdfDoc(raw)
            root = next((o for o in doc.objects.values()
                         if isinstance(o, dict) and o.get("Type") == "Catalog"), {})
            pages = [p[0] for p in doc.pages()]
            node = doc.dict_of(root.get("Outlines"))
            seen = set()

            def walk(ref, level=1):
                while ref and len(out) < 512 and level <= 6 and repr(ref) not in seen:
                    seen.add(repr(ref))
                    entry = doc.dict_of(ref)
                    title = entry.get("Title")
                    if isinstance(title, bytes):
                        title = title.decode("utf-16" if title.startswith(b"\xfe\xff") else "utf-8",
                                             "replace")
                    dest = doc.resolve(entry.get("Dest") or doc.dict_of(entry.get("A")).get("D"))
                    target = doc.resolve(dest[0]) if isinstance(dest, list) and dest else None
                    page = next((i + 1 for i, p in enumerate(pages) if p is target), 0)
                    if title:
                        out.append({"title": str(title)[:180], "page": page, "level": level})
                    walk(entry.get("First"), level + 1)
                    ref = entry.get("Next")
            walk(node.get("First"))
        except Exception:
            out = []
    if not _plausible_toc(out):
        out = []
        page = 0
        for line in text.splitlines():
            pm = re.match(r"## 第 (\d+) 页", line)
            if pm:
                page = int(pm.group(1))
                continue
            s = line.strip()
            if not s:
                continue
            hm = re.match(r"^(#{1,3})\s+(.+)", s)
            cm = re.match(r"^(第[一二三四五六七八九十百\d]+章(?:\s+.*)?)$", s)
            en = re.match(r"^(Chapter\s+\d+)\s*$", s)
            if hm or cm or en:
                title = hm.group(2) if hm else (cm.group(1) if cm else en.group(1))
                out.append({"title": title[:180], "page": page,
                            "level": len(hm.group(1)) if hm else 1})
                if len(out) >= 512:
                    break
    return clean_toc(out)


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed = {urllib.parse.urlparse(b["url"]).hostname for b in CATALOG}
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.port not in (None, 443):
            raise ValueError("教材下载跳转到了非官方地址")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_book(book_id: str, download: bool = False) -> tuple[dict, bytes, str]:
    book = next((b for b in CATALOG if b["id"] == book_id), None)
    if not book:
        raise ValueError("教材不在已核验目录中")
    with CACHE_LOCK:
        path = LIBRARY / book["filename"]
        raw = path.read_bytes() if path.is_file() else b""
        if not raw:
            if not download:
                raise FileNotFoundError("教材尚未下载")
            LIBRARY.mkdir(parents=True, exist_ok=True)
            opener = urllib.request.build_opener(OfficialRedirect())
            req = urllib.request.Request(book["url"], headers={"User-Agent": "CSLA/1.0"})
            deadline = time.monotonic() + 90
            parts, size = [], 0
            with opener.open(req, timeout=15) as resp:
                while True:
                    if time.monotonic() > deadline:
                        raise ValueError("下载超时，请稍后重试")
                    part = resp.read(65536)
                    if not part:
                        break
                    size += len(part)
                    if size > MAX_BYTES:
                        raise ValueError("教材超过32 MB上限")
                    parts.append(part)
            raw = b"".join(parts)
        digest = hashlib.sha256(raw).hexdigest()
        if not raw.startswith(b"%PDF") or digest != book["sha256"]:
            raise ValueError("教材校验失败：官方文件可能更新，请先更新教材目录的版本信息")
        cache = path.with_suffix(".text.json")
        saved = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
        if saved.get("sha256") == digest and saved.get("text"):
            text = saved["text"]
        else:
            text, info = pdftext.pdf_to_text(raw)
            cache.write_text(json.dumps({"sha256": digest, "text": text, "info": info},
                                        ensure_ascii=False), encoding="utf-8")
        if not path.is_file():
            path.write_bytes(raw)
        return book, raw, text


def import_book(store, book_id: str, folder_id: str, download: bool = False) -> dict:
    book, raw, text = get_book(book_id, download)
    folder = store.folder(folder_id)
    if not folder:
        raise ValueError("请先选择一个存在的文件夹")
    # 同一个文件夹内幂等；换文件夹可再次导入。
    existing = next((m for m in store.list_materials(folder_id)
                     if m.get("source_url") == book["url"] and
                     str(m.get("original") or "").lower().endswith(".pdf")), None)
    if existing:
        if existing.get("status") != "approved":
            raise ValueError("同一本教材已导入但待审核，请先审核通过")
        store.set_reference(existing["id"], True, book["toc"],
                            {k: v for k, v in book.items() if k != "toc"})
        return store.material(existing["id"])
    material = store.add_material(book["title"], text, subject=folder["name"],
                                  folder_id=folder_id, source_url=book["url"],
                                  original=raw, original_ext=".pdf")
    store.replace_chunks(material["id"], rag.chunk_text(text))
    store.set_reference(material["id"], True, book["toc"],
                        {k: v for k, v in book.items() if k != "toc"})
    return store.material(material["id"])


def seed_books(store) -> int:
    """每个账号首次升级导入已有PDF；删除/移出后不在启动时悄悄恢复。"""
    count = 0
    for book in CATALOG:
        key = "reference_seed_" + book["id"]
        if store.get_config().get(key):
            continue
        folder = store.folder_by_slug(book["subject_slug"])
        if not folder or not (LIBRARY / book["filename"]).is_file():
            continue
        try:
            import_book(store, book["id"], folder["id"])
        except (OSError, ValueError, pdftext.PdfError):
            continue
        store.set_config(key, "1")
        count += 1
    return count


def seed_guides(store) -> int:
    """把随源码分发的中文专题导入各账号；不自动恢复用户删除的资料。"""
    count = 0
    for slug in ("co", "cn", "os", "ds"):
        path = APP / "study_guides" / (slug + ".md")
        key = "reference_guide_" + slug + "_v1"
        folder = store.folder_by_slug(slug)
        if store.get_config().get(key) or not folder or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip()
        toc = [{"title": title, "page": 0, "level": len(mark) - 1}
               for mark, title in re.findall(r"(?m)^(#{2,3}) (.+)$", text)]
        material = store.add_material(title + "（中文专题）", text, folder_id=folder["id"],
                                      subject=folder["name"], original=text.encode("utf-8"),
                                      original_ext=".md")
        store.replace_chunks(material["id"], rag.chunk_text(text))
        store.set_reference(material["id"], True, clean_toc(toc), {
            "author": "CSLA 编写（AI辅助）", "language": "中文",
            "kind": "中文专题学习指南", "institution": "项目补充资料",
            "description": "包含公式、逐步例题、边界条件、自测答案与原始参考链接；不是官方教材或真题。"})
        store.set_config(key, "1")
        count += 1
    return count


def chapter_plan(store, material_id: str, subject_id: str, granularity: str = "chapter") -> list[dict]:
    if granularity not in ("chapter", "section"):
        raise ValueError("请选择按大章或按小节生成")
    material, subject = store.material(material_id), store.subject(subject_id)
    if not material or not subject:
        raise ValueError("教材或目标科目不存在")
    folder = store.folder(material.get("folder_id") or "")
    if not folder or folder["name"] != subject["name"]:
        raise ValueError("请将教材放到目标科目的同名文件夹，再按目录建章节")
    if not material.get("is_reference") or material.get("status") != "approved":
        raise ValueError("请先将已审核资料设为主要参考文献")
    toc = stored_toc(material)
    if not toc:
        raise ValueError("教材没有可用目录，请先编辑目录")
    top = min(t["level"] for t in toc)
    existing = {c["title"] for s in store.subjects() if s["id"] == subject_id
                for c in s["chapters"]}
    plan, seen = [], set()
    paths = section_paths(toc)
    parent = ""
    for index, section in enumerate(toc):
        if section["level"] == top:
            parent = section["title"]
        end = next((j for j in range(index + 1, len(toc))
                    if toc[j]["level"] <= section["level"]), len(toc))
        descendants = toc[index + 1:end]
        target_level = top + 1 if granularity == "section" else top
        # 无小节的大章也保留；细分标题加父章，防止重复的“引言/练习”互相覆盖。
        standalone = section["level"] == top and not descendants
        if section["level"] != target_level and not (granularity == "section" and standalone):
            continue
        title = (parent + " / " + section["title"]
                 if granularity == "section" and section["level"] > top else section["title"])
        title = title[:180]
        if title in seen:
            continue
        seen.add(title)
        detail = f"教材章节：{section['original_title'] or section['title']}"
        child_level = min((t["level"] for t in descendants), default=0)
        topics = [t for t in descendants if t["level"] == child_level]
        outline = "\n".join(t["title"] + " | " + (t["original_title"] or t["title"]) for t in topics)
        if not outline:
            outline = ("概念、前置知识与学习目标\n核心原理与工作过程\n"
                       "公式、实现与适用条件\n逐步例题与结果验证\n边界情况、易错点与自测解析")
        plan.append(dict(section, title=title, reference_section=paths[index],
                         outline=outline, detail=detail, unit_count=len(topics) or 5,
                         action="skip" if title in existing else "add"))
    return plan


def evidence(store, chapter: dict, query: str, unit_index: int) -> tuple[str, list[dict]]:
    """只检索同文件夹已审核教材。优先绑定章节页区间；编号全章唯一。"""
    folder = store.folder_by_name(chapter["subject_name"])
    materials = store.reference_materials(folder["id"]) if folder else []
    if not materials and folder:
        # 没有标记“主要参考文献”时退回该文件夹的已审核资料，避免整节完全没有出处。
        materials = [m for m in store.list_materials(folder["id"])
                     if (m.get("status") or "approved") == "approved"]
    bound = chapter.get("reference_material_id")
    # 中文标题通常是连续长句，直接整句匹配会漏掉仅措辞不同的相关内容。
    # 使用项目已有的中文二字词和英文词；单字过于宽泛，不作为独立证据。
    terms = {t for t in rag.tokenize(query.lower()) if len(t) >= 2 and not t.isdigit()}
    topic = re.split(r"[：:，,、与和]", query.lower(), maxsplit=1)[0]
    topic_terms = {t for t in rag.tokenize(topic) if len(t) >= 2 and not t.isdigit()}
    snippets, citations, books = [], [], []
    for mat in materials:
        local_terms = set(terms)
        text = store.get_material_text(mat["id"])
        pages = re.split(r"(?m)^## 第 (\d+) 页\s*\n", text)
        candidates = [(int(pages[i]), pages[i + 1]) for i in range(1, len(pages) - 1, 2)]
        if not candidates:
            candidates = [(0, text)]
        toc = stored_toc(mat)
        paths = section_paths(toc)
        section_name = chapter.get("reference_section")
        section_index = next((i for i, key in enumerate(paths)
                              if mat["id"] == bound and key == section_name), None)
        if section_index is None:  # 兼容升级前仅记录标题的章节。
            section_index = next((i for i, t in enumerate(toc)
                                  if mat["id"] == bound and t["title"] == section_name), None)
        section = toc[section_index] if section_index is not None else None
        if section:
            local_terms.update(re.findall(r"[a-z]{2,}", section["original_title"].lower()))
        if section and section["page"]:
            end = next((t["page"] for t in toc if t["page"] > section["page"]
                        and t["level"] <= section["level"]), 10001)
            candidates = [(p, s) for p, s in candidates if section["page"] <= p < end]
        elif section and not any(p for p, _ in candidates):
            # Markdown专题按标题限制范围，不能把相邻专题混入绑定小节。
            matches = list(re.finditer(r"(?m)^#{1,6}[ \t]+" + re.escape(section["title"]) + r"[ \t]*$", text))
            occurrence = sum(t["title"] == section["title"] for t in toc[:section_index + 1]) - 1
            marker = matches[occurrence] if len(matches) > occurrence else None
            if marker:
                level = len(marker.group(0).split(" ", 1)[0])
                following = re.search(r"(?m)^#{1," + str(level) + r"}\s+", text[marker.end():])
                end = marker.end() + following.start() if following else len(text)
                candidates = [(0, text[marker.start():end])]
        ranked = []
        for page, content in candidates:
            # 500字符窗口防止长页把真正相关内容挤出上下文。
            content = rag.strip_meta(content)
            # 以原文标题划分专题，避免相邻概念被同一个滑动窗口混在一起。
            passages = re.split(r"(?m)(?=^#{1,6}[ \t]+)", content)
            windows = []
            for passage in passages:
                heading = passage.split('\n', 1)[0] if passage.startswith('#') else ''
                for start in range(0, len(passage), 500):
                    windows.append((heading, passage[start:start + 1000]))
            for heading, snippet in windows:
                matched = {t for t in local_terms if t in snippet.lower()}
                # 多词查询至少命中两个不同词，避免凭一个常见字词误判相关。
                heading_hits = {t for t in local_terms if t in heading.lower()}
                score = len(matched) + 3 * len(heading_hits)
                minimum = 2 if len(local_terms) >= 3 and not section else 1
                topic_hits = sum(t in snippet.lower() for t in topic_terms)
                topic_ok = section or not topic_terms or topic_hits >= min(2, len(topic_terms))
                if len(matched) >= minimum and topic_ok:
                    ranked.append((score, page, snippet))
        if ranked:
            books.append((mat["id"] == bound, max(r[0] for r in ranked), mat, ranked))
    # 先绑定教材，再按相关度选择补充文献；不让最早导入的四本垄断检索。
    for _, _, mat, ranked in sorted(books, key=lambda x: (x[0], x[1]), reverse=True)[:6]:
        selected = []
        for score, page, snippet in sorted(ranked, key=lambda x: x[0], reverse=True):
            # 同页滑窗大幅重叠时只取一段，给其他相关页留空间。
            if any(page == p and (snippet[:150] in s or s[-150:] in snippet) for p, s in selected):
                continue
            if len(selected) == 3:
                break
            selected.append((page, snippet))
            label = f"PDF第{page}页" if page else "中文专题/正文摘录（无PDF页码）"
            block = f"[c{unit_index * 20 + len(citations) + 1}] 来源：{mat['title']}，{label}\n{snippet}"
            if sum(len(s) + 2 for s in snippets) + len(block) > 14000:
                break
            cid = f"c{unit_index * 20 + len(citations) + 1}"
            citations.append({"citation_id": cid, "material_id": mat["id"], "title": mat["title"],
                              "source_url": mat.get("source_url", ""), "page": page,
                              "quote": snippet, "score": float(score)})
            snippets.append(block)
    return "\n\n".join(snippets), citations
