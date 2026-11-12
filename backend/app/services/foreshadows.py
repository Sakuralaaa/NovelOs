"""伏笔：手动增删改、AI 规划（预览勾选后加入，可写进对应章细纲）、列出细纲里已经安排但还没入账的伏笔。

伏笔怎么来的（v0.4 起）：
1. 写章时：章细纲的 foreshadow 动作 → 正文末尾 ---CHANGES--- 声明 → 「提交」入账时写进伏笔表（这是底账来源）。
2. 规划时：AI 规划或作者手动添加，状态为 planned（计划中），写进细纲后，到那一章提交时自动转为 planted（已埋）。
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import Chapter, Foreshadow, OutlineNode
from app.services import common
from app.services.changes import match_foreshadow
from app.services.common import NotFound
from app.services.outline import FORESHADOW_TIERS
from app.skills.loader import render, system_prompt

STATUSES = ("planned", "planted", "advancing", "resolved", "dropped")


def last_committed(s: Session, book_id: int) -> int:
    chs = common.committed_chapters(s, book_id)
    return chs[-1].number if chs else 0


def _apply_fields(f: Foreshadow, data: dict[str, Any]) -> None:
    if "desc" in data and data["desc"] is not None:
        d = str(data["desc"]).strip()
        if not d:
            raise ValueError("伏笔内容不能为空")
        f.desc = d[:300]
    if data.get("status") is not None:
        if data["status"] not in STATUSES:
            raise ValueError("状态不合法")
        f.status = data["status"]
    for k in ("planted_ch", "last_ch"):
        if data.get(k) is not None:
            setattr(f, k, max(0, int(data[k])))
    for k in ("resolved_ch", "plan_plant_ch", "plan_resolve_ch"):
        if k in data:
            v = data[k]
            setattr(f, k, None if v in (None, "", 0) else max(1, int(v)))
    if data.get("tier") is not None:
        f.tier = data["tier"] if data["tier"] in FORESHADOW_TIERS else ""
    if data.get("note") is not None:
        f.note = str(data["note"])[:1000]
    # 状态与章号保持一致
    if f.status == "resolved" and not f.resolved_ch:
        f.resolved_ch = max(f.last_ch, f.planted_ch) or None
    if f.status == "resolved" and f.resolved_ch:
        f.last_ch = max(f.last_ch, f.resolved_ch)
    if f.status in ("planted", "advancing") and f.resolved_ch and data.get("status") is not None:
        f.resolved_ch = None
    if f.status != "planned" and f.planted_ch and f.last_ch < f.planted_ch:
        f.last_ch = f.planted_ch


def create(book_id: int, data: dict[str, Any]) -> Foreshadow:
    with session_scope() as s:
        common.get_book(s, book_id)
        f = Foreshadow(book_id=book_id, desc="-", status="planned", source=str(data.get("source") or "manual"))
        _apply_fields(f, {**data, "status": data.get("status") or ("planted" if data.get("planted_ch") else "planned")})
        if f.status == "planned":
            f.planted_ch = f.last_ch = 0
        s.add(f)
        s.commit()
        s.refresh(f)
        return f


def update(fid: int, data: dict[str, Any]) -> Foreshadow:
    with session_scope() as s:
        f = s.get(Foreshadow, fid)
        if f is None:
            raise NotFound("伏笔不存在")
        _apply_fields(f, data)
        s.add(f)
        s.commit()
        s.refresh(f)
        return f


def delete(fid: int) -> None:
    with session_scope() as s:
        f = s.get(Foreshadow, fid)
        if f is None:
            raise NotFound("伏笔不存在")
        s.delete(f)
        s.commit()


def outline_planned(s: Session, book_id: int) -> list[dict[str, Any]]:
    """章细纲里安排了、但伏笔表里还没有的“埋下”动作（章节还没写或还没提交）。"""
    known = {f.id or 0: f.desc for f in s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id))}
    out = []
    nodes = s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter").order_by(OutlineNode.order)).all()
    for n in nodes:
        if n.status == "written":
            continue
        for a in (n.beats or {}).get("foreshadow") or []:
            if not isinstance(a, dict) or a.get("action") != "plant" or not str(a.get("desc") or "").strip():
                continue
            if match_foreshadow(str(a["desc"]), known) is not None:
                continue
            out.append({"desc": str(a["desc"]), "chapter": n.order, "node_id": n.id, "tier": a.get("tier") or ""})
    return out


def _outline_text(s: Session, book_id: int) -> str:
    lines = []
    for n in sorted(common.outline_nodes(s, book_id), key=lambda n: (n.level != "book", n.level != "volume", n.level != "arc", n.order)):
        if n.level == "chapter":
            b = n.beats or {}
            fs = "；".join(f"{a.get('action')}:{a.get('desc')}" for a in b.get("foreshadow") or [] if isinstance(a, dict))
            lines.append(f"第{n.order}章《{n.title}》{b.get('goal', '')}" + (f"（伏笔 {fs}）" if fs else ""))
        else:
            lines.append(f"[{n.level}] {n.title}：{n.summary}")
    return "\n".join(lines[:120]) or "（还没有大纲）"


def plan(book_id: int, instruction: str, route: str | None, count: int, ctx: JobContext) -> dict[str, Any]:
    """AI 从大纲 / 设定规划伏笔，结果只是建议，作者勾选后再加入。"""
    from app.services import tropes

    count = max(1, min(10, int(count or 5)))
    with session_scope() as s:
        book = common.get_book(s, book_id)
        meta = common.kit_meta(s, book)
        cur = last_committed(s, book_id)
        existing = list(s.exec(select(Foreshadow).where(Foreshadow.book_id == book_id)))
        tl = tropes.tropes_for(s, book)
        user = render("foreshadow_plan", book_context=common.book_context(s, book), outline=_outline_text(s, book_id),
                      existing="\n".join(f"- {f.desc}（{f.status}）" for f in existing) or "（无）",
                      current=cur, next=cur + 1, count=count,
                      instruction=instruction.strip() or "长短线搭配，前十章至少埋一条长线。")
        user += tropes.prompt_block(tl, instruction)
        max_ch = max([n.order for n in common.outline_nodes(s, book_id) if n.level == "chapter"] or [0])
    ctx.progress(25, "AI 规划伏笔")
    data = get_gateway().chat_json("foreshadow_plan", system_prompt("foreshadow_plan"), user,
                                   meta={**meta, "count": count, "next": cur + 1, "instruction": instruction}, route=route)
    raw = data.get("foreshadows") if isinstance(data, dict) else data
    known = {f.id or 0: f.desc for f in existing}
    items = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict) or not str(it.get("desc") or "").strip():
            continue
        desc = str(it["desc"]).strip()[:300]
        dup = match_foreshadow(desc, known)

        def _ch(v: Any) -> int | None:
            try:
                n = int(v)
            except (TypeError, ValueError):
                return None
            return n if n > 0 else None

        p = _ch(it.get("plant_ch"))
        if p is not None and p <= cur:
            p = cur + 1  # 已经提交的章不能再埋
        r = _ch(it.get("resolve_ch"))
        if r is not None and p is not None and r <= p:
            r = p + 1
        items.append({"desc": desc, "tier": it.get("tier") if it.get("tier") in FORESHADOW_TIERS else "",
                      "plant_ch": p, "resolve_ch": r, "note": str(it.get("note") or "")[:300],
                      "related": [str(x) for x in (it.get("related") or [])][:6] if isinstance(it.get("related"), list) else [],
                      "duplicate_of": dup, "in_outline": p is not None and p <= max_ch})
    if not items:
        raise ValueError("模型没有给出伏笔")
    return {"book_id": book_id, "items": items[:count], "current": cur, "outline_max": max_ch}


def add_batch(book_id: int, items: list[dict[str, Any]], attach: bool) -> dict[str, Any]:
    """把勾选的伏笔加入伏笔池（计划中）；attach=True 时同时写进对应章细纲（埋下/回收动作）。"""
    created, attached = 0, 0
    with session_scope() as s:
        common.get_book(s, book_id)
        nodes = {n.order: n for n in s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id, OutlineNode.level == "chapter"))}
        cur = last_committed(s, book_id)
        for it in items:
            desc = str(it.get("desc") or "").strip()
            if not desc:
                continue
            f = Foreshadow(book_id=book_id, desc=desc[:300], status="planned", planted_ch=0, last_ch=0,
                           tier=it.get("tier") if it.get("tier") in FORESHADOW_TIERS else "",
                           plan_plant_ch=int(it["plant_ch"]) if str(it.get("plant_ch") or "").isdigit() and int(it["plant_ch"]) > 0 else None,
                           plan_resolve_ch=int(it["resolve_ch"]) if str(it.get("resolve_ch") or "").isdigit() and int(it["resolve_ch"]) > 0 else None,
                           note=str(it.get("note") or "")[:1000], source=str(it.get("source") or "ai"))
            s.add(f)
            created += 1
            if not attach:
                continue
            for action, ch in (("plant", f.plan_plant_ch), ("resolve", f.plan_resolve_ch)):
                node = nodes.get(ch) if ch else None
                if node is None or node.status == "written" or ch <= cur:
                    continue
                beats = dict(node.beats or {})
                fs = list(beats.get("foreshadow") or [])
                if any(isinstance(a, dict) and a.get("action") == action and str(a.get("desc")) == f.desc for a in fs):
                    continue
                entry: dict[str, Any] = {"action": action, "id": None, "desc": f.desc}
                if action == "plant" and f.tier:
                    entry["tier"] = f.tier
                fs.append(entry)
                beats["foreshadow"] = fs
                node.beats = beats
                s.add(node)
                attached += 1
        s.commit()
    return {"created": created, "attached": attached}


def chapter_numbers(s: Session, book_id: int) -> dict[int, int]:
    return {c.number: c.id or 0 for c in s.exec(select(Chapter).where(Chapter.book_id == book_id))}

