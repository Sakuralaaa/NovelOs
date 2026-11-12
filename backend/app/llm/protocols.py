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


# ---------------------------------------------------------------- v0.5：Agent 工具调用

def openai_tool_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """内部消息 → OpenAI chat 消息：assistant.tool_calls 的 arguments 序列化为字符串。"""
    import json

    out: list[dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": json.dumps(c.get("arguments") or {}, ensure_ascii=False)}}
                for c in m["tool_calls"]]})
        elif m.get("role") == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id") or "", "content": m.get("content") or ""})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


def _parse_args(raw: Any) -> dict[str, Any]:
    import json

    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        a, b = str(raw).find("{"), str(raw).rfind("}")
        try:
            v = json.loads(str(raw)[a : b + 1]) if a != -1 and b > a else {}
        except ValueError:
            v = {}
    return v if isinstance(v, dict) else {}


def parse_tool_response(data: dict[str, Any]) -> dict[str, Any]:
    msg = ((data.get("choices") or [{}])[0].get("message")) or {}
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    calls = []
    for i, c in enumerate(msg.get("tool_calls") or []):
        fn = c.get("function") or {}
        if not fn.get("name"):
            continue
        calls.append({"id": str(c.get("id") or f"call_{i}"), "name": str(fn["name"]), "arguments": _parse_args(fn.get("arguments"))})
    u = data.get("usage") or {}
    return {"content": str(content or ""), "tool_calls": calls,
            "usage": {"prompt_tokens": int(u.get("prompt_tokens") or 0), "completion_tokens": int(u.get("completion_tokens") or 0)}}


TEXT_TOOL_RULE = (
    "\n\n【工具调用协议】你不能直接调用函数。需要用工具时，在回复里输出一个或多个代码块，每块一次调用：\n"
    "```tool\n{\"name\": \"工具名\", \"arguments\": {...}}\n```\n"
    "输出工具代码块后就停下，等待「工具结果」。不需要工具时直接用中文回答作者。可用工具：\n"
)


def text_tool_messages(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, str]]:
    """不支持 function calling 的接口：工具说明进系统提示，工具结果作为 user 消息回填。"""
    import json

    spec = "\n".join(f"- {f['function']['name']}：{f['function'].get('description', '')} 参数："
                      f"{json.dumps(f['function'].get('parameters', {}).get('properties', {}), ensure_ascii=False)}" for f in tools)
    out: list[dict[str, str]] = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            out.append({"role": "system", "content": (m.get("content") or "") + TEXT_TOOL_RULE + spec})
        elif role == "assistant":
            text = m.get("content") or ""
            for c in m.get("tool_calls") or []:
                text += "\n```tool\n" + json.dumps({"name": c["name"], "arguments": c.get("arguments") or {}}, ensure_ascii=False) + "\n```"
            out.append({"role": "assistant", "content": text.strip() or "（调用工具）"})
        elif role == "tool":
            out.append({"role": "user", "content": f"工具结果（{m.get('name') or ''}）：\n{m.get('content') or ''}"})
        else:
            out.append({"role": "user", "content": m.get("content") or ""})
    # 连续同角色合并（anthropic / gemini 要求交替）
    merged: list[dict[str, str]] = []
    for m in out:
        if merged and merged[-1]["role"] == m["role"] and m["role"] != "system":
            merged[-1] = {"role": m["role"], "content": merged[-1]["content"] + "\n\n" + m["content"]}
        else:
            merged.append(m)
    return merged


_TOOL_BLOCK = re.compile(r"```tool\s*(\{.*?\})\s*```", re.S)


def parse_text_tool_calls(text: str, names: set[str]) -> dict[str, Any]:
    import json

    calls = []
    for i, m in enumerate(_TOOL_BLOCK.finditer(text or "")):
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("name") in names:
            calls.append({"id": f"call_t{i}", "name": obj["name"], "arguments": _parse_args(obj.get("arguments"))})
    content = _TOOL_BLOCK.sub("", text or "").strip()
    return {"content": content, "tool_calls": calls}
