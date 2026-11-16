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
from app.radar import fanqie, fanqie_web
from app.radar.mock_data import mock_items_50, mock_new_items

log = logging.getLogger("novelos.radar")
CONFIG_KEY = "radar_config"
DEFAULT_CONFIG = {"enabled": False, "daily_hour": 8, "auto_report": False}
BOARDS = ("read", "new")
TZ = ZoneInfo("Asia/Shanghai")


def get_config(s: Session) -> dict[str, Any]:
    return {**DEFAULT_CONFIG, **(kv_get(s, CONFIG_KEY, {}) or {})}


def set_config(s: Session, enabled: bool, daily_hour: int, auto_report: bool | None = None) -> dict[str, Any]:
    """auto_report=None 表示不改（兼容只传 enabled/daily_hour 的旧前端）。"""
    cur = get_config(s)
    cfg = {"enabled": bool(enabled), "daily_hour": max(0, min(23, int(daily_hour))),
           "auto_report": bool(cur.get("auto_report")) if auto_report is None else bool(auto_report)}
    kv_set(s, CONFIG_KEY, cfg)
    return cfg


# v0.9.2：日报配置单独存（GET/PUT /api/radar/report/config），不改 /api/radar/config 的返回形状
REPORT_CONFIG_KEY = "radar_report_config"


def get_report_config(s: Session) -> dict[str, Any]:
    from app.config import get_settings

    st = get_settings()
    cfg = {"radar_report_top_n": max(3, min(50, int(st.radar_report_top_n))),
           "radar_report_auto_scopes": list(st.radar_report_auto_scopes or ["overall"])}
    return {**cfg, **(kv_get(s, REPORT_CONFIG_KEY, {}) or {})}


def clean_auto_scopes(scopes: list[str]) -> list[str]:
    """校验自动日报 scope 列表（格式不对抛 ValueError → 400），去重保序，最多 8 个。"""
    from app.radar import report as trend_report

    out: list[str] = []
    for sc in scopes:
        sc = str(sc or "").strip()
        if not sc:
            continue
        trend_report.scope_info(sc)
        if sc not in out:
            out.append(sc)
    if len(out) > 8:
        raise ValueError("自动日报最多 8 个 scope")
    return out


def set_report_config(s: Session, top_n: int | None = None, auto_scopes: list[str] | None = None) -> dict[str, Any]:
    """不传的项不改。"""
    stored = dict(kv_get(s, REPORT_CONFIG_KEY, {}) or {})
    if top_n is not None:
        stored["radar_report_top_n"] = max(3, min(50, int(top_n)))
    if auto_scopes is not None:
        stored["radar_report_auto_scopes"] = clean_auto_scopes(auto_scopes)
    kv_set(s, REPORT_CONFIG_KEY, stored)
    return get_report_config(s)


def board_of(it: Any) -> str:
    """旧数据没有 board（或迁移补成空串）一律当阅读榜。"""
    b = it.get("board") if isinstance(it, dict) else getattr(it, "board", None)
    return b if b in BOARDS else "read"


def snapshot_boards(s: Session, snapshot_id: int) -> set[str]:
    rows = s.exec(select(RankItem.board).where(RankItem.snapshot_id == snapshot_id).distinct())
    return {b if b in BOARDS else "read" for b in rows}


