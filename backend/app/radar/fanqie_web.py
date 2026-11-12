"""番茄网页版「阅读榜」客户端：男频 19 个 + 女频 18 个题材榜，每榜最多 100 本。

- 数据接口：fanqienovel.com/api/rank/category/list（rank_list_type=3, rankMold=2），匿名可用。
- 书名/作者/简介做了 PUA 字体混淆，用 fanqie_charset 还原。
- 每个榜带 rankVersion（每日一个版本号）；同一版本重复刷新内容不变，服务层据此去重。
- 合规：只取公开字段，单次刷新内请求间隔 ≥1s，正常 UA。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from app.config import get_settings
from app.radar.fanqie_charset import CHARSET, CODE_START

log = logging.getLogger("novelos.radar")

API = "https://fanqienovel.com/api/rank/category/list"
RANK_PAGE = "https://fanqienovel.com/rank/1_2_1141"
WEB_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# 页面解析失败时的兜底题材表（2026-11 实测）
BOARDS: dict[str, list[tuple[str, str]]] = {
    "male": [("1141", "西方奇幻"), ("1140", "东方仙侠"), ("8", "科幻末世"), ("261", "都市日常"), ("124", "都市修真"),
             ("1014", "都市高武"), ("273", "历史古代"), ("27", "战神赘婿"), ("263", "都市种田"), ("258", "传统玄幻"),
             ("272", "历史脑洞"), ("539", "悬疑脑洞"), ("262", "都市脑洞"), ("257", "玄幻脑洞"), ("751", "悬疑灵异"),
             ("504", "抗战谍战"), ("746", "游戏体育"), ("718", "动漫衍生"), ("1016", "男频衍生")],
    "female": [("1139", "古风世情"), ("8", "科幻末世"), ("746", "游戏体育"), ("1015", "女频衍生"), ("248", "玄幻言情"),
               ("23", "种田"), ("79", "年代"), ("267", "现言脑洞"), ("246", "宫斗宅斗"), ("539", "悬疑脑洞"),
               ("253", "古言脑洞"), ("24", "快穿"), ("749", "青春甜宠"), ("745", "星光璀璨"), ("747", "女频悬疑"),
               ("750", "职场婚恋"), ("748", "豪门总裁"), ("1017", "民国言情")],
}


def decode(s: str | None) -> str:
    out = []
    for ch in s or "":
        i = ord(ch) - CODE_START
        out.append(CHARSET[i] if 0 <= i < len(CHARSET) and CHARSET[i] != "?" else ch)
    return "".join(out)


def _int(v: Any) -> int:
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def fetch_boards(c: httpx.Client) -> dict[str, list[tuple[str, str]]]:
    try:
        html = c.get(RANK_PAGE).text
        i = html.find("__INITIAL_STATE__=")
        if i >= 0:
            state, _ = json.JSONDecoder().raw_decode(html[i + 18:].replace(":undefined", ":null"))
            lst = (state.get("rank") or {}).get("rankCategoryTypeList") or {}
            boards = {g: [(str(x["id"]), str(x["name"])) for x in lst.get(g) or [] if x.get("id")] for g in ("male", "female")}
            if boards["male"] and boards["female"]:
                return boards
    except Exception as e:  # noqa: BLE001
        log.info("读取题材列表失败，使用内置列表：%s", e)
    return BOARDS


def parse_board(data: dict[str, Any], gender: str, category: str) -> list[dict[str, Any]]:
    out = []
    for k, r in enumerate((data.get("data") or {}).get("book_list") or [], 1):
        if not isinstance(r, dict) or not r.get("bookName"):
            continue
        title = decode(r.get("bookName"))
        out.append({
            "book_id_ext": str(r.get("bookId") or ""),
            "title": title,
            "author": decode(r.get("author")),
            "category": category,
            "rank": _int(r.get("currentPos")) or k,
            "rank_diff": _int(r.get("rankPosDiff")),
            "read_count": _int(r.get("read_count")) or _int(r.get("readCount")),
            "word_count": _int(r.get("wordNumber")),
            "abstract": re.sub(r"\s+", " ", decode(r.get("abstract"))).strip()[:500],
            "tags": [category, "完结" if str(r.get("creationStatus")) == "0" else "连载"],
            "gender": gender,
        })
    return out


def fetch_rank_lists(per_board: int | None = None, progress=None) -> tuple[list[dict[str, Any]], str]:
    """返回（全部条目, 榜单版本号）。任何异常向上抛，由调用方回退。"""
    s = get_settings()
    per_board = max(10, min(100, per_board or s.radar_per_board))
    headers = {"User-Agent": WEB_UA, "Accept": "application/json, text/plain, */*", "Referer": "https://fanqienovel.com/rank"}
    items: list[dict[str, Any]] = []
    version = ""
    with httpx.Client(timeout=s.radar_timeout, headers=headers, follow_redirects=True) as c:
        boards = fetch_boards(c)
        todo = [(g, cid, name) for g in ("male", "female") for cid, name in boards[g]]
        for n, (g, cid, name) in enumerate(todo):
            time.sleep(max(1.0, s.radar_interval_s))
            got: list[dict[str, Any]] = []
            for offset in range(0, per_board, 30):
                r = c.get(API, params={
                    "app_id": 2503, "rank_list_type": 3, "offset": offset, "limit": min(30, per_board - offset),
                    "category_id": cid, "rank_version": version, "gender": 1 if g == "male" else 0, "rankMold": 2,
                })
                r.raise_for_status()
                data = r.json()
                if data.get("code") not in (0, "0"):
                    raise RuntimeError(f"榜单接口返回 code={data.get('code')}")
                version = version or str((data.get("data") or {}).get("rankVersion") or "")
                page = parse_board(data, g, name)
                got.extend(page)
                if len(page) < 30:
                    break
                time.sleep(max(1.0, s.radar_interval_s))
            items.extend(got[:per_board])
            if progress:
                progress(10 + int(70 * (n + 1) / len(todo)), f"{'男频' if g == 'male' else '女频'} · {name}（{n + 1}/{len(todo)}）")
    if not items:
        raise RuntimeError("榜单接口没有返回数据")
    return items, version
