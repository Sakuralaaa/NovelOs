"""v0.9 书测：一次出 4 组风格不同的包装 {style, title, subtitle(≤20字), hook, cover_prompt(3:4)}，存在书上；
作者选定一组后写进书名 / 一句话简介（走 book_edit.apply_info，留旧版本可 /undo 撤回），可选写进包装的简介和封面提示词。

四组风格固定：A 番茄情绪爽感 / B 悬疑规则脑洞 / C 轻松沙雕 / D 起点正剧。
思路参考 novel_ai_engine prompts_reconstructed/04（用户授权参考，文字自写）。
"""

from __future__ import annotations

import re
from typing import Any

from app.db import session_scope
from app.jobs.manager import JobContext
from app.llm.gateway import get_gateway, resolve_targets
from app.models.tables import Package, utcnow
from app.services import book_edit, common, packaging
from app.services.common import Conflict, NotFound
from app.skills.loader import render, system_prompt

STYLES: list[tuple[str, str]] = [("A", "番茄情绪爽感"), ("B", "悬疑规则脑洞"), ("C", "轻松沙雕"), ("D", "起点正剧")]
SUBTITLE_MAX = 20
TITLE_MAX = 30
FIELDS = ("title", "subtitle", "hook", "cover_prompt")


def _clean(v: Any, n: int) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _style_code(v: Any) -> str | None:
    s = str(v or "").strip()
    m = re.match(r"^(?:方案)?\s*([A-Da-d])\b", s)
    if m:
        return m.group(1).upper()
    for code, name in STYLES:
        if name in s or name[:2] in s:
            return code
    return None


def normalize_variants(raw: Any) -> tuple[list[dict[str, str]], list[str]]:
    """固定成 A–D 四组（按 style 对号入座，对不上的按顺序补位）。缺字段的组丢掉并记 warning。"""
    items = raw.get("variants") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError("模型没有给出书测方案")
    slots: dict[str, dict[str, Any]] = {}
    rest: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        code = _style_code(it.get("style"))
        if code and code not in slots:
            slots[code] = it
        else:
            rest.append(it)
    for code, _ in STYLES:
        if code not in slots and rest:
            slots[code] = rest.pop(0)
    out: list[dict[str, str]] = []
    warns: list[str] = []
    for code, name in STYLES:
        it = slots.get(code)
        title = _clean(it.get("title"), 60).strip("《》") if it else ""
        if not it or not title:
            warns.append(f"方案 {code}（{name}）没有生成出来")
            continue
        sub = _clean(it.get("subtitle"), 60)
        if len(sub) > SUBTITLE_MAX:
            warns.append(f"方案 {code} 副标题超过 {SUBTITLE_MAX} 字，已截断")
            sub = sub[:SUBTITLE_MAX]
        cover = _clean(it.get("cover_prompt"), 600)
        if cover and not re.search(r"3\s*[:：比]\s*4|--ar\s*3:4", cover):
            cover += "，竖版 3:4"
        out.append({"style": f"{code} {name}", "title": title[:TITLE_MAX], "subtitle": sub,
                    "hook": _clean(it.get("hook"), 200), "cover_prompt": cover})
    if not out:
        raise ValueError("模型没有给出可用的书测方案")
    titles = [v["title"] for v in out]
    if len(set(titles)) < len(titles):
        warns.append("有两组书名重复")
    return out, warns


def _book_material(s: Any, book_id: int) -> tuple[str, dict[str, Any]]:
    b = common.get_book(s, book_id)
    lines = [common.book_context(s, b, with_cards=False)]
    prot = common.protagonist(s, book_id)
    if prot:
        lines.append(f"主角：{prot.name}：{prot.summary}")
    cheat = next(iter(common.cards(s, book_id, "cheat")), None)
    if cheat:
        lines.append(f"金手指：{cheat.name}：{cheat.summary}")
    top = [n for n in common.outline_nodes(s, book_id) if n.level in ("book", "volume")]
    top.sort(key=lambda n: (0 if n.level == "book" else 1, n.order))
    for n in top[:2]:
        if n.summary:
            lines.append(f"{'总纲' if n.level == 'book' else '第一卷'}：{n.summary[:300]}")
    pkg = s.get(Package, book_id)
    if pkg is not None and pkg.blurb:
        lines.append(f"现有简介：{pkg.blurb[:300]}")
    meta = {**common.kit_meta(s, b), "cheat": cheat.name if cheat else None}
    return "\n".join(lines), meta