def refresh(ctx: JobContext) -> dict[str, Any]:
    """抓取顺序：网页阅读榜 + 新书榜（真实、分题材）→ App 推荐榜（旧接口）→ 示例数据。
    同一 rankVersion 已入库且榜单类型没有变多时不再新建快照，避免“越刷越变”。
    v0.9：配置 auto_report 打开时，新快照入库后提交一份风向标日报任务（radar_report）。"""
    with session_scope() as s:
        cfg = get_config(s)
        last = latest_snapshot(s)
        last_boards = snapshot_boards(s, last.id or 0) if last is not None else set()
    source, version, note = "mock", "", None
    items: list[dict[str, Any]] = []
    if cfg["enabled"]:
        ctx.progress(5, "读取番茄阅读榜与新书榜")
        try:
            items, version = fanqie_web.fetch_rank_lists(progress=ctx.progress)
            source = "web"
        except Exception as e:  # noqa: BLE001
            log.warning("网页榜单抓取失败，尝试 App 接口：%s", e)
            try:
                items = fanqie.fetch_rank_lists()
                source = "app"
                note = f"网页榜单不可用（{e}），已改用 App 榜单"
            except Exception as e2:  # noqa: BLE001
                log.warning("App 榜单也失败，回退示例数据：%s", e2)
                note = f"抓取失败，已回退示例数据：{e2}"
    else:
        note = "雷达未开启，使用示例数据"
    if not items:
        source, items = "mock", mock_items_50() + mock_new_items()
        version = f"mock-{datetime.now(TZ).date().isoformat()}"
    for it in items:
        it["board"] = board_of(it)

    new_boards = {it["board"] for it in items}
    if (last is not None and version and last.version == version and last.source == source
            and new_boards <= last_boards):
        out = {"snapshot_id": last.id, "source": source, "items": last.items_count, "unchanged": True,
               "note": note or "榜单今天还没更新，沿用当前数据"}
        _maybe_auto_report(cfg, last.id or 0, out)
        _maybe_cache_covers(items)  # 沿用旧快照时也补缓存还没下载的封面（已缓存的会跳过）
        return out

    ctx.progress(85, "保存快照")
    with session_scope() as s:
        snap = RadarSnapshot(source=source, items_count=len(items), version=version)
        s.add(snap)
        s.flush()
        for it in items:
            s.add(RankItem(snapshot_id=snap.id or 0, rank_diff=int(it.get("rank_diff") or 0), board=it["board"], **{k: it[k] for k in (
                "book_id_ext", "title", "author", "category", "rank", "read_count", "word_count", "abstract", "tags", "gender")},
                **_shelf_fields(it)))
        s.commit()
        sid = snap.id
    out = {"snapshot_id": sid, "source": source, "items": len(items), "note": note,
           "boards": {b: sum(1 for it in items if it["board"] == b) for b in BOARDS}}
    _maybe_auto_report(cfg, sid or 0, out)
    _maybe_cache_covers(items)
    return out


def _shelf_fields(it: dict[str, Any]) -> dict[str, Any]:
    """v0.9.1 书架字段（App 榜单 / 旧格式条目没有这些键时取空值）。"""
    upd = it.get("last_update_at")
    return {"cover_url": str(it.get("cover_url") or ""), "first_chapter_id": str(it.get("first_chapter_id") or ""),
            "last_chapter_id": str(it.get("last_chapter_id") or ""), "last_chapter_title": str(it.get("last_chapter_title") or "")[:120],
            "last_update_at": upd if isinstance(upd, datetime) else None, "chapter_count": int(it.get("chapter_count") or 0)}


def _maybe_cache_covers(items: list[dict[str, Any]]) -> None:
    """抓榜完成后后台预缓存封面（配置 radar_cache_covers，默认开；只处理有 cover_url 的条目，失败忽略）。"""
    from app.config import get_settings
    from app.radar import covers

    if not get_settings().radar_cache_covers:
        return
    todo = {str(it["book_id_ext"]): str(it.get("cover_url") or "") for it in items if it.get("cover_url")}
    if todo:
        covers.prefetch_async(todo)


