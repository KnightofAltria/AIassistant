#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端自检：对着已经启动的服务跑一遍全部主链路。

    # 终端 1
    python server.py --mock
    # 终端 2
    python selftest.py
    python selftest.py --base http://127.0.0.1:8737

不依赖第三方库。--mock 模式下不需要真实 API Key，用来验证
「界面后端链路是否通」，不代表模型质量。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []


def call(base: str, path: str, method: str = "GET", payload: dict | None = None,
         timeout: float = 60.0) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"raw": body}


def sse(base: str, path: str, payload: dict, timeout: float = 120.0) -> list[tuple[str, dict]]:
    req = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    events: list[tuple[str, dict]] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        buf = ""
        for raw in resp:
            buf += raw.decode("utf-8", "replace")
            while "\n\n" in buf:
                block, buf = buf.split("\n\n", 1)
                name, data = "message", []
                for line in block.split("\n"):
                    if line.startswith("event:"):
                        name = line[6:].strip()
                    elif line.startswith("data:"):
                        data.append(line[5:].strip())
                if data:
                    try:
                        events.append((name, json.loads("\n".join(data))))
                    except json.JSONDecodeError:
                        events.append((name, {"raw": "\n".join(data)}))
    return events


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {name} {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8737")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    # 1. 状态
    status, st = call(base, "/api/state")
    check("GET /api/state", status == 200 and "configured" in st,
          f"configured={st.get('configured')} mock={st.get('mock')}")

    # 2. 首页与静态资源
    for asset in ("/", "/style.css", "/app.js"):
        req = urllib.request.Request(base + asset)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                check(f"GET {asset}", resp.status == 200 and len(body) > 100,
                      f"{len(body)} bytes")
        except Exception as exc:                       # noqa: BLE001
            check(f"GET {asset}", False, str(exc))

    # 3. 科目树
    status, subs = call(base, "/api/subjects")
    subjects = subs.get("subjects", [])
    check("GET /api/subjects", status == 200 and len(subjects) >= 4,
          f"{len(subjects)} 个科目，共 {sum(len(s['chapters']) for s in subjects)} 章")

    # 4. 导入资料
    material_text = (
        "TCP 建立连接需要三次握手。第一次客户端发送 SYN；第二次服务端回复 SYN+ACK；"
        "第三次客户端发送 ACK，连接建立。三次握手是为了防止已失效的连接请求报文"
        "突然又传送到服务端，造成资源浪费。\n\n"
        "TCP 断开连接需要四次挥手：FIN、ACK、FIN、ACK。因为 TCP 是全双工的，"
        "两个方向需要分别关闭。\n\n"
        "UDP 是无连接协议，不保证顺序与可靠，适合实时音视频与 DNS 查询。\n\n"
        "操作系统中的进程是资源分配的基本单位，线程是调度的基本单位。线程共享进程的"
        "地址空间与文件描述符，但每个线程有独立的栈和寄存器上下文。"
    )
    status, res = call(base, "/api/materials", "POST", {
        "title": "自检用资料 · 网络与操作系统",
        "text": material_text,
        "subject": "计算机网络",
    })
    material_id = (res.get("material") or {}).get("id", "")
    chunks = res.get("chunks", 0)
    check("POST /api/materials", status == 201 and chunks > 0,
          f"切分 {chunks} 片，id={material_id[:8]}")

    # 5. 检索
    status, rag = call(base, "/api/rag/search?q=" + urllib.parse.quote("为什么三次握手"))
    hits = rag.get("hits", [])
    top_is_relevant = bool(hits) and "三次握手" in (hits[0].get("snippet") or "")
    check("GET /api/rag/search", status == 200 and top_is_relevant,
          f"命中 {len(hits)} 条，首位相关={top_is_relevant}")

    # 6. 聊天流（SSE）
    events = sse(base, "/api/chat/stream", {"text": "TCP 为什么需要三次握手？"})
    names = [e[0] for e in events]
    delta_text = "".join(d.get("text", "") for n, d in events if n == "delta")
    cite_event = next((d for n, d in events if n == "citations"), {})
    check("POST /api/chat/stream", "completed" in names and bool(delta_text),
          f"{len(events)} 个事件，文本 {len(delta_text)} 字")
    check("SSE 引用校验事件", "citations" in names,
          f"verification={cite_event.get('verification')}")
    check("SSE 事件顺序", names[:2] == ["status", "status"] and names[-1] == "completed",
          " -> ".join(names))

    # 7. 会话与消息落库
    status, convs = call(base, "/api/conversations")
    conv_list = convs.get("conversations", [])
    check("GET /api/conversations", status == 200 and len(conv_list) >= 1,
          f"{len(conv_list)} 个会话")
    if conv_list:
        status, msgs = call(base, f"/api/conversations/{conv_list[0]['id']}/messages")
        check("GET /api/conversations/{id}/messages", status == 200 and len(msgs.get("messages", [])) >= 2,
              f"{len(msgs.get('messages', []))} 条消息")

        # 8. 生成总结
        status, summ = call(base, "/api/summaries/generate", "POST",
                            {"conversation_id": conv_list[0]["id"]})
        check("POST /api/summaries/generate", status == 201 and bool(summ.get("summary")),
              f"总结长度 {len((summ.get('summary') or {}).get('content', ''))}")

    # 9. 章节 + 出题 + 判分
    if subjects:
        chapter = subjects[0]["chapters"][0]
        status, detail = call(base, f"/api/chapters/{chapter['id']}")
        check("GET /api/chapters/{id}", status == 200 and "outline" in detail.get("chapter", {}),
              chapter["title"])

        status, qres = call(base, f"/api/chapters/{chapter['id']}/questions/generate",
                            "POST", {"n": 2})
        questions = qres.get("questions", [])
        check("POST /questions/generate", status == 201 and len(questions) >= 1,
              f"生成 {len(questions)} 题")

        if questions:
            q = questions[0]
            status, attempt = call(base, "/api/attempts", "POST", {
                "chapter_id": chapter["id"], "question_id": q["id"], "answer": "Z",
            })
            check("POST /api/attempts", status == 200 and "correct" in attempt,
                  f"correct={attempt.get('correct')}")

        # 章节讲解（SSE）
        events = sse(base, f"/api/chapters/{chapter['id']}/tutor", {})
        names = [e[0] for e in events]
        text = "".join(d.get("text", "") for n, d in events if n == "delta")
        check("POST /chapters/{id}/tutor", "completed" in names and bool(text),
              f"{len(text)} 字")

    # 10. 易错本
    status, mistakes = call(base, "/api/mistakes")
    ok = status == 200 and len(mistakes.get("mistakes", [])) >= 1
    check("GET /api/mistakes（答错即入本）", ok,
          f"{len(mistakes.get('mistakes', []))} 条")

    # 11. 文件夹体系：共识 + 四学科
    status, data = call(base, "/api/materials")
    folders = data.get("folders", [])
    shared = [f for f in folders if f.get("is_shared")]
    check("文件夹体系", status == 200 and len(folders) >= 5 and len(shared) == 1,
          f"{len(folders)} 个文件夹，共识 {len(shared)} 个")

    # 12. 资料详情与源文件
    if data.get("materials"):
        mid = data["materials"][0]["id"]
        status, detail = call(base, f"/api/materials/{mid}")
        check("GET /api/materials/{id}", status == 200 and bool(detail.get("content")),
              f"路径 {detail.get('path', '')[-28:]}")
        req = urllib.request.Request(f"{base}/api/materials/{mid}/raw")
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            check("GET /api/materials/{id}/raw", resp.status == 200 and len(raw) > 50,
                  f"源文件 {len(raw)} 字节，Content-Type={resp.headers.get('Content-Type')}")

    # 13. 文件夹删除的两种模式
    status, folder = call(base, "/api/folders", "POST", {"name": "自检文件夹"})
    folder_id = (folder.get("folder") or {}).get("id", "")
    check("POST /api/folders", status == 201 and bool(folder_id), folder_id[:8])
    if folder_id:
        call(base, "/api/materials", "POST",
             {"title": "自检临时资料", "text": "临时资料内容，用于验证文件夹删除。",
              "folder_id": folder_id})
        status, res = call(base, f"/api/folders/{folder_id}?mode=move", "DELETE")
        check("DELETE 文件夹（保留资料）", status == 200 and res.get("mode") == "move",
              f"移出 {res.get('moved')} 份")

    status, folder2 = call(base, "/api/folders", "POST", {"name": "自检文件夹2"})
    fid2 = (folder2.get("folder") or {}).get("id", "")
    if fid2:
        status, res = call(base, f"/api/folders/{fid2}?mode=purge", "DELETE")
        check("DELETE 文件夹（连资料删除）", status == 200 and res.get("mode") == "purge", "")

    # 12. 删除链路
    if material_id:
        status, _ = call(base, f"/api/materials/{material_id}", "DELETE")
        check("DELETE /api/materials/{id}", status == 200, "已删除并清理切片")

    # 13. 错误处理
    status, err = call(base, "/api/materials", "POST", {"title": "", "text": ""})
    check("空资料返回 400", status == 400 and "error" in err, str(err.get("error", {}))[:60])

    # 汇总
    total = len(results)
    passed = sum(1 for _, r, _ in results if r == PASS)
    print("\n" + "=" * 56)
    print(f"自检结果：{passed}/{total} 通过")
    if passed != total:
        print("失败项：")
        for name, r, detail in results:
            if r == FAIL:
                print(f"  - {name}: {detail}")
    print("=" * 56)
    return 0 if passed == total else 1


if __name__ == "__main__":
    import urllib.parse       # noqa: E402  (仅在自检里用到)
    raise SystemExit(main())
