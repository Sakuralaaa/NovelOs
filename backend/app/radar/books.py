"""v0.9.1 榜单单书：详情（书页章节目录、完整简介，缓存 24 小时）与单书 AI 灵感（书名 / 封面词 / 简介）。

- 详情缓存在数据目录 radar_detail/{book_id}.json；抓取失败不缓存，仍返回条目信息并带 detail_error。
- AI 灵感只基于书名/简介/标签/题材学「同类爆款思路」，结果用 v0.7 的 8 字 n-gram 与原书名、原简介比对，
  重合的候选丢弃（书名候选另查与原书名连续 4 字相同），丢弃数记 dropped。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.api.schemas import iso, rank_item_out
from app.config import get_settings
from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway
from app.models.tables import RankItem
from app.radar import fanqie_web
from app.radar.covers import CoverError, safe_id
from app.services import common
from app.services.common import NotFound
from app.services.imitate import OVERLAP_N, OVERLAP_WARN, TITLE_OVERLAP_N, overlap_segments
from app.skills.loader import render, system_prompt

log = logging.getLogger("novelos.radar")

HEAD_N, TAIL_N = 50, 10
AI_KINDS = ("title", "cover", "blurb")
AI_DEFAULT_N = {"title": 5, "cover": 3, "blurb": 5}
AI_MAX_N = 10


def _check_id(book_id: str) -> str:
    try:
        return safe_id(book_id)
    except CoverError as e:
        raise ValueError(str(e)) from e


def latest_item(s: Session, book_id: str) -> RankItem:
    row = s.exec(select(RankItem).where(RankItem.book_id_ext == book_id).order_by(RankItem.id.desc())).first()  # type: ignore[union-attr]
    if row is None:
        raise NotFound("榜单里没有这本书")
    return row


# ------------------------------------------------------------------ 详情

def _cache_path(book_id: str):
    d = get_settings().data_dir / "radar_detail"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{book_id}.json"


def _read_cache(book_id: str) -> dict[str, Any] | None:
    p = _cache_path(book_id)
    try:
        data = json.loads(p.read_text("utf-8"))
    except (OSError, ValueError):
        return None
    ttl = get_settings().radar_detail_ttl_h * 3600
    if not isinstance(data, dict) or time.time() - float(data.get("ts") or 0) > ttl:
        return None
    return data


def _write_cache(book_id: str, data: dict[str, Any]) -> None:
    p = _cache_path(book_id)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def _with_urls(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [{"title": r.get("title") or "", "item_id": r.get("item_id") or "", "url": fanqie_web.reader_url(r.get("item_id"))} for r in rows]


def detail(book_id: str, refresh: bool = False) -> dict[str, Any]:
    """→ {item, chapter_total, abstract, chapters_head, chapters_tail, fetched_at, detail_error, cached}。
    chapters_head 为前 50 章；chapters_tail 为其后的最后 10 章（总数 ≤50 时为空，不与 head 重复）。"""
    book_id = _check_id(book_id)
    with session_scope() as s:
        row = latest_item(s, book_id)
        item = rank_item_out(row)
    out: dict[str, Any] = {"item": item, "chapter_total": None, "abstract": item["abstract"], "chapters_head": [], "chapters_tail": [],
                           "fetched_at": None, "detail_error": None, "cached": False}
    if not book_id.isdigit():
        out["detail_error"] = "示例数据没有番茄书页"
        return out
    data = None if refresh else _read_cache(book_id)
    cached = data is not None
    if data is None:
        try:
            parsed = fanqie_web.parse_book_page(fanqie_web.fetch_book_page(book_id))
        except Exception as e:  # noqa: BLE001  网络/状态码错误都只记在 detail_error 里
            log.info("读取书页失败 %s：%s", book_id, e)
            out["detail_error"] = f"读取番茄书页失败：{e}"[:200]
            return out
        chs = parsed["chapters"]
        if parsed["chapter_total"] is None and not chs and not parsed["abstract"]:
            out["detail_error"] = "书页里没有找到章节目录（页面结构可能变了）"
            return out
        data = {"ts": time.time(), "fetched_at": iso(datetime.now(timezone.utc)), "chapter_total": parsed["chapter_total"],
                "abstract": parsed["abstract"], "head": chs[:HEAD_N], "tail": chs[HEAD_N:][-TAIL_N:]}
        _write_cache(book_id, data)
    out.update({"chapter_total": data.get("chapter_total"), "abstract": data.get("abstract") or item["abstract"],
                "chapters_head": _with_urls(data.get("head") or []), "chapters_tail": _with_urls(data.get("tail") or []),
                "fetched_at": data.get("fetched_at"), "cached": cached})
    return out


# ------------------------------------------------------------------ 单书 AI 灵感

def ai_n(kind: str, n: int | None) -> int:
    if kind not in AI_KINDS:
        raise ValueError("kind 只能是 title / cover / blurb")
    return max(1, min(AI_MAX_N, int(n or AI_DEFAULT_N[kind])))


def _clean(v: Any, n: int) -> str:
    return re.sub(r"[ \t\u3000]+", " ", str(v or "")).strip()[:n]


def _normalize(kind: str, raw: Any) -> list[dict[str, str]]:
    items = raw.get("candidates") if isinstance(raw, dict) else raw
    if isinstance(items, dict):
        items = [items]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for x in items if isinstance(items, list) else []:
        if isinstance(x, str):
            x = {"title": x} if kind == "title" else {"prompt": x} if kind == "cover" else {"blurb": x}
        if not isinstance(x, dict):
            continue
        if kind == "title":
            c = {"title": _clean(x.get("title"), 40).strip("《》"), "why": _clean(x.get("why"), 80)}
            key = c["title"]
        elif kind == "cover":
            p = _clean(x.get("prompt"), 600)
            if p and not re.search(r"3\s*[:：比]\s*4|--ar\s*3:4", p):
                p += "，竖版 3:4"
            c = {"prompt": p, "style": _clean(x.get("style"), 20)}
            key = p
        else:
            c = {"blurb": str(x.get("blurb") or "").strip()[:400], "hook": _clean(x.get("hook"), 80)}
            key = c["blurb"]
        if key and key not in seen:
            seen.add(key)
            out.append(c)
    return out


def _main_text(kind: str, c: dict[str, str]) -> str:
    return c.get("title") or "" if kind == "title" else c.get("prompt") or "" if kind == "cover" else c.get("blurb") or ""


def check_candidates(kind: str, cands: list[dict[str, str]], title: str, abstract: str) -> tuple[list[dict[str, str]], int, list[str]]:
    """与原书名/原简介比对：连续 8 字相同 ≥1 处丢弃；书名候选再查与原书名连续 4 字相同、或直接包含原书名。"""
    ref = f"{title}\n{abstract}"
    keep: list[dict[str, str]] = []
    warns: list[str] = []
    for c in cands:
        text = " ".join(v for v in c.values() if v)
        segs = overlap_segments(text, ref, OVERLAP_N)
        reason = ""
        if len(segs) >= OVERLAP_WARN:
            reason = f"和原书名/简介有 {len(segs)} 处连续 {OVERLAP_N} 字相同（{segs[0][:16]}）"
        elif kind == "title":
            main = _main_text(kind, c)
            tsegs = overlap_segments(main, title, TITLE_OVERLAP_N)
            if tsegs or (len(title) >= 2 and title in main):
                reason = f"书名和原书《{title}》太像（{(tsegs or [title])[0]}）"
        if reason:
            warns.append(f"已丢弃「{_main_text(kind, c)[:20]}」：{reason}")
        else:
            keep.append(c)
    return keep, len(cands) - len(keep), warns


def ai_job(book_id: str, kind: str, n: int | None, ctx: JobContext | None = None) -> dict[str, Any]:
    """→ {kind, book_id_ext, ref_title, candidates, dropped, warnings}。"""
    book_id = _check_id(book_id)
    n = ai_n(kind, n)
    with session_scope() as s:
        it = latest_item(s, book_id).model_dump()
    cache = _read_cache(book_id) if book_id.isdigit() else None
    abstract = (cache or {}).get("abstract") or it["abstract"] or ""
    if ctx is not None:
        ctx.progress(15, {"title": "想书名", "cover": "写封面提示词", "blurb": "写简介"}[kind] + f"（{n} 个）")
    user = render(f"radar_book_{kind}", gender_label=common.GENDER_LABEL.get(it["gender"], it["gender"]), title=it["title"],
                  category=it["category"] or "未分类", tags="、".join(it.get("tags") or []) or "（无）",
                  abstract=abstract[:600] or "（无简介）", n=n)
    raw = get_gateway().chat_json("radar_book_ai", system_prompt("radar_book_ai"), user,
                                  meta={"kind": kind, "n": n, "title": it["title"], "category": it["category"], "gender": it["gender"],
                                        "tags": it.get("tags") or [], "abstract": abstract}, temperature=0.9)
    cands = _normalize(kind, raw)
    if not cands:
        raise ValueError("模型没有给出候选")
    if ctx is not None:
        ctx.progress(85, "和原书比对查重")
    keep, dropped, warns = check_candidates(kind, cands, it["title"], abstract)
    return {"kind": kind, "book_id_ext": book_id, "ref_title": it["title"], "candidates": keep[:n], "dropped": dropped, "warnings": warns}
