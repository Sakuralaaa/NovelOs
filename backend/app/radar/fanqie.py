"""番茄 App 榜单接口客户端（匿名、明文）。

合规约束：只取公开字段（书名、作者、分类、在读数、简介、标签），每次刷新内请求间隔 ≥1s，
正常 UA，超时 10s，默认关闭。番茄用户协议禁止爬虫与自动化接入，请仅用于个人选题参考，可一键关闭。
接口字段（2026-11-12 实测）：data.result[] 含 book_id、book_name、author、category、category_v2[]、
read_count、abstract、hot、creation_status 等；无 word_count 与频道字段。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger("novelos.radar")

FEMALE_HINTS = re.compile(r"甜宠|豪门|总裁|宫斗|宅斗|古言|现言|纯爱|快穿|年代|女频|种田|婚|千金|王妃|女尊|青春|言情")


def guess_gender(category: str, tags: list[str]) -> str:
    return "female" if FEMALE_HINTS.search(category + "".join(tags)) else "male"


def _to_int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def parse_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, r in enumerate((payload.get("data") or {}).get("result") or [], 1):
        if not isinstance(r, dict) or not r.get("book_name"):
            continue
        url = str(r.get("item_schema_url") or "") + str(r.get("url") or "")
        if "short_series" in url or "short_play" in url:
            continue  # 短剧条目不是小说
        cats = [str(c) for c in (r.get("category_v2") or [])] or [c for c in str(r.get("category") or "").split(",") if c]
        out.append({
            "book_id_ext": str(r.get("book_id") or ""),
            "title": str(r.get("book_name")),
            "author": str(r.get("author") or ""),
            "category": cats[0] if cats else "其他",
            "rank": i,
            "read_count": _to_int(r.get("read_count")) or _to_int(r.get("hot")),
            "word_count": _to_int(r.get("word_number") or r.get("word_count")),
            "abstract": str(r.get("abstract") or "")[:500],
            "tags": cats[:5],
            "gender": guess_gender(cats[0] if cats else "", cats),
        })
    return out


def fetch_rank_lists() -> list[dict[str, Any]]:
    """依次请求配置的 side_type 榜单。任何异常向上抛，由调用方回退 mock。"""
    s = get_settings()
    items: list[dict[str, Any]] = []
    headers = {"User-Agent": s.radar_user_agent, "Accept": "application/json"}
    with httpx.Client(timeout=s.radar_timeout, headers=headers) as c:
        for i, side in enumerate(s.radar_side_types):
            if i:
                time.sleep(max(1.0, s.radar_interval_s))
            r = c.get(s.radar_base_url, params={"aid": 13, "limit": 30, "offset": 0, "side_type": side})
            r.raise_for_status()
            data = r.json()
            if data.get("code") not in (0, "0", None):
                raise RuntimeError(f"榜单接口返回 code={data.get('code')}")
            got = parse_items(data)
            for it in got:
                it["tags"] = list(dict.fromkeys([*it["tags"], f"side{side}"]))[:6]
            items.extend(got)
    # 跨榜去重，保留首次出现（排名靠前）的
    seen: set[str] = set()
    uniq = []
    for it in items:
        if it["book_id_ext"] in seen:
            continue
        seen.add(it["book_id_ext"])
        uniq.append(it)
    if not uniq:
        raise RuntimeError("榜单接口没有返回小说条目")
    return uniq
