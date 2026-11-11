"""雷达：刷新快照、最新榜单、按分类聚合热度趋势、配置与每日调度。"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.db import kv_get, kv_set, session_scope
from app.jobs.manager import JobContext, submit
from app.models.tables import RadarSnapshot, RankItem
from app.radar import fanqie
from app.radar.mock_data import mock_items_50

log = logging.getLogger("novelos.radar")
CONFIG_KEY = "radar_config"
DEFAULT_CONFIG = {"enabled": False, "daily_hour": 8}
TZ = ZoneInfo("Asia/Shanghai")


def get_config(s: Session) -> dict[str, Any]:
    return {**DEFAULT_CONFIG, **(kv_get(s, CONFIG_KEY, {}) or {})}


def set_config(s: Session, enabled: bool, daily_hour: int) -> dict[str, Any]:
    cfg = {"enabled": bool(enabled), "daily_hour": max(0, min(23, int(daily_hour)))}
    kv_set(s, CONFIG_KEY, cfg)
    return cfg


def refresh(ctx: JobContext) -> dict[str, Any]:
    with session_scope() as s:
        cfg = get_config(s)
    source, fallback_reason = "mock", None
    if cfg["enabled"]:
        ctx.progress(10, "请求番茄 App 榜单（请求间隔 ≥1s）")
        try:
            items = fanqie.fetch_rank_lists()
            source = "app"
        except Exception as e:  # noqa: BLE001
            log.warning("榜单抓取失败，回退 mock：%s", e)
            fallback_reason = f"抓取失败，已回退 mock：{e}"
            items = mock_items_50()
    else:
        items = mock_items_50()
        fallback_reason = "雷达未开启，使用 mock 数据"
    ctx.progress(80, "保存快照")
    with session_scope() as s:
        snap = RadarSnapshot(source=source, items_count=len(items))
        s.add(snap)
        s.flush()
        for it in items:
            s.add(RankItem(snapshot_id=snap.id or 0, **{k: it[k] for k in (
                "book_id_ext", "title", "author", "category", "rank", "read_count", "word_count", "abstract", "tags", "gender")}))
        s.commit()
        sid = snap.id
    return {"snapshot_id": sid, "source": source, "items": len(items), "note": fallback_reason}


def latest_snapshot(s: Session, offset: int = 0) -> RadarSnapshot | None:
    return s.exec(select(RadarSnapshot).order_by(RadarSnapshot.id.desc()).offset(offset)).first()  # type: ignore[union-attr]


def snapshot_items(s: Session, snapshot_id: int, gender: str | None = None, category: str | None = None) -> list[RankItem]:
    q = select(RankItem).where(RankItem.snapshot_id == snapshot_id)
    if gender:
        q = q.where(RankItem.gender == gender)
    if category:
        q = q.where(RankItem.category == category)
    return list(s.exec(q.order_by(RankItem.gender, RankItem.rank)))


def _items_for_trends(s: Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snap = latest_snapshot(s)
    if snap is None:
        return mock_items_50(), []
    cur = [i.model_dump() for i in snapshot_items(s, snap.id or 0)]
    prev_snap = latest_snapshot(s, 1)
    prev = [i.model_dump() for i in snapshot_items(s, prev_snap.id or 0)] if prev_snap else []
    return cur, prev


def compute_trends(s: Session, gender: str | None = None) -> list[dict[str, Any]]:
    """热度 = Σ(排名权重 × log 在读)，排名权重 = 1 / sqrt(rank)；rising = 名次上升或新上榜的书数。"""
    cur, prev = _items_for_trends(s)
    prev_rank = {(p["gender"], p["book_id_ext"]): p["rank"] for p in prev}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in cur:
        if gender and it["gender"] != gender:
            continue
        groups[it["category"] or "其他"].append(it)
    out: list[dict[str, Any]] = []
    for cat, items in groups.items():
        heat = sum((1 / math.sqrt(max(1, i["rank"]))) * math.log10(max(10, i["read_count"])) for i in items)
        rising = 0
        if prev:
            for i in items:
                pr = prev_rank.get((i["gender"], i["book_id_ext"]))
                if pr is None or pr > i["rank"]:
                    rising += 1
        items.sort(key=lambda i: i["rank"])
        out.append({"category": cat, "heat": round(heat * 10, 1), "books": len(items), "rising": rising,
                    "sample_titles": [i["title"] for i in items[:3]]})
    out.sort(key=lambda t: -t["heat"])
    return out


# ---------------------------------------------------------------- 每日调度

async def daily_scheduler(stop: asyncio.Event) -> None:
    """简单 asyncio 调度：每分钟检查一次，开启时在 daily_hour（北京时间）当天首次检查时刷新。"""
    last_day: str | None = None
    while not stop.is_set():
        try:
            with session_scope() as s:
                cfg = get_config(s)
                snap = latest_snapshot(s)
            now = datetime.now(TZ)
            today = now.date().isoformat()
            taken_today = snap is not None and (snap.taken_at if snap.taken_at.tzinfo else snap.taken_at.replace(tzinfo=ZoneInfo("UTC"))).astimezone(TZ).date().isoformat() == today
            if cfg["enabled"] and now.hour >= cfg["daily_hour"] and last_day != today and not taken_today:
                last_day = today
                submit("radar_refresh", refresh)
        except Exception:  # noqa: BLE001
            log.exception("雷达调度异常")
        try:
            await asyncio.wait_for(stop.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
