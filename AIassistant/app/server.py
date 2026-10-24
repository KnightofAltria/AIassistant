#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""计算机课程学习助手 —— 本地服务（仅标准库，无第三方依赖）。

启动：
    python server.py                 # 默认 127.0.0.1:8737
    python server.py --port 9000
    python server.py --mock          # 离线演示模式，不需要 API Key

启动后在浏览器打开 http://127.0.0.1:8737 ，先填写 DeepSeek API Key 进入。
所有数据保存在本文件所在目录的 data/ 下，可随时删除。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import deepseek
import prompts
import rag
import seed
from store import DATA_DIR, Store

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

STORE = Store()
LOCK = threading.Lock()
_RETRIEVER: rag.Retriever | None = None
_RETRIEVER_VERSION = -1


# ---------------------------------------------------------------- 检索缓存
def get_retriever() -> rag.Retriever:
    global _RETRIEVER, _RETRIEVER_VERSION
    version = STORE.stats()["chunks"]
    if _RETRIEVER is None or _RETRIEVER_VERSION != version:
        _RETRIEVER = rag.Retriever(STORE.all_chunks())
        _RETRIEVER_VERSION = version
    return _RETRIEVER


def client() -> deepseek.DeepSeekClient:
    cfg = STORE.get_config()
    return deepseek.DeepSeekClient(cfg.get("api_key", ""), cfg.get("model", deepseek.DEFAULT_MODEL))


def rag_context(query: str, subject: str = "", k: int = 8) -> rag.RagContext:
    """检索并组装证据。科目未知时先自动路由，命中不到再回退全库。"""
    retriever = get_retriever()
    routed = subject or rag.route_subject(retriever, query)
    hits = retriever.search(query, k=k, subject=routed or None)
    if not hits and routed:
        hits = retriever.search(query, k=k)          # 本科目无资料，回退全库
        routed = ""
    evidence, citations = rag.build_evidence(hits)
    return rag.RagContext(query=query, subject=routed, hits=hits, evidence=evidence,
                          citations=citations, insufficient=rag.insufficient_evidence(hits, query))


