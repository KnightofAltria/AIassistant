#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地存储层：SQLite + 文件目录，全部落在程序所在文件夹下。

设计文档要求：
  · 资料、用户档案、近期总结、易错提示本全部保存在本地
  · 以上全部文件资料均应提供删除功能
所以这里所有实体都有 delete，且删除资料时同步清理其切片与磁盘文件。

只用标准库，不依赖任何第三方包。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
MATERIAL_DIR = DATA_DIR / "materials"
DB_PATH = DATA_DIR / "csla.db"
CONFIG_PATH = DATA_DIR / "config.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    profile TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    age TEXT DEFAULT '',
    gender TEXT DEFAULT '',
    major TEXT DEFAULT '',
    needs TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    slug TEXT DEFAULT '',
    is_shared INTEGER DEFAULT 0,
    ord INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS materials (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    subject TEXT DEFAULT '',
    folder_id TEXT DEFAULT '',
    source_url TEXT DEFAULT '',
    path TEXT DEFAULT '',
    bytes INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    material_id TEXT NOT NULL,
    ord INTEGER NOT NULL,
    text TEXT NOT NULL,
    FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_material ON chunks(material_id);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'chat',
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    citations TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
CREATE TABLE IF NOT EXISTS summaries (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    conversation_id TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mistakes (
    id TEXT PRIMARY KEY,
    subject TEXT DEFAULT '',
    chapter TEXT DEFAULT '',
    stem TEXT NOT NULL,
    my_answer TEXT DEFAULT '',
    right_answer TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subjects (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    is_builtin INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    outline TEXT DEFAULT '',
    is_builtin INTEGER DEFAULT 0,
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    question_id TEXT NOT NULL,
    chapter_id TEXT NOT NULL,
    answer TEXT DEFAULT '',
    correct INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    chapter_id TEXT NOT NULL,
    stem TEXT NOT NULL,
    options TEXT DEFAULT '[]',
    answer TEXT DEFAULT '',
    explanation TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (chapter_id) REFERENCES chapters(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'mistake',
    ref_id TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    chapter TEXT DEFAULT '',
    stem TEXT NOT NULL,
    answer TEXT DEFAULT '',
    note TEXT DEFAULT '',
    stage INTEGER DEFAULT 0,
    due_at TEXT NOT NULL,
    last_at TEXT DEFAULT '',
    reps INTEGER DEFAULT 0,
    lapses INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_due ON reviews(due_at);
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    model TEXT DEFAULT '',
    prompt_chars INTEGER DEFAULT 0,
    completion_chars INTEGER DEFAULT 0,
    tokens_est INTEGER DEFAULT 0,
    first_ms INTEGER DEFAULT 0,
    total_ms INTEGER DEFAULT 0,
    ok INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_log(created_at);
CREATE TABLE IF NOT EXISTS activity (
    day TEXT PRIMARY KEY,
    events INTEGER DEFAULT 0
);
"""


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """给老库补列，保证升级不用删数据。"""
        cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(folders)")}
        for name, ddl in (("slug", "TEXT DEFAULT ''"),
                          ("is_shared", "INTEGER DEFAULT 0"),
                          ("ord", "INTEGER DEFAULT 0")):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE folders ADD COLUMN {name} {ddl}")
        user_cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(users)")}
        for name in ("age", "gender", "major", "needs"):
            if name not in user_cols:
                self.conn.execute(f"ALTER TABLE users ADD COLUMN {name} TEXT DEFAULT ''")
        for table in ("subjects", "chapters"):
            have = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            if "is_builtin" not in have:
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN is_builtin INTEGER DEFAULT 0")
        # 历史数据：四个内置科目的章节统一标记为内置
        self.conn.execute(
            "UPDATE subjects SET is_builtin=1 WHERE slug IN ('co','cn','os','ds')")
        self.conn.execute(
            "UPDATE chapters SET is_builtin=1 WHERE subject_id IN "
            "(SELECT id FROM subjects WHERE slug IN ('co','cn','os','ds'))")
        mat_cols = {row["name"] for row in self.conn.execute("PRAGMA table_info(materials)")}
        for name, ddl in (("hash", "TEXT DEFAULT ''"),
                          ("status", "TEXT DEFAULT 'approved'"),
                          ("fetched_at", "TEXT DEFAULT ''")):
            if name not in mat_cols:
                self.conn.execute(f"ALTER TABLE materials ADD COLUMN {name} {ddl}")
        # 老资料补 hash：用于"重抓后内容是否真的变了"的判断
        for row in self.conn.execute(
                "SELECT id, path, hash FROM materials WHERE (hash IS NULL OR hash='')").fetchall():
            p = Path(row["path"] or "")
            if p.is_file():
                digest = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
                self.conn.execute("UPDATE materials SET hash=? WHERE id=?", (digest, row["id"]))
        self.conn.commit()

    # ---------------------------------------------------------------- 配置
    def get_config(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM config").fetchall()
        return {r["key"]: r["value"] for r in rows}

    def set_config(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO config(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def has_api_key(self) -> bool:
        return bool(self.get_config().get("api_key"))

    def mask_key(self) -> str:
        key = self.get_config().get("api_key", "")
        return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else ("已设置" if key else "")

    # ---------------------------------------------------------------- 用户
    def ensure_user(self, name: str = "本机用户") -> dict:
        row = self.conn.execute("SELECT * FROM users LIMIT 1").fetchone()
        if row:
            return dict(row)
        uid = new_id()
        self.conn.execute("INSERT INTO users(id, name, profile, created_at) VALUES(?,?,?,?)",
                          (uid, name, "", now()))
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())

    META_FIELDS = ("age", "gender", "major", "needs")

    def get_meta(self) -> dict:
        user = self.ensure_user()
        return {k: (user.get(k) or "") for k in self.META_FIELDS}

    def set_meta(self, data: dict) -> dict:
        user = self.ensure_user()
        for k in self.META_FIELDS:
            if k in data:
                self.conn.execute(f"UPDATE users SET {k}=? WHERE id=?",
                                  (str(data.get(k) or "")[:200], user["id"]))
        if data.get("name"):
            self.conn.execute("UPDATE users SET name=? WHERE id=?",
                              (str(data["name"])[:60], user["id"]))
        self.conn.commit()
        return self.get_meta()

    def meta_summary(self) -> str:
        """给模型看的一行学习者信息；全空时返回空串。"""
        m = self.get_meta()
        parts = []
        if m.get("age"):
            parts.append(f"年龄：{m['age']}")
        if m.get("gender"):
            parts.append(f"性别：{m['gender']}")
        if m.get("major"):
            parts.append(f"专业：{m['major']}")
        if m.get("needs"):
            parts.append(f"需求：{m['needs']}")
        return "；".join(parts)

    def update_profile(self, profile: str) -> None:
        user = self.ensure_user()
        self.conn.execute("UPDATE users SET profile=? WHERE id=?", (profile, user["id"]))
        self.conn.commit()

    # ---------------------------------------------------------------- 资料
    def add_material(self, title: str, text: str, subject: str = "", folder_id: str = "",
                     source_url: str = "", ext: str = ".md",
                     status: str = "approved") -> dict:
        mid = new_id()
        MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in title if ch not in '\\/:*?"<>|').strip() or mid
        path = MATERIAL_DIR / f"{mid[:8]}_{safe}{ext}"
        path.write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        ts = now()
        self.conn.execute(
            "INSERT INTO materials(id,title,subject,folder_id,source_url,path,bytes,created_at,"
            "hash,status,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (mid, title, subject, folder_id, source_url, str(path),
             path.stat().st_size, ts, digest, status, ts if source_url else ""))
        self.conn.commit()
        self.bump()
        return dict(self.conn.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone())

    def list_materials(self, folder_id: str | None = None) -> list[dict]:
        if folder_id is None:
            rows = self.conn.execute("SELECT * FROM materials ORDER BY created_at DESC").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM materials WHERE folder_id=? ORDER BY created_at DESC",
                (folder_id,)).fetchall()
        return [dict(r) for r in rows]

    def get_material_text(self, material_id: str) -> str:
        row = self.conn.execute("SELECT path FROM materials WHERE id=?", (material_id,)).fetchone()
        if not row or not Path(row["path"]).exists():
            return ""
        return Path(row["path"]).read_text(encoding="utf-8", errors="replace")

    def delete_material(self, material_id: str) -> None:
        row = self.conn.execute("SELECT path FROM materials WHERE id=?", (material_id,)).fetchone()
        if row and row["path"]:
            p = Path(row["path"])
            if p.exists():
                p.unlink()
        self.conn.execute("DELETE FROM chunks WHERE material_id=?", (material_id,))
        self.conn.execute("DELETE FROM materials WHERE id=?", (material_id,))
        self.conn.commit()
        self.bump()

    def all_chunks(self) -> list[dict]:
        """只返回"已审核通过"资料的切片。

        审核不是装饰：待审核（pending）和已驳回（rejected）的资料不进入检索索引，
        否则等于没审。老的空状态按通过处理，避免历史数据整体消失。
        """
        rows = self.conn.execute(
            "SELECT c.id, c.material_id, c.ord, c.text, m.title, m.subject "
            "FROM chunks c JOIN materials m ON m.id=c.material_id "
            "WHERE COALESCE(NULLIF(m.status, ''), 'approved') = 'approved'").fetchall()
        return [dict(r) for r in rows]

    def replace_chunks(self, material_id: str, texts: list[str]) -> None:
        self.conn.execute("DELETE FROM chunks WHERE material_id=?", (material_id,))
        self.conn.executemany(
            "INSERT INTO chunks(material_id, ord, text) VALUES(?,?,?)",
            [(material_id, i, t) for i, t in enumerate(texts)])
        self.conn.commit()
        self.bump()

    # ---------------------------------------------------------------- 索引版本
    def rev(self) -> int:
        """索引版本号：资料增删、切片重建、审核状态变化都会 +1。

        之前用"切片数量"当缓存版本，内容变了但切片数没变时就完全察觉不到，
        所以改成显式版本号——检索器只要对不上版本就重建。
        """
        row = self.conn.execute("SELECT value FROM config WHERE key='index_rev'").fetchone()
        try:
            return int(row["value"]) if row else 0
        except (TypeError, ValueError):
            return 0

    def bump(self) -> int:
        cur = self.rev() + 1
        self.conn.execute(
            "INSERT INTO config(key, value) VALUES('index_rev', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(cur),))
        self.conn.commit()
        return cur

    # ---------------------------------------------------------------- 文件夹
    def add_folder(self, name: str, slug: str = "", is_shared: bool = False,
                   ord: int = 100) -> dict:
        fid = new_id()
        self.conn.execute(
            "INSERT INTO folders(id,name,created_at,slug,is_shared,ord) VALUES(?,?,?,?,?,?)",
            (fid, name, now(), slug, 1 if is_shared else 0, ord))
        self.conn.commit()
        return {"id": fid, "name": name, "slug": slug, "is_shared": bool(is_shared)}

    def list_folders(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT f.*, (SELECT COUNT(*) FROM materials m WHERE m.folder_id=f.id) AS count "
            "FROM folders f ORDER BY f.is_shared DESC, f.ord, f.created_at").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["is_shared"] = bool(d.get("is_shared"))
            out.append(d)
        return out

    def folder_by_slug(self, slug: str) -> dict | None:
        if slug == "core":                 # 设计文档里叫 core，内部沿用小写 shared
            slug = "shared"
        row = self.conn.execute("SELECT * FROM folders WHERE slug=?", (slug,)).fetchone()
        return dict(row) if row else None

    def folder_by_name(self, name: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM folders WHERE name=?", (name,)).fetchone()
        return dict(row) if row else None

    def folder(self, folder_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM folders WHERE id=?", (folder_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_shared"] = bool(d.get("is_shared"))
        return d

    def rename_folder(self, folder_id: str, name: str) -> None:
        self.conn.execute("UPDATE folders SET name=? WHERE id=?", (name, folder_id))
        self.conn.commit()

    def delete_folder(self, folder_id: str, mode: str = "move") -> dict:
        """mode=move：只删文件夹，资料移到根目录；mode=purge：连资料一起删。"""
        moved = 0
        if mode == "purge":
            for m in self.list_materials(folder_id):
                self.delete_material(m["id"])
        else:
            moved = self.conn.execute(
                "SELECT COUNT(*) FROM materials WHERE folder_id=?", (folder_id,)).fetchone()[0]
            self.conn.execute("UPDATE materials SET folder_id='' WHERE folder_id=?", (folder_id,))
        self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self.conn.commit()
        return {"mode": mode, "moved": int(moved)}

    def move_material(self, material_id: str, folder_id: str) -> None:
        self.conn.execute("UPDATE materials SET folder_id=? WHERE id=?", (folder_id, material_id))
        self.conn.commit()

    def assign_orphan_materials(self) -> int:
        """把落在根目录的资料，按科目归入对应文件夹；没有科目的归入共识资料。"""
        folders = {f["slug"]: f for f in self.list_folders() if f.get("slug")}
        subjects = {s["slug"]: s["name"] for s in self.subjects()}
        count = 0
        for m in self.list_materials(""):
            target = None
            for slug, name in subjects.items():
                if m.get("subject") == name:
                    target = folders.get(slug)
                    break
            if target is None and folders.get("shared"):
                target = folders["shared"]
            if target:
                self.conn.execute("UPDATE materials SET folder_id=? WHERE id=?",
                                  (target["id"], m["id"]))
                count += 1
        self.conn.commit()
        return count

    # ---------------------------------------------------------------- 会话
    def create_conversation(self, title: str, kind: str = "chat") -> dict:
        cid = new_id()
        ts = now()
        self.conn.execute(
            "INSERT INTO conversations(id,kind,title,created_at,updated_at) VALUES(?,?,?,?,?)",
            (cid, kind, title, ts, ts))
        self.conn.commit()
        return {"id": cid, "title": title, "kind": kind}

    def list_conversations(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC").fetchall()]

    def delete_conversation(self, cid: str) -> None:
        self.conn.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
        self.conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
        self.conn.commit()

    def rename_conversation(self, cid: str, title: str) -> None:
        self.conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, cid))
        self.conn.commit()

    def add_message(self, cid: str, role: str, content: str, citations: list | None = None) -> str:
        mid = new_id()
        self.conn.execute(
            "INSERT INTO messages(id,conversation_id,role,content,citations,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (mid, cid, role, content, json.dumps(citations or [], ensure_ascii=False), now()))
        self.conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now(), cid))
        self.conn.commit()
        return mid

    def messages(self, cid: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at, rowid",
            (cid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["citations"] = json.loads(d.get("citations") or "[]")
            out.append(d)
        return out

    # ---------------------------------------------------------------- 总结
    def add_summary(self, kind: str, title: str, content: str, conversation_id: str = "") -> dict:
        sid = new_id()
        self.conn.execute(
            "INSERT INTO summaries(id,kind,title,content,conversation_id,created_at)"
            " VALUES(?,?,?,?,?,?)", (sid, kind, title, content, conversation_id, now()))
        self.conn.commit()
        return {"id": sid, "kind": kind, "title": title, "content": content}

    def list_summaries(self, kind: str | None = None) -> list[dict]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM summaries WHERE kind=? ORDER BY created_at DESC", (kind,)).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM summaries ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete_summary(self, sid: str) -> None:
        self.conn.execute("DELETE FROM summaries WHERE id=?", (sid,))
        self.conn.commit()

    # ---------------------------------------------------------------- 易错本
    def add_mistake(self, subject: str, chapter: str, stem: str, my_answer: str,
                    right_answer: str, note: str = "") -> dict:
        mid = new_id()
        self.conn.execute(
            "INSERT INTO mistakes(id,subject,chapter,stem,my_answer,right_answer,note,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (mid, subject, chapter, stem, my_answer, right_answer, note, now()))
        self.conn.commit()
        return {"id": mid}

    def list_mistakes(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM mistakes ORDER BY created_at DESC").fetchall()]

    def delete_mistake(self, mid: str) -> None:
        self.conn.execute("DELETE FROM mistakes WHERE id=?", (mid,))
        self.conn.commit()

    # ---------------------------------------------------------------- 科目
    def subjects(self) -> list[dict]:
        subs = [dict(r) for r in self.conn.execute(
            "SELECT * FROM subjects ORDER BY ord").fetchall()]
        for s in subs:
            s["chapters"] = [dict(r) for r in self.conn.execute(
                "SELECT * FROM chapters WHERE subject_id=? ORDER BY ord", (s["id"],)).fetchall()]
        return subs

    def chapters(self, subject_slug: str) -> list[dict]:
        row = self.conn.execute("SELECT * FROM subjects WHERE slug=?", (subject_slug,)).fetchone()
        if not row:
            return []
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM chapters WHERE subject_id=? ORDER BY ord", (row["id"],)).fetchall()]

    def chapter(self, chapter_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT c.*, s.name AS subject_name, s.slug AS subject_slug "
            "FROM chapters c JOIN subjects s ON s.id=c.subject_id WHERE c.id=?",
            (chapter_id,)).fetchone()
        return dict(row) if row else None

    def set_outline(self, chapter_id: str, outline: str) -> None:
        self.conn.execute("UPDATE chapters SET outline=? WHERE id=?", (outline, chapter_id))
        self.conn.commit()

    def questions(self, chapter_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM questions WHERE chapter_id=? ORDER BY rowid", (chapter_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["options"] = json.loads(d.get("options") or "[]")
            out.append(d)
        return out

    def add_question(self, chapter_id: str, stem: str, options: list, answer: str,
                     explanation: str = "") -> dict:
        qid = new_id()
        self.conn.execute(
            "INSERT INTO questions(id,chapter_id,stem,options,answer,explanation,created_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (qid, chapter_id, stem, json.dumps(options, ensure_ascii=False),
             answer, explanation, now()))
        self.conn.commit()
        return {"id": qid, "stem": stem, "options": options, "answer": answer,
                "explanation": explanation}

    def delete_question(self, qid: str) -> None:
        self.conn.execute("DELETE FROM questions WHERE id=?", (qid,))
        self.conn.commit()

    # ---------------------------------------------------------------- 科目增删改
    def add_subject(self, name: str, slug: str = "", is_builtin: bool = False) -> dict:
        if slug:
            exists = self.conn.execute("SELECT id FROM subjects WHERE slug=?", (slug,)).fetchone()
            if exists:
                raise ValueError(f"已存在 slug={slug} 的科目")
        sid = new_id()
        slug = slug or f"u{sid[:6]}"
        ord_ = self.conn.execute("SELECT COALESCE(MAX(ord),0)+1 FROM subjects").fetchone()[0]
        self.conn.execute(
            "INSERT INTO subjects(id,slug,name,ord,is_builtin) VALUES(?,?,?,?,?)",
            (sid, slug, name, ord_, 1 if is_builtin else 0))
        self.conn.commit()
        return {"id": sid, "slug": slug, "name": name, "is_builtin": is_builtin}

    def delete_subject(self, subject_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone()
        if not row:
            raise ValueError("科目不存在")
        if row["is_builtin"]:
            raise PermissionError(f"「{row['name']}」是内置科目，不允许删除")
        self.conn.execute("DELETE FROM questions WHERE chapter_id IN "
                          "(SELECT id FROM chapters WHERE subject_id=?)", (subject_id,))
        self.conn.execute("DELETE FROM chapters WHERE subject_id=?", (subject_id,))
        self.conn.execute("DELETE FROM subjects WHERE id=?", (subject_id,))
        self.conn.commit()
        return {"deleted": row["name"]}

    def subject(self, subject_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM subjects WHERE id=?", (subject_id,)).fetchone()
        return dict(row) if row else None

    def update_subject(self, subject_id: str, name: str) -> None:
        self.conn.execute("UPDATE subjects SET name=? WHERE id=?", (name, subject_id))
        self.conn.commit()

    # ---------------------------------------------------------------- 章节增删改
    def add_chapter(self, subject_id: str, title: str, outline: str = "",
                    is_builtin: bool = False) -> dict:
        cid = new_id()
        ord_ = self.conn.execute(
            "SELECT COALESCE(MAX(ord),-1)+1 FROM chapters WHERE subject_id=?",
            (subject_id,)).fetchone()[0]
        self.conn.execute(
            "INSERT INTO chapters(id,subject_id,title,ord,outline,is_builtin) VALUES(?,?,?,?,?,?)",
            (cid, subject_id, title, ord_, outline, 1 if is_builtin else 0))
        self.conn.commit()
        return {"id": cid, "title": title, "outline": outline, "is_builtin": is_builtin}

    def update_chapter(self, chapter_id: str, title: str | None = None,
                       outline: str | None = None) -> None:
        if title is not None:
            self.conn.execute("UPDATE chapters SET title=? WHERE id=?", (title, chapter_id))
        if outline is not None:
            self.conn.execute("UPDATE chapters SET outline=? WHERE id=?", (outline, chapter_id))
        self.conn.commit()

    def delete_chapter(self, chapter_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM chapters WHERE id=?", (chapter_id,)).fetchone()
        if not row:
            raise ValueError("章节不存在")
        self.conn.execute("DELETE FROM questions WHERE chapter_id=?", (chapter_id,))
        self.conn.execute("DELETE FROM chapters WHERE id=?", (chapter_id,))
        self.conn.commit()
        return {"deleted": row["title"], "was_builtin": bool(row["is_builtin"])}

    # ---------------------------------------------------------------- 作答记录
    def record_attempt(self, chapter_id: str, question_id: str, answer: str,
                       correct: bool) -> dict:
        aid = new_id()
        self.conn.execute(
            "INSERT INTO attempts(id,question_id,chapter_id,answer,correct,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (aid, question_id, chapter_id, answer, 1 if correct else 0, now()))
        self.conn.commit()
        return {"id": aid, "correct": correct}

    def chapter_stats(self, chapter_id: str) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*) AS total, SUM(correct) AS right FROM attempts WHERE chapter_id=?",
            (chapter_id,)).fetchone()
        total = int(row["total"] or 0)
        right = int(row["right"] or 0)
        total_q = self.conn.execute(
            "SELECT COUNT(*) FROM questions WHERE chapter_id=?", (chapter_id,)).fetchone()[0]
        return {"attempts": total, "correct": right, "wrong": total - right,
                "rate": round(right / total * 100, 1) if total else 0.0,
                "questions": total_q, "visited": total > 0}

    def wrong_questions(self, chapter_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT q.stem, q.answer, a.answer AS my_answer FROM attempts a "
            "JOIN questions q ON q.id = a.question_id "
            "WHERE a.chapter_id=? AND a.correct=0 ORDER BY a.created_at DESC LIMIT 20",
            (chapter_id,)).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- 用户档案（本地多份）
    @property
    def profile_dir(self) -> Path:
        d = DATA_DIR / "profile"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_profile(self, content: str, month: str | None = None) -> dict:
        month = month or time.strftime("%Y-%m")
        path = self.profile_dir / f"{month}.md"
        path.write_text(content, encoding="utf-8")
        self.update_profile(content)
        return {"month": month, "path": str(path), "bytes": path.stat().st_size}

    def list_profiles(self) -> list[dict]:
        out = []
        for path in sorted(self.profile_dir.glob("*.md"), reverse=True):
            out.append({"month": path.stem, "path": str(path),
                        "size": path.stat().st_size,
                        "preview": path.read_text(encoding="utf-8", errors="replace")[:200]})
        return out

    def read_profile(self, month: str) -> str:
        path = self.profile_dir / f"{month}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def delete_profile(self, month: str) -> None:
        path = self.profile_dir / f"{month}.md"
        if path.exists():
            path.unlink()

    # ---------------------------------------------------------------- 复习队列（间隔重复）
    def add_review(self, stem: str, answer: str = "", subject: str = "", chapter: str = "",
                   note: str = "", kind: str = "mistake", ref_id: str = "",
                   stage: int = 0, due_at: str = "") -> dict:
        """把一个待复习项排入队列。同一个题干不重复入队，只刷新到期时间。"""
        exists = self.conn.execute("SELECT * FROM reviews WHERE stem=?", (stem,)).fetchone()
        if exists:
            return dict(exists)
        rid = new_id()
        ts = now()
        self.conn.execute(
            "INSERT INTO reviews(id,kind,ref_id,subject,chapter,stem,answer,note,stage,"
            "due_at,last_at,reps,lapses,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, kind, ref_id, subject, chapter, stem[:500], answer, note,
             int(stage), due_at or ts, "", 0, 0, ts))
        self.conn.commit()
        return dict(self.conn.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone())

    def list_reviews(self, due_only: bool = False, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM reviews"
        args: tuple = ()
        if due_only:
            sql += " WHERE due_at <= ?"
            args = (now(),)
        sql += " ORDER BY due_at, created_at LIMIT ?"
        return [dict(r) for r in self.conn.execute(sql, args + (limit,)).fetchall()]

    def list_due_reviews(self, limit: int = 20) -> list[dict]:
        return self.list_reviews(due_only=True, limit=limit)

    def due_review_count(self) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE due_at <= ?", (now(),)).fetchone()[0])

    def review_forecast(self, days: int = 7) -> dict:
        """未来几天各有多少条到期，外加"已过期"的数量，用于看板上的预测条。"""
        today = datetime.now().date()
        items = []
        for offset in range(max(1, days)):
            day = (today + timedelta(days=offset)).isoformat()
            count = int(self.conn.execute(
                "SELECT COUNT(*) FROM reviews WHERE substr(due_at,1,10)=?", (day,)).fetchone()[0])
            items.append({"day": day, "count": count, "label": day[5:]})
        overdue = int(self.conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE due_at < ?", (today.isoformat(),)).fetchone()[0])
        return {"days": items, "overdue": overdue,
                "peak": max([i["count"] for i in items] + [1])}

    def grade_review(self, review_id: str, quality: str) -> dict | None:
        import extras                                  # 延迟导入：extras 不反向依赖 store
        row = self.conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
        if not row:
            return None
        stage, due = extras.srs_next(int(row["stage"] or 0), quality)
        lapses = int(row["lapses"] or 0) + (1 if quality == "again" else 0)
        self.conn.execute(
            "UPDATE reviews SET stage=?, due_at=?, last_at=?, reps=reps+1, lapses=? WHERE id=?",
            (stage, due.strftime("%Y-%m-%d %H:%M:%S"), now(), lapses, review_id))
        self.conn.commit()
        self.touch_activity()
        return dict(self.conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone())

    def delete_review(self, review_id: str) -> None:
        self.conn.execute("DELETE FROM reviews WHERE id=?", (review_id,))
        self.conn.commit()

    # ---------------------------------------------------------------- 调用统计（token / 耗时）
    def record_usage(self, kind: str, model: str = "", prompt_chars: int = 0,
                     completion_chars: int = 0, tokens_est: int = 0,
                     first_ms: int = 0, total_ms: int = 0, ok: bool = True) -> None:
        self.conn.execute(
            "INSERT INTO usage_log(kind,model,prompt_chars,completion_chars,tokens_est,"
            "first_ms,total_ms,ok,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (kind, model, int(prompt_chars), int(completion_chars), int(tokens_est),
             int(first_ms), int(total_ms), 1 if ok else 0, now()))
        self.conn.commit()

    def usage_stats(self, days: int = 14) -> dict:
        since = (datetime.now() - timedelta(days=max(1, days))).strftime("%Y-%m-%d 00:00:00")
        rows = self.conn.execute(
            "SELECT * FROM usage_log WHERE created_at >= ? ORDER BY created_at", (since,)
        ).fetchall()
        calls = len(rows)
        tokens = sum(int(r["tokens_est"] or 0) for r in rows)
        firsts = [int(r["first_ms"] or 0) for r in rows if int(r["first_ms"] or 0) > 0]
        totals = [int(r["total_ms"] or 0) for r in rows if int(r["total_ms"] or 0) > 0]
        by_kind: dict[str, int] = {}
        for r in rows:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        daily: dict[str, int] = {}
        for r in rows:
            day = (r["created_at"] or "")[:10]
            daily[day] = daily.get(day, 0) + 1
        return {
            "days": days, "calls": calls, "tokens_est": tokens,
            "avg_first_ms": int(sum(firsts) / len(firsts)) if firsts else 0,
            "avg_total_ms": int(sum(totals) / len(totals)) if totals else 0,
            "by_kind": by_kind,
            "daily": [{"day": d, "calls": n} for d, n in sorted(daily.items())],
            "failed": sum(1 for r in rows if not r["ok"]),
        }

    # ---------------------------------------------------------------- 打卡 / 连续学习
    def activity_map(self, weeks: int = 12) -> dict:
        """按天汇总学习活动：作答 + 提问 + 导入 + 复习，够画一张热力图。"""
        days: dict[str, int] = {}
        for sql in ("SELECT substr(created_at,1,10) d, COUNT(*) n FROM attempts GROUP BY d",
                    "SELECT substr(created_at,1,10) d, COUNT(*) n FROM messages "
                    "WHERE role='user' GROUP BY d",
                    "SELECT day d, events n FROM activity"):
            for row in self.conn.execute(sql).fetchall():
                if row["d"]:
                    days[row["d"]] = days.get(row["d"], 0) + int(row["n"] or 0)
        return {"days": [{"day": d, "count": n} for d, n in sorted(days.items())],
                "weeks": weeks, "total": sum(days.values()),
                "max": max(days.values()) if days else 0}

    def touch_activity(self, n: int = 1) -> None:
        day = time.strftime("%Y-%m-%d")
        self.conn.execute(
            "INSERT INTO activity(day, events) VALUES(?,?) "
            "ON CONFLICT(day) DO UPDATE SET events=events+excluded.events", (day, int(n)))
        self.conn.commit()

    def streak(self) -> dict:
        days = {r["day"] for r in self.conn.execute("SELECT day FROM activity").fetchall()}
        if not days:
            return {"days": 0, "today": time.strftime("%Y-%m-%d"), "total_days": 0}
        today = datetime.now().date()
        cursor = today
        if today.isoformat() not in days:          # 今天还没学，从昨天开始算
            cursor = today - timedelta(days=1)
        count = 0
        while cursor.isoformat() in days:
            count += 1
            cursor -= timedelta(days=1)
        return {"days": count, "today": today.isoformat(), "total_days": len(days)}

    # ---------------------------------------------------------------- 掌握度
    def mastery(self) -> dict:
        rows = self.conn.execute(
            "SELECT c.id, c.title, s.name AS subject, s.slug AS subject_slug, "
            "COUNT(a.id) AS total, COALESCE(SUM(a.correct),0) AS right, "
            "MAX(a.created_at) AS last_at "
            "FROM chapters c JOIN subjects s ON s.id=c.subject_id "
            "LEFT JOIN attempts a ON a.chapter_id=c.id "
            "GROUP BY c.id ORDER BY s.ord, c.ord").fetchall()
        chapters: list[dict] = []
        for r in rows:
            total, right = int(r["total"] or 0), int(r["right"] or 0)
            rate = round(right / total * 100, 1) if total else 0.0
            if total == 0:
                status = "未练习"
            elif rate < 60:
                status = "薄弱"
            elif rate < 85:
                status = "巩固中"
            else:
                status = "已掌握"
            chapters.append({
                "chapter_id": r["id"], "title": r["title"],
                "label": f"{r['subject']} · {r['title']}",
                "subject": r["subject"], "subject_slug": r["subject_slug"],
                "attempts": total, "correct": right, "rate": rate,
                "status": status, "last_at": r["last_at"] or "",
            })
        subjects: dict[str, dict] = {}
        for c in chapters:
            agg = subjects.setdefault(c["subject"], {"subject": c["subject"], "attempts": 0,
                                                     "correct": 0, "chapters": 0})
            agg["attempts"] += c["attempts"]
            agg["correct"] += c["correct"]
            agg["chapters"] += 1
        for agg in subjects.values():
            agg["rate"] = round(agg["correct"] / agg["attempts"] * 100, 1) if agg["attempts"] else 0.0
        total_a = sum(c["attempts"] for c in chapters)
        total_c = sum(c["correct"] for c in chapters)
        return {
            "chapters": chapters,
            "subjects": sorted(subjects.values(), key=lambda x: -x["attempts"]),
            "overall": {"attempts": total_a, "correct": total_c,
                        "rate": round(total_c / total_a * 100, 1) if total_a else 0.0},
        }

    def recommendations(self, limit: int = 5) -> list[dict]:
        """今日建议：复习到期 > 薄弱章节 > 没练过的章节。纯规则，不调模型。"""
        out: list[dict] = []
        due = self.due_review_count()
        if due:
            out.append({"type": "review", "title": f"先复习 {due} 条到期内容",
                        "detail": "间隔重复队列里到期了，趁热打铁最省时间", "weight": 100})
        mastery = self.mastery()
        weak = [c for c in mastery["chapters"] if c["status"] == "薄弱"]
        for c in weak[:2]:
            out.append({"type": "weak", "title": f"补一补「{c['title']}」",
                        "detail": f"正确率 {c['rate']}%，低于 60% 的及格线",
                        "weight": 80, "chapter_id": c["chapter_id"]})
        idle = [c for c in mastery["chapters"] if c["status"] == "未练习"]
        if idle:
            out.append({"type": "new", "title": f"开新章节：「{idle[0]['title']}」",
                        "detail": "还没做过这一章的题，先看讲解再练 3 道",
                        "weight": 60, "chapter_id": idle[0]["chapter_id"]})
        if not out:
            out.append({"type": "idle", "title": "今天状态清零，随便问一个问题",
                        "detail": "没有到期复习，也没有薄弱章节；可以去「AI 聊天」随便聊聊",
                        "weight": 10})
        return sorted(out, key=lambda x: -x["weight"])[:limit]

    # ---------------------------------------------------------------- 资料审核 / 版本
    def set_material_status(self, material_id: str, status: str) -> dict | None:
        status = status if status in ("pending", "approved", "rejected") else "pending"
        self.conn.execute("UPDATE materials SET status=? WHERE id=?", (status, material_id))
        self.conn.commit()
        self.bump()                        # 状态变了，检索索引必须跟着变
        row = self.conn.execute("SELECT * FROM materials WHERE id=?", (material_id,)).fetchone()
        return dict(row) if row else None

    def update_material_meta(self, material_id: str, **fields) -> None:
        allowed = {"hash", "status", "fetched_at", "title", "subject", "bytes"}
        pairs = [(k, v) for k, v in fields.items() if k in allowed]
        if not pairs:
            return
        sets = ", ".join(f"{k}=?" for k, _ in pairs)
        self.conn.execute(f"UPDATE materials SET {sets} WHERE id=?",
                          [v for _, v in pairs] + [material_id])
        self.conn.commit()
        self.bump()

    def pending_materials(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM materials WHERE status='pending' ORDER BY created_at DESC").fetchall()]

    def stale_materials(self, days: int = 30) -> list[dict]:
        """有来源链接、且抓取时间超过 days 天的资料，提醒复核。"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        rows = self.conn.execute(
            "SELECT * FROM materials WHERE source_url != '' AND (fetched_at='' OR fetched_at < ?)",
            (cutoff,)).fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- 统计
    def stats(self) -> dict:
        def one(sql: str, *args) -> int:
            return int(self.conn.execute(sql, args).fetchone()[0])
        return {
            "materials": one("SELECT COUNT(*) FROM materials"),
            "chunks": one("SELECT COUNT(*) FROM chunks"),
            "conversations": one("SELECT COUNT(*) FROM conversations"),
            "messages": one("SELECT COUNT(*) FROM messages"),
            "summaries": one("SELECT COUNT(*) FROM summaries"),
            "mistakes": one("SELECT COUNT(*) FROM mistakes"),
            "questions": one("SELECT COUNT(*) FROM questions"),
        }

    def wipe_all(self) -> None:
        """清空所有本地数据（设计文档要求所有资料都可删除）。"""
        for table in ("chunks", "materials", "messages", "conversations", "summaries",
                      "mistakes", "questions", "chapters", "subjects", "folders",
                      "reviews", "usage_log", "activity"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        if MATERIAL_DIR.exists():
            shutil.rmtree(MATERIAL_DIR, ignore_errors=True)
        MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
