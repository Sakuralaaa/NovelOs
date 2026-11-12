"""通用、任务、模型渠道、雷达。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app import __version__
from app.api.schemas import (
    ChannelIn, ChannelUpdate, ModelFetchIn, RadarConfigIn, RoutingIn, TropesIn, WritingSettingsIn, channel_out, job_out, rank_item_out,
    snapshot_out,
)
from app.db import get_session, kv_set, session_scope
from app.jobs.manager import submit
from app.llm.crypto import decrypt, encrypt
from app.llm.gateway import (
    IMAGE_MODE_KEY, ROLES, ROUTING_KEY, LLMError, LLMGateway, get_image_mode, get_routing, is_mock_mode,
)
from app.models.tables import Channel, Job, RadarSnapshot, TokenUsage
from app.radar import service as radar
from app.services.research import recent_logs
from app.services.writing import WRITING_SETTINGS_KEY, writing_settings

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


# ------------------------------------------------------------------ jobs

@router.get("/jobs")
def list_jobs(book_id: int | None = None, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    q = select(Job)
    if book_id is not None:
        q = q.where(Job.book_id == book_id)
    return [job_out(j) for j in s.exec(q.order_by(Job.id.desc()).limit(50))]  # type: ignore[union-attr]


@router.get("/jobs/{job_id}")
def get_job(job_id: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    j = s.get(Job, job_id)
    if j is None:
        raise HTTPException(404, "任务不存在")
    return job_out(j)


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: int) -> StreamingResponse:
    async def gen():  # type: ignore[no-untyped-def]
        last = None
        while True:
            with session_scope() as s:
                j = s.get(Job, job_id)
                data = job_out(j) if j else None
            if data is None:
                yield "event: error\ndata: {\"detail\":\"任务不存在\"}\n\n"
                return
            payload = json.dumps(data, ensure_ascii=False)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if data["status"] in ("succeeded", "failed"):
                return
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ------------------------------------------------------------------ settings

@router.get("/settings/channels")
def list_channels(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [channel_out(c) for c in s.exec(select(Channel).order_by(Channel.id))]


@router.post("/settings/channels")
def create_channel(body: ChannelIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    c = Channel(name=body.name, base_url=body.base_url.strip(), api_key_enc=encrypt(body.api_key.strip()),
                models=[m.strip() for m in body.models if m.strip()], enabled=body.enabled, api_format=body.api_format)
    s.add(c)
    s.commit()
    s.refresh(c)
    return channel_out(c)


@router.put("/settings/channels/{cid}")
def update_channel(cid: int, body: ChannelUpdate, s: Session = Depends(get_session)) -> dict[str, Any]:
    c = s.get(Channel, cid)
    if c is None:
        raise HTTPException(404, "渠道不存在")
    if body.name is not None:
        c.name = body.name
    if body.base_url is not None:
        c.base_url = body.base_url.strip()
    if body.api_key:  # 空字符串 / null 表示不修改
        c.api_key_enc = encrypt(body.api_key.strip())
    if body.models is not None:
        c.models = [m.strip() for m in body.models if m.strip()]
    if body.enabled is not None:
        c.enabled = body.enabled
    if body.api_format is not None:
        c.api_format = body.api_format
    s.add(c)
    s.commit()
    s.refresh(c)
    return channel_out(c)


@router.delete("/settings/channels/{cid}")
def delete_channel(cid: int, s: Session = Depends(get_session)) -> dict[str, bool]:
    c = s.get(Channel, cid)
    if c is None:
        raise HTTPException(404, "渠道不存在")
    s.delete(c)
    routing = get_routing(s)
    changed = {k: (None if v and v.split(":", 1)[0] == str(cid) else v) for k, v in routing.items()}
    s.commit()
    kv_set(s, ROUTING_KEY, changed)
    return {"ok": True}


@router.post("/settings/channels/{cid}/test")
async def test_channel(cid: int) -> dict[str, Any]:
    with session_scope() as s:
        c = s.get(Channel, cid)
        if c is None:
            raise HTTPException(404, "渠道不存在")
        try:
            key = decrypt(c.api_key_enc)
        except ValueError as e:
            return {"ok": False, "latency_ms": 0, "error": str(e)}
        base, models, fmt = c.base_url, list(c.models or []), c.api_format or "openai"
    return await asyncio.to_thread(LLMGateway.test_channel, base, key, models, fmt)


@router.post("/settings/models/fetch")
async def fetch_models(body: ModelFetchIn) -> dict[str, Any]:
    key = body.api_key.strip()
    fmt = body.api_format
    if not key and body.channel_id:
        with session_scope() as s:
            c = s.get(Channel, body.channel_id)
            if c is None:
                raise HTTPException(404, "渠道不存在")
            try:
                key = decrypt(c.api_key_enc)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
    base = body.base_url.strip().rstrip("/")
    try:
        models = await asyncio.to_thread(LLMGateway.list_models, base, key, fmt)
    except LLMError as e:
        raise HTTPException(400, f"拉取失败：{e}") from e
    return {"models": models}


@router.get("/research/logs")
def research_logs(book_id: int | None = None, limit: int = Query(30, ge=1, le=200)) -> list[dict[str, Any]]:
    return recent_logs(book_id, limit)


@router.get("/settings/routing")
def routing_get(s: Session = Depends(get_session)) -> dict[str, str | None]:
    return {**get_routing(s), "image_mode": get_image_mode(s)}


@router.put("/settings/routing")
def routing_put(body: RoutingIn, s: Session = Depends(get_session)) -> dict[str, str | None]:
    data = body.model_dump()
    image_mode = data.pop("image_mode", None)
    for role, v in data.items():
        if v is None or v == "":
            data[role] = None
            continue
        if ":" not in v:
            raise HTTPException(400, f"{role} 路由格式应为 \"channel_id:model\"")
        cid = v.split(":", 1)[0]
        if not cid.isdigit() or s.get(Channel, int(cid)) is None:
            raise HTTPException(400, f"{role} 路由引用的渠道 {cid} 不存在")
    kv_set(s, ROUTING_KEY, {r: data.get(r) for r in ROLES})
    if image_mode:
        kv_set(s, IMAGE_MODE_KEY, image_mode)
    return {**get_routing(s), "image_mode": get_image_mode(s)}


@router.get("/settings/status")
def settings_status(s: Session = Depends(get_session)) -> dict[str, bool]:
    return {"mock_mode": is_mock_mode(s)}


@router.get("/settings/writing")
def writing_get(s: Session = Depends(get_session)) -> dict[str, Any]:
    """写作默认设置（合约增补“自动采纳最高分”的落点）：auto_adopt_best / auto_commit / default_variants。"""
    return writing_settings(s)


@router.put("/settings/writing")
def writing_put(body: WritingSettingsIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    cur = writing_settings(s)
    cur.update({k: v for k, v in body.model_dump().items() if v is not None})
    kv_set(s, WRITING_SETTINGS_KEY, cur)
    return writing_settings(s)


@router.get("/settings/tropes")
def tropes_get(s: Session = Depends(get_session)) -> dict[str, Any]:
    """全局禁用套路列表（生成选题、设定等时注入提示词，生成结果命中关键词时标黄提醒）。"""
    from app.services import tropes

    return {"banned": tropes.global_tropes(s), "defaults": tropes.DEFAULT_TROPES}


@router.put("/settings/tropes")
def tropes_put(body: TropesIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from app.services import tropes

    kv_set(s, tropes.TROPES_KEY, {"banned": tropes.clean([t.model_dump() for t in body.banned])})
    return {"banned": tropes.global_tropes(s), "defaults": tropes.DEFAULT_TROPES}


@router.get("/settings/usage")
def usage(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """token 用量汇总（按渠道/模型/角色）。"""
    agg: dict[tuple[Any, ...], dict[str, Any]] = {}
    for u in s.exec(select(TokenUsage)):
        k = (u.channel_id, u.model, u.role)
        a = agg.setdefault(k, {"channel_id": u.channel_id, "model": u.model, "role": u.role, "calls": 0,
                               "prompt_tokens": 0, "completion_tokens": 0})
        a["calls"] += 1
        a["prompt_tokens"] += u.prompt_tokens
        a["completion_tokens"] += u.completion_tokens
    return list(agg.values())


# ------------------------------------------------------------------ radar

@router.post("/radar/refresh")
async def radar_refresh() -> dict[str, Any]:
    return job_out(submit("radar_refresh", radar.refresh))


@router.get("/radar/snapshots")
def radar_snapshots(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [snapshot_out(x) for x in s.exec(select(RadarSnapshot).order_by(RadarSnapshot.id.desc()).limit(60))]  # type: ignore[union-attr]


@router.get("/radar/latest")
def radar_latest(
    gender: str | None = Query(None), category: str | None = Query(None), s: Session = Depends(get_session)
) -> dict[str, Any]:
    snap = radar.latest_snapshot(s)
    if snap is None:
        return {"snapshot": None, "items": []}
    items = radar.snapshot_items(s, snap.id or 0, gender or None, category or None)
    return {"snapshot": snapshot_out(snap), "items": [rank_item_out(i) for i in items]}


@router.get("/radar/trends")
def radar_trends(gender: str | None = Query(None), s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return radar.compute_trends(s, gender or None)


@router.get("/radar/config")
def radar_config_get(s: Session = Depends(get_session)) -> dict[str, Any]:
    return radar.get_config(s)


@router.put("/radar/config")
def radar_config_put(body: RadarConfigIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    return radar.set_config(s, body.enabled, body.daily_hour)
