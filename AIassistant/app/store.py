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

import json
import shutil
import sqlite3
import time
import uuid
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
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
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
    ord INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chapters (
    id TEXT PRIMARY KEY,
    subject_id TEXT NOT NULL,
    title TEXT NOT NULL,
    ord INTEGER NOT NULL DEFAULT 0,
    outline TEXT DEFAULT '',
    FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
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

    def update_profile(self, profile: str) -> None:
        user = self.ensure_user()
        self.conn.execute("UPDATE users SET profile=? WHERE id=?", (profile, user["id"]))
        self.conn.commit()

    # ---------------------------------------------------------------- 资料
    def add_material(self, title: str, text: str, subject: str = "", folder_id: str = "",
                     source_url: str = "", ext: str = ".md") -> dict:
        mid = new_id()
        MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch for ch in title if ch not in '\\/:*?"<>|').strip() or mid
        path = MATERIAL_DIR / f"{mid[:8]}_{safe}{ext}"
        path.write_text(text, encoding="utf-8")
        self.conn.execute(
            "INSERT INTO materials(id,title,subject,folder_id,source_url,path,bytes,created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (mid, title, subject, folder_id, source_url, str(path),
             path.stat().st_size, now()))
        self.conn.commit()
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

    def all_chunks(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT c.id, c.material_id, c.ord, c.text, m.title, m.subject "
            "FROM chunks c JOIN materials m ON m.id=c.material_id").fetchall()
        return [dict(r) for r in rows]

    def replace_chunks(self, material_id: str, texts: list[str]) -> None:
        self.conn.execute("DELETE FROM chunks WHERE material_id=?", (material_id,))
        self.conn.executemany(
            "INSERT INTO chunks(material_id, ord, text) VALUES(?,?,?)",
            [(material_id, i, t) for i, t in enumerate(texts)])
        self.conn.commit()

    # ---------------------------------------------------------------- 文件夹
    def add_folder(self, name: str) -> dict:
        fid = new_id()
        self.conn.execute("INSERT INTO folders(id,name,created_at) VALUES(?,?,?)", (fid, name, now()))
        self.conn.commit()
        return {"id": fid, "name": name}

    def list_folders(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM folders ORDER BY created_at").fetchall()]

    def delete_folder(self, folder_id: str) -> None:
        for m in self.list_materials(folder_id):
            self.delete_material(m["id"])
        self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
        self.conn.commit()

    def move_material(self, material_id: str, folder_id: str) -> None:
        self.conn.execute("UPDATE materials SET folder_id=? WHERE id=?", (folder_id, material_id))
        self.conn.commit()

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
                      "mistakes", "questions", "chapters", "subjects", "folders"):
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        if MATERIAL_DIR.exists():
            shutil.rmtree(MATERIAL_DIR, ignore_errors=True)
        MATERIAL_DIR.mkdir(parents=True, exist_ok=True)