def generate(book_id: int, ctx: JobContext | None = None) -> dict[str, Any]:
    progress = ctx.progress if ctx else (lambda *a, **k: None)
    with session_scope() as s:
        material, meta = _book_material(s, book_id)
    progress(20, "生成 4 组书测方案")
    raw = get_gateway().chat_json("book_test", system_prompt("book_test"), render("book_test", book_context=material),
                                  meta=meta, temperature=0.9)
    variants, warns = normalize_variants(raw)
    with session_scope() as s:
        ts = resolve_targets(s, "planner")
        b = common.get_book(s, book_id)
        b.book_test = {"variants": variants, "warnings": warns, "created_at": utcnow().isoformat(),
                       "model": f"{ts[0].name}/{ts[0].model}" if ts else "mock", "adopted": None}
        s.add(b)
        s.commit()
        return book_test_out(book_id, b.book_test)


def book_test_out(book_id: int, bt: dict[str, Any] | None) -> dict[str, Any]:
    bt = bt or {}
    return {"book_id": book_id, "variants": list(bt.get("variants") or []), "warnings": list(bt.get("warnings") or []),
            "created_at": bt.get("created_at"), "model": bt.get("model") or "", "adopted": bt.get("adopted"),
            "adopted_fields": list(bt.get("adopted_fields") or [])}


def get(book_id: int) -> dict[str, Any]:
    with session_scope() as s:
        b = common.get_book(s, book_id)
        if not (b.book_test or {}).get("variants"):
            raise NotFound("这本书还没做过书测：先 POST /api/books/{id}/book-test 生成")
        return book_test_out(book_id, b.book_test)


def adopt(book_id: int, index: int, fields: list[str] | None = None) -> dict[str, Any]:
    """选定一组：title → 书名，subtitle → 一句话简介（book.tagline）；可选 hook → 包装简介，cover_prompt → 包装封面提示词。
    书名/简介走 apply_info（旧版本进版本栈，可 POST /books/{id}/undo 撤回）。返回 {before, after, applied, index}。"""
    use = [f for f in (fields or ["title", "subtitle"]) if f in FIELDS] or ["title", "subtitle"]
    with session_scope() as s:
        b = common.get_book(s, book_id)
        bt = dict(b.book_test or {})
        vs = bt.get("variants") or []
        if not vs:
            raise Conflict("这本书还没做过书测")
        if not 0 <= index < len(vs):
            raise NotFound(f"没有第 {index} 组方案（共 {len(vs)} 组，下标从 0 开始）")
        v = vs[index]
        before = {**book_edit.info_of(b), "blurb": "", "cover_prompt": ""}
        pkg = s.get(Package, book_id)
        if pkg is not None:
            before["blurb"], before["cover_prompt"] = pkg.blurb, pkg.cover_prompt
    info: dict[str, Any] = {}
    if "title" in use:
        info["title"] = v["title"]
    if "subtitle" in use and v.get("subtitle"):
        info["tagline"] = v["subtitle"]
    if info:
        book_edit.apply_info(book_id, info, f"书测：采纳方案 {v['style']}")
    with session_scope() as s:
        if "hook" in use or "cover_prompt" in use:
            pkg = packaging.get_or_create_package(s, book_id)
            if "hook" in use and v.get("hook"):
                pkg.blurb = v["hook"]
            if "cover_prompt" in use and v.get("cover_prompt"):
                pkg.cover_prompt = v["cover_prompt"]
            s.add(pkg)
        b = common.get_book(s, book_id)
        bt = dict(b.book_test or {})
        bt["adopted"], bt["adopted_fields"] = index, use
        b.book_test = bt
        b.updated_at = utcnow()
        s.add(b)
        s.commit()
        pkg = s.get(Package, book_id)
        after = {**book_edit.info_of(b), "blurb": pkg.blurb if pkg else "", "cover_prompt": pkg.cover_prompt if pkg else ""}
    return {"index": index, "variant": v, "applied": use, "before": before, "after": after}
