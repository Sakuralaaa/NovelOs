"""模型调用追踪：内存里保留最近 N 次调用的完整提示词与输出，供调提示词时对照。

只在本进程内存里，重启清空；不落库，不对外发送。可用 NOVELOS_LLM_TRACE=0 关闭。
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from typing import Any

from app.config import get_settings

_MAX_MSG = 40_000
_lock = threading.Lock()
_ids = itertools.count(1)
_buf: deque[dict[str, Any]] | None = None


def _buffer() -> deque[dict[str, Any]] | None:
    global _buf
    s = get_settings()
    if not s.llm_trace:
        return None
    if _buf is None or _buf.maxlen != max(10, s.llm_trace_max):
        _buf = deque(_buf or [], maxlen=max(10, s.llm_trace_max))
    return _buf


def _clip(v: Any) -> Any:
    if isinstance(v, str) and len(v) > _MAX_MSG:
        return v[:_MAX_MSG] + f"\n…（截断，原长 {len(v)} 字）"
    return v


def record(
    *, task: str, role: str, model: str, channel: str, messages: list[dict[str, Any]], output: Any,
    started: float, error: str | None = None, usage: dict[str, Any] | None = None,
    temperature: float | None = None,
) -> None:
    with _lock:
        buf = _buffer()
        if buf is None:
            return
        buf.append({
            "id": next(_ids),
            "at": int(started),
            "duration_ms": int((time.time() - started) * 1000),
            "task": task, "role": role, "model": model, "channel": channel, "temperature": temperature,
            "messages": [{"role": m.get("role"), "content": _clip(m.get("content"))} for m in messages],
            "output": _clip(output),
            "error": error,
            "usage": usage or None,
        })


def _summary(e: dict[str, Any]) -> dict[str, Any]:
    out = e["output"]
    text = out if isinstance(out, str) else str(out)
    return {
        "id": e["id"], "at": e["at"], "duration_ms": e["duration_ms"], "task": e["task"], "role": e["role"],
        "model": e["model"], "channel": e["channel"], "error": e["error"], "usage": e["usage"],
        "prompt_chars": sum(len(str(m.get("content") or "")) for m in e["messages"]),
        "output_chars": len(text), "output_head": text[:120],
    }


def list_calls(task: str | None = None, limit: int = 50, after_id: int = 0) -> list[dict[str, Any]]:
    with _lock:
        items = list(_buf or [])
    items = [e for e in items if e["id"] > after_id and (not task or e["task"] == task)]
    return [_summary(e) for e in reversed(items)][: max(1, min(limit, 500))]


def get_call(cid: int) -> dict[str, Any] | None:
    with _lock:
        for e in _buf or []:
            if e["id"] == cid:
                return dict(e)
    return None


def clear() -> None:
    with _lock:
        if _buf is not None:
            _buf.clear()
