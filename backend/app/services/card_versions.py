"""v0.12 设定卡锁定 + 单卡版本。

- 锁定：任何 AI 生成 / 同步 / 批量改 / Agent 改动都跳过锁定卡；作者手动编辑不受限。
- 版本：每次写卡前把旧内容存进 Card.versions（最多 MAX_CARD_VERSIONS 条），可逐条查看与回滚；回滚本身也会先存一版。
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models.tables import Card, utcnow
from app.services.common import Conflict, NotFound

MAX_CARD_VERSIONS = 20
VERSION_KEYS = ("type", "name", "summary", "data", "known_by", "status", "ref_enabled", "soul")
LOCKED_MSG = "这张设定已锁定，AI 不能修改；先解锁再让 AI 改"


def state_of(c: Card) -> dict[str, Any]:
    return {"type": c.type, "name": c.name, "summary": c.summary or "", "data": dict(c.data or {}),
            "known_by": list(c.known_by or []), "status": c.status or "active",
            "ref_enabled": bool(c.ref_enabled) if c.ref_enabled is not None else True,
            "soul": dict(c.soul) if c.soul else None}


def push(c: Card, label: str, before: dict[str, Any] | None = None) -> bool:
    """存一版旧内容。before 不传时取当前内容；与最近一版相同则不重复存。"""
    st = before if before is not None else state_of(c)
    vs = list(c.versions or [])
    if vs and {k: vs[-1].get(k) for k in VERSION_KEYS} == {k: st.get(k) for k in VERSION_KEYS}:
        return False
    c.versions = [*vs, {**st, "label": (label or "修改")[:60], "at": utcnow().isoformat()}][-MAX_CARD_VERSIONS:]
    return True


def changed(before: dict[str, Any], c: Card) -> bool:
    return before != state_of(c)


def ensure_unlocked(c: Card) -> None:
    if getattr(c, "locked", False):
        raise Conflict(LOCKED_MSG)


def list_versions(c: Card) -> list[dict[str, Any]]:
    """最近的在前；n 为在 versions 里的下标（回滚用）。"""
    vs = list(c.versions or [])
    return [{"n": i, **v} for i, v in reversed(list(enumerate(vs)))]


def restore(s: Session, c: Card, n: int) -> Card:
    vs = list(c.versions or [])
    if not (0 <= n < len(vs)):
        raise NotFound("这个版本不存在")
    v = vs[n]
    push(c, f"回滚到「{v.get('label') or '旧版本'}」之前")
    c.type = v.get("type") or c.type
    c.name = (v.get("name") or c.name)[:40]
    c.summary = v.get("summary") or ""
    c.data = dict(v.get("data") or {})
    c.known_by = list(v.get("known_by") or [])
    c.status = v.get("status") if v.get("status") in ("active", "deprecated") else "active"
    c.ref_enabled = bool(v.get("ref_enabled", True))
    c.soul = dict(v["soul"]) if isinstance(v.get("soul"), dict) else None
    c.updated_at = utcnow()
    s.add(c)
    return c
