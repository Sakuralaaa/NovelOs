"""各家接口格式的请求构造与响应解析。

统一输入：OpenAI 风格 messages（role=system/user/assistant，content 为字符串）。
统一输出：(text, usage{prompt_tokens, completion_tokens}, images[bytes 或 url])。
"""

from __future__ import annotations

import base64
import re
from typing import Any

FORMATS = ("openai", "responses", "anthropic", "gemini")


def url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def headers(fmt: str, api_key: str) -> dict[str, str]:
    h: dict[str, str] = {}
    if fmt == "anthropic":
        h["anthropic-version"] = "2023-06-01"
        if api_key:
            h["x-api-key"] = api_key
            h["Authorization"] = f"Bearer {api_key}"  # 兼容走 Bearer 的中转
    elif fmt == "gemini":
        if api_key:
            h["x-goog-api-key"] = api_key
    elif api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def _split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    sys = "\n\n".join(m["content"] for m in messages if m.get("role") == "system" and m.get("content"))
    rest = [m for m in messages if m.get("role") != "system"]
    return sys, rest


def chat_request(
    fmt: str, model: str, messages: list[dict[str, str]], temperature: float | None, max_tokens: int | None,
    want_image: bool = False,
) -> tuple[str, dict[str, Any]]:
    """返回 (path, body)。"""
    if fmt == "responses":
        sys, rest = _split_system(messages)
        body: dict[str, Any] = {"model": model, "input": [{"role": m["role"], "content": m["content"]} for m in rest]}
        if sys:
            body["instructions"] = sys
        if temperature is not None:
            body["temperature"] = temperature
        if max_tokens:
            body["max_output_tokens"] = max_tokens
        if want_image:
            body["tools"] = [{"type": "image_generation"}]
        return "/responses", body
    if fmt == "anthropic":
        sys, rest = _split_system(messages)
        body = {"model": model, "messages": rest or [{"role": "user", "content": "继续"}], "max_tokens": max_tokens or 8192}
        if sys:
            body["system"] = sys
        if temperature is not None:
            body["temperature"] = min(temperature, 1.0)
        return "/messages", body
    if fmt == "gemini":
        sys, rest = _split_system(messages)
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in rest]
        body = {"contents": contents or [{"role": "user", "parts": [{"text": "继续"}]}]}
        if sys:
            body["systemInstruction"] = {"parts": [{"text": sys}]}
        gen: dict[str, Any] = {}
        if temperature is not None:
            gen["temperature"] = temperature
        if max_tokens:
            gen["maxOutputTokens"] = max_tokens
        if want_image:
            gen["responseModalities"] = ["TEXT", "IMAGE"]
        if gen:
            body["generationConfig"] = gen
        return f"/models/{model.removeprefix('models/')}:generateContent", body
    body = {"model": model, "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens:
        body["max_tokens"] = max_tokens
    if want_image:
        body["modalities"] = ["image", "text"]
    return "/chat/completions", body


_MD_IMG = re.compile(r"!\[[^\]]*\]\((\S+?)\)")
_DATA_URL = re.compile(r"data:image/[a-zA-Z+.-]+;base64,([A-Za-z0-9+/=]+)")


def _img_from_url(u: str) -> bytes | str:
    m = _DATA_URL.match(u)
    return base64.b64decode(m.group(1)) if m else u


def parse_chat(fmt: str, data: dict[str, Any]) -> tuple[str, dict[str, int], list[bytes | str]]:
    texts: list[str] = []
    images: list[bytes | str] = []
    usage: dict[str, int] = {}
    if fmt == "responses":
        if isinstance(data.get("output_text"), str):
            texts.append(data["output_text"])
        for item in data.get("output") or []:
            if item.get("type") == "message" and not data.get("output_text"):
                for c in item.get("content") or []:
                    if c.get("type") in ("output_text", "text") and c.get("text"):
                        texts.append(c["text"])
            elif item.get("type") == "image_generation_call" and item.get("result"):
                images.append(base64.b64decode(item["result"]))
        u = data.get("usage") or {}
        usage = {"prompt_tokens": int(u.get("input_tokens") or 0), "completion_tokens": int(u.get("output_tokens") or 0)}
    elif fmt == "anthropic":
        for c in data.get("content") or []:
            if c.get("type") == "text" and c.get("text"):
                texts.append(c["text"])
            elif c.get("type") == "image" and (c.get("source") or {}).get("data"):
                images.append(base64.b64decode(c["source"]["data"]))
        u = data.get("usage") or {}
        usage = {"prompt_tokens": int(u.get("input_tokens") or 0), "completion_tokens": int(u.get("output_tokens") or 0)}
    elif fmt == "gemini":
        cands = data.get("candidates") or []
        for p in ((cands[0].get("content") or {}).get("parts") or []) if cands else []:
            if p.get("thought"):
                continue
            if p.get("text"):
                texts.append(p["text"])
            inline = p.get("inlineData") or p.get("inline_data")
            if inline and inline.get("data"):
                images.append(base64.b64decode(inline["data"]))
        u = data.get("usageMetadata") or {}
        usage = {"prompt_tokens": int(u.get("promptTokenCount") or 0), "completion_tokens": int(u.get("candidatesTokenCount") or 0)}
    else:
        msg = ((data.get("choices") or [{}])[0].get("message")) or {}
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):  # 多模态分段
            for c in content:
                if c.get("type") in ("text", "output_text") and c.get("text"):
                    texts.append(c["text"])
                elif c.get("type") == "image_url":
                    images.append(_img_from_url(str((c.get("image_url") or {}).get("url") or "")))
                elif c.get("type") == "image" and c.get("b64_json"):
                    images.append(base64.b64decode(c["b64_json"]))
        for im in msg.get("images") or []:  # OpenRouter 等
            u2 = (im.get("image_url") or {}).get("url") if isinstance(im, dict) else im
            if u2:
                images.append(_img_from_url(str(u2)))
        u = data.get("usage") or {}
        usage = {"prompt_tokens": int(u.get("prompt_tokens") or 0), "completion_tokens": int(u.get("completion_tokens") or 0)}
    text = "".join(texts)
    # 对话接口出图常见做法：正文里给 markdown 图片或 data URL
    for m in _MD_IMG.finditer(text):
        images.append(_img_from_url(m.group(1)))
    if not _MD_IMG.search(text):
        for m in _DATA_URL.finditer(text):
            images.append(base64.b64decode(m.group(1)))
    return text, usage, [i for i in images if i]


def models_request(fmt: str) -> tuple[str, dict[str, str]]:
    if fmt == "gemini":
        return "/models", {"pageSize": "1000"}
    if fmt == "anthropic":
        return "/models", {"limit": "1000"}
    return "/models", {}
