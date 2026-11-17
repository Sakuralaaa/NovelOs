"""v0.12 生成档案 + 成本预算接口。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlmodel import Session, select

from app.api.schemas import iso, job_out
from app.db import get_session, kv_set, session_scope
from app.jobs.manager import JobContext, submit
from app.llm import archive
from app.models.tables import Book, Generation

router = APIRouter(prefix="/api")

KIND_LABEL = {
    "chapter_write": "写章", "chapter_rewrite": "改写", "chapter_refine": "精修", "chapter_patch": "定点修", "chapter_review": "审稿",
    "polish_voice": "语感重塑", "humanize": "去 AI 味", "thicken": "描写增厚", "outline_generate": "生成大纲", "outline_expand": "展开大纲",
    "outline_node": "改大纲", "bible_generate": "生成设定", "bible_propose": "AI 改设定", "card_suggest": "AI 改设定卡", "field_ai": "字段 AI",
    "character_soul": "灵魂五维", "idea_generate": "生成选题", "package": "包装", "cover": "封面", "agent_run": "Agent", "agent": "Agent",
    "followup": "追问", "generation_followup": "追问", "trend_report": "风向标日报", "teardown": "拆书", "image": "生图",
    "writing_chapter": "写章", "writing_scene": "写场景", "chapter_state": "抽状态账本", "pairwise": "候选比较", "scene_plan": "排段落",
    "reader": "读者审读", "review": "审稿",
}


def gen_out(g: Generation, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": g.id, "book_id": g.book_id, "job_id": g.job_id, "kind": g.kind, "kind_label": KIND_LABEL.get(g.kind, KIND_LABEL.get(g.task, g.kind)),
        "task": g.task, "route": g.route, "model": g.model, "status": g.status, "error": g.error,
        "output_words": g.output_words, "target_words": g.target_words, "short": archive.is_short(g),
        "in_tokens": g.in_tokens, "out_tokens": g.out_tokens, "cost_cny": round(g.cost_cny or 0, 4), "ms": g.ms,
        "starred": g.starred, "parent_id": g.parent_id, "note": g.note, "created_at": iso(g.created_at),
        "preview": (g.output or "")[:160],
    }
    if full:
        out["prompt"] = g.prompt
        out["output"] = g.output
    return out


@router.get("/generations")
def list_generations(book_id: int | None = None, kind: str = "", status: str = "", q: str = "", starred: bool = False,
                     days: int = Query(0, ge=0, le=3650), limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     s: Session = Depends(get_session)) -> dict[str, Any]:
    conds: list[Any] = []
    if book_id is not None:
        conds.append(Generation.book_id == book_id)
    if kind:
        conds.append(Generation.kind == kind)
    if status:
        conds.append(Generation.status == status)
    if starred:
        conds.append(Generation.starred == True)  # noqa: E712
    if days:
        conds.append(Generation.created_at >= datetime.now(timezone.utc) - timedelta(days=days))
    if q.strip():
        like = f"%{q.strip()}%"
        conds.append(or_(Generation.output.like(like), Generation.prompt.like(like), Generation.note.like(like)))  # type: ignore[attr-defined]
    base = select(Generation).where(*conds)
    total = s.exec(select(func.count()).select_from(Generation).where(*conds)).one()
    rows = s.exec(base.order_by(Generation.id.desc()).offset(offset).limit(limit)).all()  # type: ignore[union-attr]
    kinds = s.exec(select(Generation.kind, func.count()).where(*([Generation.book_id == book_id] if book_id is not None else []))
                   .group_by(Generation.kind)).all()
    cost = s.exec(select(func.coalesce(func.sum(Generation.cost_cny), 0.0)).where(*conds)).one()
    return {"items": [gen_out(g) for g in rows], "total": int(total if not isinstance(total, tuple) else total[0]),
            "cost_cny": round(float(cost if not isinstance(cost, tuple) else cost[0]), 4),
            "kinds": [{"kind": k, "label": KIND_LABEL.get(k, k), "count": n} for k, n in kinds]}


def _gen(s: Session, gid: int) -> Generation:
    g = s.get(Generation, gid)
    if g is None:
        raise HTTPException(404, "这条记录不存在")
    return g


@router.get("/generations/{gid}")
def get_generation(gid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    g = _gen(s, gid)
    out = gen_out(g, full=True)
    kids = s.exec(select(Generation).where(Generation.parent_id == gid).order_by(Generation.id)).all()
    out["children"] = [gen_out(k) for k in kids]
    return out


class GenPatch(BaseModel):
    starred: bool | None = None


@router.patch("/generations/{gid}")
def patch_generation(gid: int, body: GenPatch, s: Session = Depends(get_session)) -> dict[str, Any]:
    g = _gen(s, gid)
    if body.starred is not None:
        g.starred = body.starred
    s.add(g)
    s.commit()
    s.refresh(g)
    return gen_out(g)


@router.delete("/generations/{gid}")
def delete_generation(gid: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    g = _gen(s, gid)
    for k in s.exec(select(Generation).where(Generation.parent_id == gid)):
        k.parent_id = None
        s.add(k)
    s.delete(g)
    s.commit()
    return {"ok": True}


class FollowupIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    route: str | None = None


def _followup(gid: int, instruction: str, route: str | None, ctx: JobContext) -> dict[str, Any]:
    from app.llm.gateway import get_gateway

    with session_scope() as s:
        g = s.get(Generation, gid)
        if g is None:
            raise ValueError("这条记录不存在")
        prompt, output, role = g.prompt, g.output, g.route if g.route in ("planner", "writer", "reviewer") else "planner"
    if not (output or "").strip():
        raise ValueError("原记录没有可追问的结果")
    messages = [
        {"role": "system", "content": "你在帮网文作者修改一条 AI 生成结果。按作者的新要求给出修改后的完整结果，格式与原结果一致，不要解释。"},
        {"role": "user", "content": (prompt or "（原要求未保存）")[:4000]},
        {"role": "assistant", "content": output[:16000]},
        {"role": "user", "content": instruction},
    ]
    ctx.progress(20, "按要求重新生成")
    token = archive.set_parent(gid, instruction)
    try:
        out = get_gateway().chat("followup", messages, meta={"output": output, "instruction": instruction}, role=role, route=route)
    finally:
        archive.reset_parent(token)
    with session_scope() as s:
        new = s.exec(select(Generation).where(Generation.parent_id == gid, Generation.status == "ok")
                     .order_by(Generation.id.desc())).first()  # type: ignore[union-attr]
        return {"parent_id": gid, "id": new.id if new else None, "output": out}


@router.post("/generations/{gid}/followup")
async def followup_generation(gid: int, body: FollowupIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    g = _gen(s, gid)
    if not (g.output or "").strip() or g.status != "ok":
        raise HTTPException(400, "只能对成功的结果追问")
    return job_out(submit("generation_followup", lambda ctx: _followup(gid, body.instruction, body.route, ctx), book_id=g.book_id))


# ------------------------------------------------------------------ 预算

class BudgetIn(BaseModel):
    daily_cny: float = Field(default=0, ge=0, le=1_000_000)
    book_cny: float = Field(default=0, ge=0, le=1_000_000)


@router.get("/settings/budget")
def get_budget(book_id: int | None = None, s: Session = Depends(get_session)) -> dict[str, Any]:
    if book_id is not None and s.get(Book, book_id) is None:
        raise HTTPException(404, "书不存在")
    return archive.budget_status(s, book_id)


@router.put("/settings/budget")
def put_budget(body: BudgetIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    kv_set(s, archive.BUDGET_KEY, {"daily_cny": round(body.daily_cny, 2), "book_cny": round(body.book_cny, 2)})
    return archive.budget_status(s)