def _maybe_auto_report(cfg: dict[str, Any], snapshot_id: int, out: dict[str, Any]) -> None:
    """开启自动日报时，对 radar_report_auto_scopes（默认只有 overall）里这份快照还没有日报的 scope 各提交一个 radar_report 任务。
    job id 写进刷新结果：report_job_ids {scope: id}；overall 的另写 report_job_id（兼容 v0.9）。"""
    if not cfg.get("auto_report") or not snapshot_id:
        return
    from app.radar import report as trend_report

    try:
        with session_scope() as s:
            scopes = get_report_config(s).get("radar_report_auto_scopes") or ["overall"]
    except Exception:  # noqa: BLE001
        scopes = ["overall"]
    ids: dict[str, int] = {}
    for scope in scopes:
        try:
            with session_scope() as s:
                if trend_report.latest_report(s, scope, snapshot_id=snapshot_id) is not None:
                    continue
            trend_report.check_can_generate(scope)
            ids[scope] = trend_report.submit_report(scope).id
        except Exception as e:  # noqa: BLE001  日报失败不影响刷新本身
            log.warning("自动提交风向标日报（%s）失败：%s", scope, e)
    if ids:
        out["report_job_ids"] = ids
    if "overall" in ids:
        out["report_job_id"] = ids["overall"]


def latest_snapshot(s: Session, offset: int = 0) -> RadarSnapshot | None:
    return s.exec(select(RadarSnapshot).order_by(RadarSnapshot.id.desc()).offset(offset)).first()  # type: ignore[union-attr]


def snapshot_items(s: Session, snapshot_id: int, gender: str | None = None, category: str | None = None, dedupe: bool = True,
                   board: str | None = None) -> list[RankItem]:
    q = select(RankItem).where(RankItem.snapshot_id == snapshot_id)
    if gender:
        q = q.where(RankItem.gender == gender)
    if category:
        q = q.where(RankItem.category == category)
    if board == "read":
        q = q.where(RankItem.board.in_(["read", ""]))  # type: ignore[attr-defined]  旧数据视为阅读榜
    elif board:
        q = q.where(RankItem.board == board)
    if category or not dedupe:
        return list(s.exec(q.order_by(RankItem.gender, RankItem.board, RankItem.rank)))
    # “全部”视图：同一本书可能上多个题材榜，去重后按在读人数排
    rows = list(s.exec(q.order_by(RankItem.read_count.desc(), RankItem.rank)))  # type: ignore[attr-defined]
    seen: set[tuple[str, str, str]] = set()
    out = []
    for r in rows:
        key = (r.gender, board_of(r), r.book_id_ext)
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _items_for_trends(s: Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    snap = latest_snapshot(s)
    if snap is None:
        return mock_items_50() + mock_new_items(), []
    cur = [i.model_dump() for i in snapshot_items(s, snap.id or 0, dedupe=False)]
    prev_snap = latest_snapshot(s, 1)
    prev = [i.model_dump() for i in snapshot_items(s, prev_snap.id or 0, dedupe=False)] if prev_snap else []
    for it in (*cur, *prev):
        it["board"] = board_of(it)
    return cur, prev


def rank_key(it: dict[str, Any]) -> tuple[str, str, str, str]:
    """同一本书在同一类榜、同一题材里的身份（跨快照比名次用）。旧数据 board 视为 read。"""
    return (it["gender"], board_of(it), it.get("category") or "", it["book_id_ext"])


def compute_trends(s: Session, gender: str | None = None, board: str | None = None) -> list[dict[str, Any]]:
    """热度 = Σ(排名权重 × log 在读)，排名权重 = 1 / sqrt(rank)；rising = 名次上升或新上榜的书数。
    board=None 时阅读榜与新书榜合并统计；传 read / new 只看一类榜。"""
    cur, prev = _items_for_trends(s)
    prev_rank = {rank_key(p): p["rank"] for p in prev}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for it in cur:
        if gender and it["gender"] != gender:
            continue
        if board and it["board"] != board:
            continue
        groups[it["category"] or "其他"].append(it)
    out: list[dict[str, Any]] = []
    for cat, items in groups.items():
        heat = sum((1 / math.sqrt(max(1, i["rank"]))) * math.log10(max(10, i["read_count"])) for i in items)
        rising = 0
        if any(i.get("rank_diff") for i in items):
            rising = sum(1 for i in items if (i.get("rank_diff") or 0) > 0)
        elif prev:
            for i in items:
                pr = prev_rank.get(rank_key(i))
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