# ---------------------------------------------------------------- HTTP 处理
class Handler(BaseHTTPRequestHandler):
    server_version = "CSLA/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------ 基础工具
    def log_message(self, fmt: str, *args) -> None:      # 安静一点
        if "--verbose" in getattr(self.server, "flags", []):
            super().log_message(fmt, *args)

    def _json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400, **extra) -> None:
        self._json({"error": {"message": message, **extra}}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

    def _sse(self, event: str, data: dict) -> None:
        chunk = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        self.wfile.write(chunk.encode("utf-8"))
        self.wfile.flush()

    # ------------------------------------------------------------ 路由
    def do_GET(self) -> None:      # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                self._api_get(path, query)
            else:
                self._static(path)
        except Exception as exc:                      # noqa: BLE001
            self._error(f"服务器内部错误：{exc}", 500)

    def do_POST(self) -> None:     # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            self._api_post(parsed.path, self._body())
        except deepseek.DeepSeekError as exc:
            self._error(str(exc), 502, retryable=exc.retryable)
        except Exception as exc:                      # noqa: BLE001
            self._error(f"服务器内部错误：{exc}", 500)

    def do_DELETE(self) -> None:   # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        try:
            self._api_delete(parsed.path)
        except Exception as exc:                      # noqa: BLE001
            self._error(f"删除失败：{exc}", 500)

    # ------------------------------------------------------------ 静态文件
    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self._error("资源不存在", 404)
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------ GET API
    def _api_get(self, path: str, query: dict) -> None:
        if path == "/api/state":
            cfg = STORE.get_config()
            self._json({
                "configured": STORE.has_api_key() or deepseek.MOCK,
                "mock": deepseek.MOCK,
                "masked_key": STORE.mask_key(),
                "model": cfg.get("model", deepseek.DEFAULT_MODEL),
                "user": STORE.ensure_user(),
                "stats": STORE.stats(),
            })
            return

        if path == "/api/subjects":
            self._json({"subjects": STORE.subjects()})
            return

        m = re.fullmatch(r"/api/chapters/([\w-]+)", path)
        if m:
            chapter = STORE.chapter(m.group(1))
            if not chapter:
                self._error("章节不存在", 404)
                return
            self._json({"chapter": chapter, "questions": STORE.questions(chapter["id"])})
            return

        if path == "/api/conversations":
            self._json({"conversations": STORE.list_conversations()})
            return

        m = re.fullmatch(r"/api/conversations/([\w-]+)/messages", path)
        if m:
            self._json({"messages": STORE.messages(m.group(1))})
            return

        if path == "/api/summaries":
            self._json({"summaries": STORE.list_summaries(query.get("kind", [None])[0])})
            return

        if path == "/api/mistakes":
            self._json({"mistakes": STORE.list_mistakes()})
            return

        if path == "/api/materials":
            folder = query.get("folder", [""])[0]
            self._json({
                "materials": STORE.list_materials(folder if folder else None),
                "folders": STORE.list_folders(),
            })
            return

        if path == "/api/rag/search":
            q = query.get("q", [""])[0]
            subject = query.get("subject", [""])[0]
            ctx = rag_context(q, subject)
            self._json(ctx.as_dict())
            return

        if path == "/api/profile":
            self._json({"profile": STORE.ensure_user().get("profile", "")})
            return

        self._error("未知接口", 404)

    # ------------------------------------------------------------ POST API
    def _api_post(self, path: str, body: dict) -> None:
        # ---- 配置 API Key
        if path == "/api/config":
            key = (body.get("api_key") or "").strip()
            model = body.get("model") or deepseek.DEFAULT_MODEL
            probe = deepseek.DeepSeekClient(key, model)
            result = probe.validate()            # 失败会抛 DeepSeekError
            with LOCK:
                STORE.set_config("api_key", key)
                STORE.set_config("model", model)
            self._json({"ok": True, "models": result.get("models", []), "mock": deepseek.MOCK})
            return

        # ---- 对话（SSE 流式）
        if path == "/api/chat/stream":
            self._chat_stream(body)
            return

        # ---- 会话管理
        if path == "/api/conversations":
            conv = STORE.create_conversation(body.get("title") or "新对话")
            self._json({"conversation": conv}, 201)
            return

        m = re.fullmatch(r"/api/conversations/([\w-]+)/rename", path)
        if m:
            STORE.rename_conversation(m.group(1), body.get("title") or "未命名")
            self._json({"ok": True})
            return

        # ---- 生成近期总结
        if path == "/api/summaries/generate":
            cid = body.get("conversation_id") or ""
            messages = STORE.messages(cid) if cid else []
            if not messages:
                self._error("该会话没有消息，无法总结", 400)
                return
            transcript = "\n".join(f"{m['role']}：{m['content'][:600]}" for m in messages[-20:])
            text = client().complete(
                [{"role": "system", "content": prompts.SUMMARY_SYSTEM},
                 {"role": "user", "content": transcript}], max_tokens=900)
            title = messages[0]["content"][:24] or "近期总结"
            item = STORE.add_summary("recent", title, text, cid)
            # 同时更新用户画像
            try:
                profile = client().complete(
                    [{"role": "system", "content": prompts.PROFILE_SYSTEM},
                     {"role": "user", "content": transcript}], max_tokens=500)
                STORE.update_profile(profile)
            except deepseek.DeepSeekError:
                pass
            self._json({"summary": item}, 201)
            return

        # ---- 章节讲解（流式）
        m = re.fullmatch(r"/api/chapters/([\w-]+)/tutor", path)
        if m:
            self._chapter_tutor(m.group(1), body)
            return

        # ---- 生成题目
        m = re.fullmatch(r"/api/chapters/([\w-]+)/questions/generate", path)
        if m:
            self._generate_questions(m.group(1), int(body.get("n") or 3))
            return

        # ---- 判分
        if path == "/api/attempts":
            self._attempt(body)
            return

        # ---- 资料
        if path == "/api/materials":
            title = (body.get("title") or "").strip()
            text = body.get("text") or ""
            if not title or not text.strip():
                self._error("标题与内容都不能为空", 400)
                return
            material = STORE.add_material(
                title=title, text=text, subject=body.get("subject", ""),
                folder_id=body.get("folder_id", ""), source_url=body.get("source_url", ""))
            chunks = rag.chunk_text(text)
            STORE.replace_chunks(material["id"], chunks)
            self._json({"material": material, "chunks": len(chunks)}, 201)
            return

        if path == "/api/folders":
            name = (body.get("name") or "").strip()
            if not name:
                self._error("文件夹名不能为空", 400)
                return
            self._json({"folder": STORE.add_folder(name)}, 201)
            return

        m = re.fullmatch(r"/api/materials/([\w-]+)/move", path)
        if m:
            STORE.move_material(m.group(1), body.get("folder_id", ""))
            self._json({"ok": True})
            return

        self._error("未知接口", 404)

    # ------------------------------------------------------------ DELETE API
    def _api_delete(self, path: str) -> None:
        for pattern, action in (
            (r"/api/conversations/([\w-]+)", STORE.delete_conversation),
            (r"/api/materials/([\w-]+)", STORE.delete_material),
            (r"/api/folders/([\w-]+)", STORE.delete_folder),
            (r"/api/summaries/([\w-]+)", STORE.delete_summary),
            (r"/api/mistakes/([\w-]+)", STORE.delete_mistake),
            (r"/api/questions/([\w-]+)", STORE.delete_question),
        ):
            m = re.fullmatch(pattern, path)
            if m:
                action(m.group(1))
                self._json({"ok": True})
                return
        self._error("未知接口", 404)

    # ------------------------------------------------------------ 业务：对话
    def _chat_stream(self, body: dict) -> None:
        text = (body.get("text") or "").strip()
        if not text:
            self._error("消息不能为空", 400)
            return
        cid = body.get("conversation_id") or ""
        ephemeral = bool(body.get("ephemeral"))     # 章节内随手提问：不落会话记录
        if not ephemeral and not cid:
            conv = STORE.create_conversation(text[:20] or "新对话")
            cid = conv["id"]
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return

        ctx = rag_context(text)
        history = [{"role": m["role"], "content": m["content"]}
                   for m in STORE.messages(cid)][-8:] if cid else []

        system = prompts.CHAT_SYSTEM
        if ctx.evidence:
            system += f"\n\n参考资料（只能引用这些编号）：\n\n{ctx.evidence}"
        if ctx.insufficient:
            # 检索结果可疑时，宁可让模型少引用，也不要把无关资料当证据
            system += ("\n\n注意：本次检索到的资料与问题的相关性很低。"
                      "凡是与问题无关的资料，一律不要引用它的编号；"
                      "请明确说明「资料中没有找到足够依据」，再给出常识性补充并标明这是补充。")
        if ctx.subject:
            system += f"\n\n本次检索范围限定在科目：{ctx.subject}。"

        if not ephemeral:
            STORE.add_message(cid, "user", text)

        self._sse_start()
        self._sse("status", {"stage": "retrieving", "conversation_id": cid,
                             "hits": len(ctx.hits), "insufficient": ctx.insufficient,
                             "subject": ctx.subject, "top_score": round(ctx.top_score, 2)})
        collected: list[str] = []
        try:
            self._sse("status", {"stage": "generating"})
            for piece in client().stream_chat(
                    [{"role": "system", "content": system}, *history,
                     {"role": "user", "content": text}]):
                collected.append(piece)
                self._sse("delta", {"text": piece})
            answer = "".join(collected)
            verification = rag.validate_citations(answer, ctx.citations, ctx.insufficient)
            self._sse("status", {"stage": "verifying"})
            self._sse("citations", verification)
            mid = "" if ephemeral else STORE.add_message(cid, "assistant", answer, verification["items"])
            self._sse("completed", {"message_id": mid, "conversation_id": cid,
                                    "status": "completed"})
        except deepseek.DeepSeekError as exc:
            self._sse("failed", {"code": exc.status or 0, "message": str(exc),
                                 "retryable": exc.retryable})
        except BrokenPipeError:
            return
        finally:
            try:
                self.wfile.flush()
            except Exception:                        # noqa: BLE001
                pass

    # ------------------------------------------------------------ 业务：章节
    def _chapter_tutor(self, chapter_id: str, body: dict) -> None:
        chapter = STORE.chapter(chapter_id)
        if not chapter:
            self._error("章节不存在", 404)
            return
        if not STORE.has_api_key() and not deepseek.MOCK:
            self._error("尚未配置 DeepSeek API Key", 401)
            return
        ctx = rag_context(f"{chapter['title']} {chapter.get('outline', '')}",
                          subject=chapter.get("subject_name", ""))
        system = prompts.SUBJECT_TUTOR_SYSTEM.format(
            chapter=chapter["title"], subject=chapter["subject_name"])
        if ctx.evidence:
            system += f"\n\n参考资料（只能引用这些编号）：\n\n{ctx.evidence}"

        self._sse_start()
        self._sse("status", {"stage": "generating", "chapter_id": chapter_id})
        collected: list[str] = []
        try:
            for piece in client().stream_chat(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": f"请讲解本章：{chapter['title']}"}]):
                collected.append(piece)
                self._sse("delta", {"text": piece})
            answer = "".join(collected)
            STORE.set_outline(chapter_id, answer)
            verification = rag.validate_citations(answer, ctx.citations, ctx.insufficient)
            self._sse("citations", verification)
            self._sse("completed", {"status": "completed", "chapter_id": chapter_id})
        except deepseek.DeepSeekError as exc:
            self._sse("failed", {"code": exc.status or 0, "message": str(exc),
                                 "retryable": exc.retryable})

    def _generate_questions(self, chapter_id: str, n: int) -> None:
        chapter = STORE.chapter(chapter_id)
        if not chapter:
            self._error("章节不存在", 404)
            return
        n = max(1, min(n, 10))
        ctx = rag_context(f"{chapter['title']} 题目", subject=chapter.get("subject_name", ""))
        system = prompts.QUESTION_GEN_SYSTEM.format(n=n)
        user = f"章节：{chapter['title']}\n大纲：\n{chapter.get('outline', '')}\n"
        if ctx.evidence:
            user += f"\n参考资料：\n{ctx.evidence}"
        raw = client().complete([{"role": "system", "content": system},
                                 {"role": "user", "content": user}], max_tokens=1600)
        items = _parse_questions(raw)
        created = []
        for item in items[:n]:
            created.append(STORE.add_question(
                chapter_id, item.get("stem", ""), item.get("options", []),
                item.get("answer", ""), item.get("explanation", "")))
        self._json({"questions": created}, 201)

    def _attempt(self, body: dict) -> None:
        chapter_id = body.get("chapter_id", "")
        question_id = body.get("question_id", "")
        picked = (body.get("answer") or "").strip().upper()[:1]
        chapter = STORE.chapter(chapter_id) if chapter_id else None
        question = next((q for q in STORE.questions(chapter_id) if q["id"] == question_id), None)
        if not question:
            self._error("题目不存在", 404)
            return
        correct = question["answer"].strip().upper()[:1]
        ok = picked == correct
        if not ok:
            STORE.add_mistake(
                subject=chapter["subject_name"] if chapter else "",
                chapter=chapter["title"] if chapter else "",
                stem=question["stem"], my_answer=picked, right_answer=correct,
                note=question.get("explanation", ""))
        self._json({"correct": ok, "right_answer": correct,
                    "explanation": question.get("explanation", "")})


# ---------------------------------------------------------------- 工具函数
def _parse_questions(raw: str) -> list[dict]:
    """从模型输出里抠出 JSON 数组；容忍 ```json 包裹和前后废话。"""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not item.get("stem"):
            continue
        options = item.get("options") or []
        if not isinstance(options, list) or len(options) < 2:
            continue
        out.append({
            "stem": str(item["stem"])[:500],
            "options": [str(o)[:300] for o in options[:6]],
            "answer": str(item.get("answer", "A"))[:1].upper(),
            "explanation": str(item.get("explanation", ""))[:600],
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="计算机课程学习助手本地服务")
    ap.add_argument("--port", type=int, default=8737)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--mock", action="store_true", help="离线演示模式，不需要 API Key")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()

    if args.mock:
        deepseek.MOCK = True

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    seed.seed(STORE)
    samples = seed.seed_samples(STORE)
    if samples:
        print(f"  已导入内置示例资料 {samples} 份（可在界面里删除）")

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.flags = ["--verbose"] if args.verbose else []
    url = f"http://{args.host}:{args.port}"
    print("=" * 56)
    print("  计算机课程学习助手（本地版）")
    print(f"  地址：{url}")
    print(f"  数据目录：{DATA_DIR}")
    print(f"  模式：{'离线演示（--mock）' if deepseek.MOCK else 'DeepSeek API'}")
    print("=" * 56)
    if args.open:
        threading.Thread(target=lambda: (time.sleep(1.0), webbrowser.open(url)),
                         daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
