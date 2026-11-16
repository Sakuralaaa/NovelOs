"""v0.9.3 持久用量：每次模型调用写一条 llm_usage（route, model, book_id, kind, in/out tokens, ms）。

任务上下文（Job.kind / book_id）由任务系统通过 ContextVar 设置，网关调用处读取，不需要层层传参。
"""

from __future__ import annotations

import contextvars
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import select

from app.config import get_settings

log = logging.getLogger("novelos.usage")

_job_ctx: contextvars.ContextVar[tuple[str, int | None] | None] = contextvars.ContextVar("novelos_job_ctx", default=None)


def set_job_context(kind: str, book_id: int | None) -> contextvars.Token[Any]:
    return _job_ctx.set((kind, book_id))


def reset_job_context(token: contextvars.Token[Any]) -> None:
    try:
        _job_ctx.reset(token)
    except ValueError:  # pragma: no cover - 跨上下文
        _job_ctx.set(None)


def job_context() -> tuple[str, int | None] | None:
    return _job_ctx.get()


def est_tokens(chars: int) -> int:
    return max(0, int(round(chars * max(0.05, float(get_settings().tokens_per_char)))))


def _chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(m.get("content") or "")) for m in messages)


def record(*, task: str, route: str, model: str, messages: list[dict[str, Any]], output: Any, ms: int,
           usage: dict[str, Any] | None = None) -> None:
    if not get_settings().llm_usage_log:
        return
    ctx = job_context()
    kind, book_id = (ctx if ctx else (task, None))
    out_text = output if isinstance(output, str) else str(output or "")
    pin = int((usage or {}).get("prompt_tokens") or 0)
    pout = int((usage or {}).get("completion_tokens") or 0)
    estimated = not (pin or pout)
    if estimated:
        pin, pout = est_tokens(_chars(messages)), est_tokens(len(out_text))
    try:
        from app.db import session_scope
        from app.models.tables import LlmUsage

        with session_scope() as s:
            s.add(LlmUsage(route=route, model=model, book_id=book_id, kind=kind or task, task=task,
                           in_tokens=pin, out_tokens=pout, ms=max(0, int(ms)), estimated=estimated))
            s.commit()
    except Exception:  # pragma: no cover - 记账失败不影响主流程
        log.exception("记录 llm_usage 失败")


def avg_ms(route: str, n: int = 20) -> tuple[float, int]:
    """同 route 最近 n 次调用的平均耗时（毫秒）与样本数。mock 调用不算（耗时没有参考价值）。"""
    from app.db import session_scope
    from app.models.tables import LlmUsage

    with session_scope() as s:
        rows = list(s.exec(select(LlmUsage.ms).where(LlmUsage.route == route, LlmUsage.model != "mock")
                           .order_by(LlmUsage.id.desc()).limit(n)))  # type: ignore[union-attr]
    if not rows:
        return 0.0, 0
    return sum(int(r) for r in rows) / len(rows), len(rows)


def _agg(rows: list[Any], key: str) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = getattr(r, key) or ""
        a = out.setdefault(k, {key: k, "calls": 0, "in_tokens": 0, "out_tokens": 0, "ms": 0})
        a["calls"] += 1
        a["in_tokens"] += r.in_tokens
        a["out_tokens"] += r.out_tokens
        a["ms"] += r.ms
    return sorted(out.values(), key=lambda x: (-x["calls"], str(x[key])))


def summary(book_id: int | None = None, days: int | None = None) -> dict[str, Any]:
    from app.api.schemas import iso
    from app.db import session_scope
    from app.models.tables import LlmUsage

    with session_scope() as s:
        q = select(LlmUsage)
        if book_id is not None:
            q = q.where(LlmUsage.book_id == book_id)
        if days:
            q = q.where(LlmUsage.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
        rows = list(s.exec(q.order_by(LlmUsage.id)))  # type: ignore[arg-type]
    return {
        "book_id": book_id,
        "calls": len(rows),
        "in_tokens": sum(r.in_tokens for r in rows),
        "out_tokens": sum(r.out_tokens for r in rows),
        "ms": sum(r.ms for r in rows),
        "by_kind": _agg(rows, "kind"),
        "by_route": _agg(rows, "route"),
        "last_at": iso(rows[-1].created_at) if rows else None,
    }
