#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具层：把软件的功能封装成模型可以调用的 tool。

设计文档第 34 条要求"把各种功能封装为 tools，允许软件自我修改"，例如在资料管理里
说一句话就完成分类与移动，在科目学习里说一句话就修改章节。这个文件就是那层封装。

约定：
  · 每个工具返回 dict，含 ok / summary（给人看的一句话）/ data。
  · 危险操作（删除）必须由调用方显式传 confirm=true，否则先返回"待确认"，
    把决定权留给用户，避免模型一句话就把资料删了。
  · 内置科目与内置章节不允许删除，删除请求会被拒绝并说明原因。
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import rag
from crawl import UA, html_to_text, trim

MAX_FETCH_BYTES = 2 * 1024 * 1024
FETCH_TIMEOUT = 20.0


@dataclass
class ToolContext:
    store: object
    retriever_factory: object = None      # 可选：() -> Retriever
    max_chars: int = 6000


# ---------------------------------------------------------------- 安全：URL 抓取
def _check_url(url: str) -> str:
    """只允许公网 http/https，挡掉内网/回环/文件协议（SSRF 防护）。"""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("只支持 http/https 链接")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("链接缺少主机名")
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ValueError(f"域名解析失败：{host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"禁止抓取内网地址：{ip}")
    return url


def fetch_url(url: str) -> str:
    url = _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                              "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        raw = resp.read(MAX_FETCH_BYTES + 1)
    if len(raw) > MAX_FETCH_BYTES:
        raise ValueError("页面超过 2 MB，已拒绝")
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------- 工具实现
def _find_material(store, title: str) -> dict | None:
    """按标题精确 → 包含 的顺序匹配资料。"""
    materials = store.list_materials()
    for m in materials:
        if m["title"] == title:
            return m
    for m in materials:
        if title and title in m["title"]:
            return m
    for m in materials:
        if title and m["title"] and m["title"] in title:
            return m
    return None


def _find_folder(store, name: str) -> dict | None:
    for f in store.list_folders():
        if f["name"] == name or f.get("slug") == name:
            return f
    for f in store.list_folders():
        if name and name in f["name"]:
            return f
    return None


def _find_subject(store, name: str) -> dict | None:
    for s in store.subjects():
        if s["name"] == name or s["slug"] == name:
            return s
    for s in store.subjects():
        if name and name in s["name"]:
            return s
    return None


def _find_chapter(store, subject: dict, title: str) -> dict | None:
    chapters = subject.get("chapters", [])
    for c in chapters:
        if c["title"] == title:
            return c
    for c in chapters:
        if title and title in c["title"]:
            return c
    return None


# ---- 资料类
def t_list_folders(ctx: ToolContext, **_) -> dict:
    folders = ctx.store.list_folders()
    total = ctx.store.stats()["materials"]
    lines = [f"{'🔒' if f['is_shared'] else '📁'} {f['name']}（{f['count']} 份）" for f in folders]
    return {"ok": True, "summary": f"共 {len(folders)} 个文件夹、{total} 份资料：" + "；".join(lines),
            "data": folders}


def t_list_materials(ctx: ToolContext, folder: str = "", **_) -> dict:
    target = _find_folder(ctx.store, folder) if folder else None
    materials = ctx.store.list_materials(target["id"] if target else None)
    lines = [f"{m['title']}（{m.get('subject') or '未分类'}）" for m in materials]
    return {"ok": True, "summary": f"列出 {len(materials)} 份资料：" + "；".join(lines[:30]),
            "data": [{"title": m["title"], "subject": m.get("subject", ""),
                      "folder_id": m.get("folder_id", ""), "path": m.get("path", "")}
                     for m in materials]}


def t_move_material(ctx: ToolContext, title: str, folder: str, **_) -> dict:
    material = _find_material(ctx.store, title)
    if not material:
        return {"ok": False, "summary": f"没有找到标题匹配「{title}」的资料"}
    target = _find_folder(ctx.store, folder)
    if not target:
        return {"ok": False, "summary": f"没有找到文件夹「{folder}」"}
    ctx.store.move_material(material["id"], target["id"])
    return {"ok": True, "summary": f"已把「{material['title']}」移动到「{target['name']}」"}


def t_classify_materials(ctx: ToolContext, **_) -> dict:
    moved = ctx.store.assign_orphan_materials()
    folders = {f["id"]: f for f in ctx.store.list_folders()}
    details = []
    for m in ctx.store.list_materials():
        f = folders.get(m.get("folder_id", ""), {})
        details.append(f"{m['title']}→{f.get('name', '根目录')}")
    return {"ok": True,
            "summary": f"已按科目归类 {moved} 份资料；当前分布：" + "；".join(details[:20]),
            "data": {"moved": moved}}


def t_create_folder(ctx: ToolContext, name: str, shared: bool = False, **_) -> dict:
    if ctx.store.folder_by_name(name):
        return {"ok": False, "summary": f"已存在同名文件夹「{name}」"}
    folder = ctx.store.add_folder(name, is_shared=shared)
    return {"ok": True, "summary": f"已创建文件夹「{name}」", "data": folder}


def t_delete_material(ctx: ToolContext, title: str, confirm: bool = False, **_) -> dict:
    material = _find_material(ctx.store, title)
    if not material:
        return {"ok": False, "summary": f"没有找到标题匹配「{title}」的资料"}
    if not confirm:
        return {"ok": False, "need_confirm": True,
                "summary": f"即将删除资料「{material['title']}」，请确认后我再执行"
                           "（需要用户明确同意，调用时传 confirm=true）"}
    ctx.store.delete_material(material["id"])
    return {"ok": True, "summary": f"已删除资料「{material['title']}」"}


def t_import_url(ctx: ToolContext, url: str, subject: str = "", folder: str = "",
                 title: str = "", **_) -> dict:
    try:
        raw = fetch_url(url)
    except (ValueError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "summary": f"抓取失败：{exc}"}
    text = trim(html_to_text(raw), ctx.max_chars)
    if len(text) < 200:
        return {"ok": False, "summary": "抓到的正文太短，可能不是文章页"}
    title = title or (text.splitlines()[0][:40] if text else url)
    target = _find_folder(ctx.store, folder) if folder else None
    if target is None and subject:
        target = _find_folder(ctx.store, subject)
    body = f"# {title}\n\n来源：{url}\n\n{text}\n"
    material = ctx.store.add_material(
        title=title, text=body, subject=subject,
        folder_id=target["id"] if target else "",
        source_url=url, ext=".md")
    chunks = rag.chunk_text(body)
    ctx.store.replace_chunks(material["id"], chunks)
    where = target["name"] if target else "根目录"
    return {"ok": True,
            "summary": f"已抓取并导入「{title}」（{len(text)} 字，{len(chunks)} 个切片，放入 {where}）",
            "data": {"material_id": material["id"], "chunks": len(chunks)}}


def t_search_materials(ctx: ToolContext, query: str, k: int = 5, **_) -> dict:
    if not ctx.retriever_factory:
        return {"ok": False, "summary": "检索器未初始化"}
    retriever = ctx.retriever_factory()
    hits = retriever.search(query, k=k)
    if not hits:
        return {"ok": True, "summary": f"没有检索到与「{query}」相关的资料", "data": []}
    return {"ok": True,
            "summary": f"检索到 {len(hits)} 段：" + "；".join(
                f"[{h.citation_id}] {h.title}（{round(h.score,1)} 分）" for h in hits),
            "data": [h.as_dict() for h in hits]}


# ---- 科目/章节类
def t_list_subjects(ctx: ToolContext, **_) -> dict:
    subjects = ctx.store.subjects()
    lines = []
    for s in subjects:
        mark = "内置" if s.get("is_builtin") else "自定义"
        lines.append(f"{s['name']}（{mark}，{len(s['chapters'])} 章："
                     + "、".join(c["title"] for c in s["chapters"][:8]) + "）")
    return {"ok": True, "summary": f"共 {len(subjects)} 个科目：" + "；".join(lines),
            "data": subjects}


def t_add_subject(ctx: ToolContext, name: str, **_) -> dict:
    if _find_subject(ctx.store, name):
        return {"ok": False, "summary": f"已存在科目「{name}」"}
    subject = ctx.store.add_subject(name, is_builtin=False)
    return {"ok": True, "summary": f"已创建科目「{name}」，接下来可以给它添加章节",
            "data": subject}


def t_delete_subject(ctx: ToolContext, name: str, confirm: bool = False, **_) -> dict:
    subject = _find_subject(ctx.store, name)
    if not subject:
        return {"ok": False, "summary": f"没有找到科目「{name}」"}
    if subject.get("is_builtin"):
        return {"ok": False, "summary": f"「{subject['name']}」是内置科目，不允许删除"}
    if not confirm:
        return {"ok": False, "need_confirm": True,
                "summary": f"即将删除科目「{subject['name']}」及其全部章节与题目，请用户确认后传 confirm=true"}
    ctx.store.delete_subject(subject["id"])
    return {"ok": True, "summary": f"已删除科目「{subject['name']}」"}


def t_add_chapter(ctx: ToolContext, subject: str, title: str, outline: str = "", **_) -> dict:
    target = _find_subject(ctx.store, subject)
    if not target:
        return {"ok": False, "summary": f"没有找到科目「{subject}」"}
    chapter = ctx.store.add_chapter(target["id"], title, outline, is_builtin=False)
    return {"ok": True, "summary": f"已在「{target['name']}」下新增章节「{title}」",
            "data": chapter}


def t_update_chapter(ctx: ToolContext, subject: str, title: str,
                     new_title: str = "", new_outline: str = "", **_) -> dict:
    target = _find_subject(ctx.store, subject)
    if not target:
        return {"ok": False, "summary": f"没有找到科目「{subject}」"}
    chapter = _find_chapter(ctx.store, target, title)
    if not chapter:
        return {"ok": False, "summary": f"「{target['name']}」下没有章节「{title}」"}
    ctx.store.update_chapter(chapter["id"],
                             title=new_title or None,
                             outline=new_outline or None)
    changed = "、".join(x for x in (("标题" if new_title else ""),
                                    ("大纲" if new_outline else "")) if x) or "内容"
    return {"ok": True, "summary": f"已更新「{chapter['title']}」的{changed}"}


def t_delete_chapter(ctx: ToolContext, subject: str, title: str,
                     confirm: bool = False, **_) -> dict:
    target = _find_subject(ctx.store, subject)
    if not target:
        return {"ok": False, "summary": f"没有找到科目「{subject}」"}
    chapter = _find_chapter(ctx.store, target, title)
    if not chapter:
        return {"ok": False, "summary": f"「{target['name']}」下没有章节「{title}」"}
    warning = "（注意：这是初始内置章节）" if chapter.get("is_builtin") else ""
    if not confirm:
        return {"ok": False, "need_confirm": True,
                "summary": f"即将删除章节「{chapter['title']}」{warning}及其题目，请用户确认后传 confirm=true"}
    ctx.store.delete_chapter(chapter["id"])
    return {"ok": True, "summary": f"已删除章节「{chapter['title']}」{warning}"}


def t_generate_questions(ctx: ToolContext, subject: str, title: str, n: int = 3,
                         **_) -> dict:
    """只做校验与信息回传，真正的生成由 server 调用模型完成。"""
    target = _find_subject(ctx.store, subject)
    if not target:
        return {"ok": False, "summary": f"没有找到科目「{subject}」"}
    chapter = _find_chapter(ctx.store, target, title)
    if not chapter:
        return {"ok": False, "summary": f"「{target['name']}」下没有章节「{title}」"}
    return {"ok": True, "action": "generate_questions",
            "summary": f"准备为「{target['name']} / {chapter['title']}」生成 {n} 道题",
            "data": {"chapter_id": chapter["id"], "n": n}}


# ---------------------------------------------------------------- 注册表
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: callable
    scope: tuple


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


TOOLS: dict[str, Tool] = {}


def _reg(name, desc, params, fn, scope):
    TOOLS[name] = Tool(name, desc, params, fn, scope)


_reg("list_folders", "列出所有资料文件夹及每个文件夹的资料数量。",
     _schema({}), t_list_folders, ("materials",))
_reg("list_materials", "列出资料，可按文件夹名筛选。",
     _schema({"folder": {"type": "string", "description": "文件夹名，可留空表示全部"}}),
     t_list_materials, ("materials",))
_reg("move_material", "把某份资料移动到指定文件夹（按标题匹配，支持模糊）。",
     _schema({"title": {"type": "string", "description": "资料标题或其中一部分"},
              "folder": {"type": "string", "description": "目标文件夹名"}},
             ["title", "folder"]), t_move_material, ("materials",))
_reg("classify_materials", "按科目把散落在根目录的资料自动归类到对应的科目文件夹。",
     _schema({}), t_classify_materials, ("materials",))
_reg("create_folder", "新建一个资料文件夹。",
     _schema({"name": {"type": "string"},
              "shared": {"type": "boolean", "description": "是否为不推荐修改的核心文件夹"}},
             ["name"]), t_create_folder, ("materials",))
_reg("delete_material", "删除一份资料（必须由用户确认后才传 confirm=true）。",
     _schema({"title": {"type": "string"},
              "confirm": {"type": "boolean", "description": "用户确认后才设为 true"}},
             ["title"]), t_delete_material, ("materials",))
_reg("import_url", "抓取一个网页链接，转成资料存入本地（自动截取正文并建索引）。",
     _schema({"url": {"type": "string"},
              "subject": {"type": "string", "description": "所属科目名，可空"},
              "folder": {"type": "string", "description": "放入哪个文件夹，可空"},
              "title": {"type": "string", "description": "自定义标题，可空"}},
             ["url"]), t_import_url, ("materials",))
_reg("search_materials", "在本地资料里检索片段，用于确认是否已有相关资料。",
     _schema({"query": {"type": "string"},
              "k": {"type": "integer", "description": "返回条数，默认 5"}},
             ["query"]), t_search_materials, ("materials",))

_reg("list_subjects", "列出所有科目、章节数量与章节名，以及是否为内置。",
     _schema({}), t_list_subjects, ("study",))
_reg("add_subject", "新建一个科目（用户要求新增科目时调用）。",
     _schema({"name": {"type": "string"}}, ["name"]), t_add_subject, ("study",))
_reg("delete_subject", "删除一个自定义科目（内置科目会被拒绝；需用户确认）。",
     _schema({"name": {"type": "string"},
              "confirm": {"type": "boolean"}}, ["name"]), t_delete_subject, ("study",))
_reg("add_chapter", "在指定科目下新增一个章节。",
     _schema({"subject": {"type": "string"},
              "title": {"type": "string"},
              "outline": {"type": "string", "description": "章节大纲，可空"}},
             ["subject", "title"]), t_add_chapter, ("study",))
_reg("update_chapter", "修改章节的标题或大纲。",
     _schema({"subject": {"type": "string"},
              "title": {"type": "string", "description": "现有章节标题"},
              "new_title": {"type": "string"},
              "new_outline": {"type": "string"}},
             ["subject", "title"]), t_update_chapter, ("study",))
_reg("delete_chapter", "删除一个章节（内置章节会提示；需用户确认）。",
     _schema({"subject": {"type": "string"},
              "title": {"type": "string"},
              "confirm": {"type": "boolean"}}, ["subject", "title"]),
     t_delete_chapter, ("study",))
_reg("generate_questions", "为某章节生成练习题。",
     _schema({"subject": {"type": "string"},
              "title": {"type": "string"},
              "n": {"type": "integer"}},
             ["subject", "title"]), t_generate_questions, ("study",))


def tools_for_scope(scope: str) -> list[dict]:
    """返回 OpenAI 兼容的 tools 描述，只含该场景允许的工具。"""
    out = []
    for tool in TOOLS.values():
        if scope in tool.scope:
            out.append({"type": "function",
                        "function": {"name": tool.name,
                                     "description": tool.description,
                                     "parameters": tool.parameters}})
    return out


def run_tool(scope: str, name: str, args: dict, ctx: ToolContext) -> dict:
    tool = TOOLS.get(name)
    if not tool or scope not in tool.scope:
        return {"ok": False, "summary": f"当前场景不支持工具「{name}」"}
    try:
        return tool.fn(ctx, **(args or {}))
    except PermissionError as exc:
        return {"ok": False, "summary": str(exc)}
    except TypeError as exc:
        return {"ok": False, "summary": f"参数不正确：{exc}"}
    except Exception as exc:                       # noqa: BLE001
        return {"ok": False, "summary": f"执行失败：{exc}"}
