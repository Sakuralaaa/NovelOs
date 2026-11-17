"""v0.9.3 成本提示：调模型前估算输入/输出 token、调用次数、走哪个模型、大概要多少秒。

- 输入：尽量按真实组装的上下文长度算（写章用 Context Pack，改写/润色用章节正文），中文 1 字≈tokens_per_char token。
- 输出：按目标字数（words > 书的 chapter_words > 2200）。
- 秒数：llm_usage 里同 route 最近 20 次真实调用的平均耗时 × 调用次数；没有记录用默认值。
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, select

from app.llm import usage as usage_log
from app.llm.gateway import resolve_targets
from app.models.tables import Book, Chapter, OutlineNode
from app.services import common
from app.services.common import NotFound

KINDS: dict[str, dict[str, Any]] = {
    # kind: route（角色）、calls（调用次数）、needs（book / chapter）、label
    "chapter_write": {"route": "writer", "needs": "book", "label": "写一章"},
    "chapter_rewrite": {"route": "writer", "needs": "chapter", "label": "按要求改写本章"},
    "polish_voice": {"route": "writer", "needs": "chapter", "label": "语感重塑"},
    "humanize": {"route": "writer", "needs": "chapter", "label": "去 AI 味"},
    "thicken": {"route": "writer", "needs": "chapter", "label": "描写增厚"},
    "review": {"route": "reviewer", "needs": "chapter", "label": "审稿"},
    "outline": {"route": "planner", "needs": "book", "label": "生成大纲"},
    "bible": {"route": "planner", "needs": "book", "label": "生成设定"},
    "report": {"route": "planner", "needs": None, "label": "风向标日报"},
    "idea": {"route": "planner", "needs": None, "label": "生成选题"},
    "field_ai": {"route": "planner", "needs": "book", "label": "字段级 AI"},
    "soul": {"route": "planner", "needs": "book", "label": "灵魂五维"},
    "teardown": {"route": "reviewer", "needs": None, "label": "拆书"},
    "package": {"route": "planner", "needs": "book", "label": "包装（书名/简介/封面词）"},
    "aigc": {"route": "zhuque", "needs": "chapter", "label": "AI 率检测（朱雀）"},
}
DEFAULT_SECONDS = {"writer": 45, "planner": 35, "reviewer": 30, "agent": 20}
SYSTEM_CHARS = 1800  # 规则包 + 系统提示的大致字数
SCENES_EST = 4
DEFAULT_WORDS = 2200


def _model(s: Session, route: str) -> str:
    ts = resolve_targets(s, route)
    return f"{ts[0].name}/{ts[0].model}" if ts else "mock"


def _pack_chars(s: Session, book: Book) -> tuple[int, int, str]:
    """→ (Context Pack 前缀+后缀字数, 章纲字数, 说明)。下一章还没有章纲时按书级上下文粗估。"""
    from app.services.context import build_context_pack, scene_plan_context
    from app.services.outline import max_chapter_number, node_plan_text

    bid = book.id or 0
    nxt = max_chapter_number(s, bid) + 1
    node = s.exec(select(OutlineNode).where(OutlineNode.book_id == bid, OutlineNode.level == "chapter",
                                            OutlineNode.order == nxt)).first()
    if node is None:
        return len(common.book_context(s, book)) + 2500, 600, f"第{nxt}章还没有章纲，按书级设定粗估"
    pack = build_context_pack(s, book, node)
    plan = node_plan_text(node)
    return len(pack.prefix) + len(pack.suffix) + len(pack.prev_tail) + len(scene_plan_context(s, book, node)) // SCENES_EST, len(plan), \
        f"按第{nxt}章的实际上下文估算"


def estimate(s: Session, kind: str, book_id: int | None = None, chapter_id: int | None = None,
             words: int | None = None) -> dict[str, Any]:
    if kind not in KINDS:
        raise ValueError(f"不支持的 kind：{kind}")
    spec = KINDS[kind]
    route = spec["route"]
    notes: list[str] = []
    book: Book | None = None
    ch: Chapter | None = None
    if chapter_id is not None:
        ch = s.get(Chapter, chapter_id)
        if ch is None:
            raise NotFound("章节不存在")
        book_id = book_id or ch.book_id
    if book_id is not None:
        book = s.get(Book, book_id)
        if book is None:
            raise NotFound("书不存在")
    target = int(words or (book.chapter_words if book else 0) or DEFAULT_WORDS)
    content_len = len(ch.content) if ch and ch.content else 0
    if spec["needs"] == "chapter" and not content_len:
        notes.append("没有指定有正文的章节，按目标字数估算")
        content_len = target
    if spec["needs"] == "book" and book is None:
        notes.append("没有指定书，按通用默认值估算")
    book_ctx = len(common.book_context(s, book)) if book else 1200

    if kind == "chapter_write":
        if book is not None:
            pack_len, plan_len, n = _pack_chars(s, book)
            notes.append(n)
        else:
            pack_len, plan_len = 6000, 600
        write_in = pack_len + plan_len + 800
        state_in = target + 1500
        inp = (book_ctx + plan_len + 1500) + write_in + state_in + 2 * (target + plan_len + 2500) + target
        out = int(target * 1.05) + 800 + 600 + 600 + 200
        calls = 1 + 1 + 1 + 3
        notes.append("排段落 1 次 + 整章写作 1 次 + 抽状态 1 次 + 审稿、读者审读与摘要；开篇第 1 章和大爽点章写 2 版再成对比较，约翻倍；没过审时还会多 1–2 次重写")
    elif kind in ("chapter_rewrite", "polish_voice"):
        inp, out, calls = content_len + 1500 + SYSTEM_CHARS, content_len, 1
    elif kind in ("humanize", "thicken"):
        inp, out, calls = 3 * (1200 + SYSTEM_CHARS) + content_len // 2, max(600, content_len // 3), 3
        notes.append("按段定点改写，次数随问题段落数变化")
    elif kind == "review":
        inp, out, calls = content_len + 2500 + SYSTEM_CHARS, 900, 1
    elif kind == "outline":
        inp, out, calls = book_ctx + 2500 + SYSTEM_CHARS, 4000, 1
    elif kind == "bible":
        inp, out, calls = book_ctx + 2000 + SYSTEM_CHARS, 3000, 1
    elif kind == "report":
        from app.radar import service as radar

        top_n = int(radar.get_report_config(s)["radar_report_top_n"])
        inp, out, calls = 4 * top_n * 130 + 2500, 4500, 1
    elif kind == "idea":
        inp, out, calls = 2500 + SYSTEM_CHARS, 2500, 2
        notes.append("生成 + 复核打分")
    elif kind == "field_ai":
        inp, out, calls = book_ctx + 2400 + SYSTEM_CHARS, 200, 1
    elif kind == "soul":
        inp, out, calls = book_ctx + 2400 + SYSTEM_CHARS, 400, 1
    elif kind == "teardown":
        n = int(words or 20000)
        inp, out, calls = min(n, 16000) + 1500, 3000, 1
        notes.append("输入按原文字数（最多 16000 字进提示词）")
    else:  # package
        inp, out, calls = book_ctx + 1500 + SYSTEM_CHARS, 1500, 1

    if kind == "aigc":
        return {"kind": kind, "label": spec["label"], "input_tokens_est": 0, "output_tokens_est": 0, "calls_est": 1,
                "route": "zhuque", "model": "zhuque", "seconds_est": 10, "seconds_source": "default",
                "note": "朱雀检测不消耗模型 token，计朱雀自己的检测额度"}
    avg, n_hist = usage_log.avg_ms(route)
    if n_hist:
        seconds, src = int(round(avg / 1000 * calls)), "history"
    else:
        seconds, src = DEFAULT_SECONDS.get(route, 30) * calls, "default"
    model = _model(s, route)
    if model == "mock":
        notes.append("当前没有可用模型渠道，实际会走演示模式（不花钱）")
    tin, tout = usage_log.est_tokens(inp), usage_log.est_tokens(out)
    cost, priced = 0.0, False
    ts = resolve_targets(s, route)
    if ts:  # v0.12：按渠道里填的单价折算人民币
        from app.llm import archive
        from app.models.tables import Channel

        ch_row = s.get(Channel, ts[0].channel_id)
        prices = dict(ch_row.prices or {}) if ch_row is not None else {}
        pi, po = archive.price_of(prices, ts[0].model)
        priced = bool(pi or po)
        cost = archive.cost_cny(prices, ts[0].model, tin, tout)
    from app.llm import archive as _arc

    budget = _arc.budget_status(s, book_id)
    return {"kind": kind, "label": spec["label"], "input_tokens_est": tin,
            "output_tokens_est": tout, "calls_est": calls, "route": route, "model": model,
            "seconds_est": max(1, seconds), "seconds_source": src, "note": "；".join(notes),
            "cost_cny_est": round(cost, 4), "priced": priced, "budget": budget}

