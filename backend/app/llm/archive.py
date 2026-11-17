"""v0.12 生成档案 + 成本：每次模型调用落一条 generation；按渠道里填的模型单价折算人民币；预算上限拦截。

- 档案：成功（ok）、空结果（empty，0 字 / 0 张图）、失败（failed，带原因）都记，输出全文保留。
- 单价：Channel.prices = {模型: {"in": 元/百万输入 token, "out": 元/百万输出 token, "image": 元/张}}；没填按 0 计，mock 不计费。
- 预算：KV budget = {"daily_cny": 每日上限, "book_cny": 单书累计上限}，0 或不填表示不限；超出时调用前直接拦下。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from app.llm import usage as usage_log

log = logging.getLogger("novelos.archive")

BUDGET_KEY = "budget"
PROMPT_KEEP = 4000
OUTPUT_KEEP = 200_000
SHORT_RATIO = 0.7  # 实际字数低于目标的 70% 记为字数不足


class BudgetExceeded(Exception):
    pass


import contextvars  # noqa: E402

_parent: contextvars.ContextVar[tuple[int, str] | None] = contextvars.ContextVar("novelos_gen_parent", default=None)


def set_parent(parent_id: int, note: str) -> contextvars.Token[Any]:
    """追问：这之后落的档案 parent_id 指向原条，note 记作者的追问要求。"""
    return _parent.set((parent_id, note[:500]))


def reset_parent(token: contextvars.Token[Any]) -> None:
    try:
        _parent.reset(token)
    except ValueError:  # pragma: no cover
        _parent.set(None)


def count_words(text: str) -> int:
    """中文按字计，英文/数字按词计。"""
    t = text or ""
    return len(re.findall(r"[\u4e00-\u9fff]", t)) + len(re.findall(r"[A-Za-z0-9]+", t))


def price_of(prices: dict[str, Any] | None, model: str) -> tuple[float, float]:
    p = (prices or {}).get(model) or {}
    try:
        return max(0.0, float(p.get("in") or 0)), max(0.0, float(p.get("out") or 0))
    except (TypeError, ValueError, AttributeError):
        return 0.0, 0.0


def cost_cny(prices: dict[str, Any] | None, model: str, in_tokens: int, out_tokens: int) -> float:
    pi, po = price_of(prices, model)
    return round((in_tokens * pi + out_tokens * po) / 1_000_000, 6)


def channel_prices(channel_id: int | None) -> dict[str, Any]:
    if not channel_id:
        return {}
    try:
        from app.db import session_scope
        from app.models.tables import Channel

        with session_scope() as s:
            c = s.get(Channel, channel_id)
            return dict(c.prices or {}) if c is not None else {}
    except Exception:  # pragma: no cover
        return {}


# ---------------------------------------------------------------- 预算

def get_budget(s: Any) -> dict[str, float]:
    from app.db import kv_get

    b = kv_get(s, BUDGET_KEY, {}) or {}
    out = {}
    for k in ("daily_cny", "book_cny"):
        try:
            out[k] = max(0.0, float(b.get(k) or 0))
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


def _today_start() -> datetime:
    from app.config import get_settings

    tz_off = 8  # 默认按北京时间算「今天」
    try:
        tz_off = int(getattr(get_settings(), "budget_tz_offset", 8))
    except Exception:  # pragma: no cover
        pass
    now = datetime.now(timezone.utc) + timedelta(hours=tz_off)
    start_local = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local - timedelta(hours=tz_off)


def spent(s: Any, book_id: int | None = None, since: datetime | None = None) -> float:
    from app.models.tables import Generation

    q = select(func.coalesce(func.sum(Generation.cost_cny), 0.0))
    if book_id is not None:
        q = q.where(Generation.book_id == book_id)
    if since is not None:
        q = q.where(Generation.created_at >= since)
    v = s.exec(q).one()
    return float(v[0] if isinstance(v, tuple) else v or 0)


def budget_status(s: Any, book_id: int | None = None) -> dict[str, Any]:
    b = get_budget(s)
    today = spent(s, since=_today_start())
    out: dict[str, Any] = {**b, "today_cny": round(today, 4)}
    if book_id is not None:
        out["book_spent_cny"] = round(spent(s, book_id=book_id), 4)
    return out


def check_budget() -> None:
    """真实模型调用前检查预算；超了抛 BudgetExceeded（mock 不检查）。"""
    try:
        from app.db import session_scope

        ctx = usage_log.job_context()
        book_id = ctx[1] if ctx else None
        with session_scope() as s:
            b = get_budget(s)
            if not (b["daily_cny"] or b["book_cny"]):
                return
            if b["daily_cny"]:
                today = spent(s, since=_today_start())
                if today >= b["daily_cny"]:
                    raise BudgetExceeded(f"今日预算已用完：已用 ¥{today:.2f}，上限 ¥{b['daily_cny']:.2f}。到设置里调高上限后再试")
            if b["book_cny"] and book_id is not None:
                used = spent(s, book_id=book_id)
                if used >= b["book_cny"]:
                    raise BudgetExceeded(f"这本书的预算已用完：已用 ¥{used:.2f}，上限 ¥{b['book_cny']:.2f}。到设置里调高上限后再试")
    except BudgetExceeded:
        raise
    except Exception:  # pragma: no cover - 查账失败不拦调用
        log.exception("检查预算失败")


# ---------------------------------------------------------------- 档案

def _last_user(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            c = m.get("content")
            return c if isinstance(c, str) else str(c)
    return ""


def record(*, task: str, route: str, model: str, messages: list[dict[str, Any]] | None, output: str = "",
           ms: int = 0, usage: dict[str, Any] | None = None, status: str | None = None, error: str = "",
           channel_id: int | None = None, raw_model: str = "", meta: dict[str, Any] | None = None,
           images: int | None = None) -> int | None:
    """落一条档案，返回 id。任何异常都吞掉，不影响主流程。"""
    from app.config import get_settings

    if not getattr(get_settings(), "llm_usage_log", True):
        return None
    try:
        from app.db import session_scope
        from app.models.tables import Generation

        ctx = usage_log.job_context()
        kind, book_id = (ctx if ctx else (task, None))
        out_text = output if isinstance(output, str) else str(output or "")
        pin = int((usage or {}).get("prompt_tokens") or (usage or {}).get("input_tokens") or 0)
        pout = int((usage or {}).get("completion_tokens") or (usage or {}).get("output_tokens") or 0)
        if not (pin or pout):
            pin = usage_log.est_tokens(sum(len(str(m.get("content") or "")) for m in (messages or [])))
            pout = usage_log.est_tokens(len(out_text))
        if status is None:
            empty = (images == 0) if images is not None else not out_text.strip()
            status = "empty" if empty else "ok"
        target = 0
        for k in ("target_words", "scene_words"):
            try:
                target = int((meta or {}).get(k) or 0)
            except (TypeError, ValueError):
                target = 0
            if target:
                break
        prices = {} if model == "mock" else channel_prices(channel_id)
        if images is not None:
            try:
                cost = round(images * max(0.0, float(((prices.get(raw_model) or {}).get("image")) or 0)), 6)
            except (TypeError, ValueError, AttributeError):
                cost = 0.0
            pin = pout = 0
        else:
            cost = cost_cny(prices, raw_model, pin, pout)
        if status == "failed":
            pout, cost = 0, 0.0  # 失败的调用不记输出计费（上游一般不收）
        with session_scope() as s:
            g = Generation(book_id=book_id, job_id=usage_log.current_job_id(), kind=kind or task, task=task, route=route,
                           model=model, status=status, error=(error or "")[:1000], prompt=_last_user(messages or [])[:PROMPT_KEEP],
                           output=(out_text if images is None else f"（{images} 张图）")[:OUTPUT_KEEP],
                           output_words=count_words(out_text) if images is None else 0, target_words=max(0, target),
                           in_tokens=pin, out_tokens=pout, cost_cny=cost, ms=max(0, int(ms)))
            par = _parent.get()
            if par:
                g.parent_id, g.note = par

            s.add(g)
            s.commit()
            return g.id
    except Exception:  # pragma: no cover
        log.exception("记录生成档案失败")
        return None


def is_short(g: Any) -> bool:
    return bool(g.target_words and g.status == "ok" and g.output_words < g.target_words * SHORT_RATIO)
