#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DeepSeek API 客户端（只用标准库 urllib，SSE 流式）。

DeepSeek 兼容 OpenAI 协议：
  POST https://api.deepseek.com/chat/completions   {"model":"deepseek-chat", "stream":true}
  GET  https://api.deepseek.com/models             用于校验 Key
DeepSeek 没有 embedding 接口，因此检索走本地 BM25（见 rag.py）。

设置环境变量 CSLA_MOCK=1 时启用离线演示后端：不联网、不给 Key 也能跑通全链路，
用于本机自检与答辩演示。所有 mock 输出都会带 [演示模式] 前缀，不会被误当成真实回答。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEFAULT_MODEL = "deepseek-chat"
REASONER_MODEL = "deepseek-reasoner"
MOCK = os.environ.get("CSLA_MOCK", "") in ("1", "true", "yes")


class DeepSeekError(RuntimeError):
    def __init__(self, message: str, status: int = 0, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class DeepSeekClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, timeout: float = 120.0):
        self.api_key = (api_key or "").strip()
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout

    # ---------------------------------------------------------------- 基础请求
    def _request(self, path: str, payload: dict | None = None, stream: bool = False):
        url = f"{BASE_URL}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method="POST" if payload is not None else "GET")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "text/event-stream" if stream else "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:400]
            hint = {401: "API Key 无效或已过期", 402: "账户余额不足",
                    429: "请求过于频繁，请稍后再试"}.get(exc.code, "接口返回错误")
            raise DeepSeekError(f"{hint}（HTTP {exc.code}）：{body}", exc.code,
                                retryable=exc.code in (429, 500, 502, 503, 504)) from exc
        except urllib.error.URLError as exc:
            raise DeepSeekError(f"无法连接 DeepSeek：{exc.reason}", 0, retryable=True) from exc

    # ---------------------------------------------------------------- 校验 Key
    def validate(self) -> dict:
        if MOCK:
            return {"ok": True, "mock": True, "models": [DEFAULT_MODEL, REASONER_MODEL]}
        if not self.api_key:
            raise DeepSeekError("未填写 API Key", 401)
        with self._request("/models") as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        models = [m.get("id") for m in payload.get("data", [])]
        return {"ok": True, "models": models}

    # ---------------------------------------------------------------- 流式对话
    def stream_chat(self, messages: list[dict], temperature: float = 0.3,
                    max_tokens: int = 2048) -> "list[str] | object":
        if MOCK:
            return iter(_mock_stream(messages))
        payload = {
            "model": self.model, "messages": messages, "stream": True,
            "temperature": temperature, "max_tokens": max_tokens,
        }
        resp = self._request("/chat/completions", payload, stream=True)
        return _iter_sse(resp)

    # ---------------------------------------------------------------- 非流式
    def complete(self, messages: list[dict], temperature: float = 0.3,
                 max_tokens: int = 1024) -> str:
        if MOCK:
            return _mock_complete(messages)
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "max_tokens": max_tokens, "stream": False}
        with self._request("/chat/completions", payload) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise DeepSeekError(f"返回格式异常：{str(data)[:300]}") from exc


def _iter_sse(resp):
    """解析 SSE：逐行读 data: {...}，抽取 delta.content。"""
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                break
            try:
                obj = json.loads(body)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                yield piece
    finally:
        try:
            resp.close()
        except Exception:      # noqa: BLE001 - 关闭失败不影响主流程
            pass


# ---------------------------------------------------------------- 离线演示后端
def _has_evidence(messages: list[dict]) -> bool:
    return any("来源：" in m.get("content", "") for m in messages)


def _mock_stream(messages: list[dict]):
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    if _has_evidence(messages):
        text = ("[演示模式] 根据检索到的资料，结论如下：资料中给出的要点可以直接作为答案依据，"
                "我用 [c1] 标注了出处。若要更细的推导，可以继续追问。")
    elif "总结" in user:
        text = ("[演示模式] 本次对话围绕若干知识点展开，主要收获与待补充之处见下。"
                "（未配置 API Key，此处为本地演示文本）")
    else:
        text = ("[演示模式] 当前未配置 DeepSeek API Key，或处于离线自检状态。"
                "界面、流式输出、引用校验、资料检索等链路均为真实实现，"
                "只有模型生成部分是占位文本。填入 Key 后即为真实回答。")
    for i in range(0, len(text), 6):
        yield text[i:i + 6]


def _mock_complete(messages: list[dict]) -> str:
    joined = "\n".join(m.get("content", "") for m in messages)
    if "单选题" in joined or "出题" in joined:
        return json.dumps([
            {"stem": "[演示模式] 关于本知识点的说法，正确的是？",
             "options": ["A. 选项一", "B. 选项二", "C. 选项三", "D. 选项四"],
             "answer": "B", "explanation": "未配置 API Key，此处为占位题目，用于验证渲染与判分链路。"},
            {"stem": "[演示模式] 下列哪一项属于本知识点的典型应用？",
             "options": ["A. 场景一", "B. 场景二", "C. 场景三", "D. 场景四"],
             "answer": "A", "explanation": "占位解析。"},
        ], ensure_ascii=False)
    if "大纲" in joined or "讲解" in joined:
        return ("[演示模式] ## 本章要解决的问题\n占位内容。\n## 核心概念\n- 概念一\n- 概念二\n"
                "## 最小例子\n占位。\n## 常见误区\n- 误区一\n## 检验问题\n占位问题。"
                "（未配置 API Key，此为占位内容）")
    return "[演示模式] 未配置 API Key，此处为占位内容。填入 Key 后即为真实生成结果。"
