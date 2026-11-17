"""v0.13 @变量：写章、改写、大纲、AI 改设定的要求里写 @书名、@第3章正文、@前5章摘要… 自动展开成资料块，
同一份资料只放一次，每个变量有字数上限，合计不超过 VAR_BUDGET。另提供上下文构成预览与按书关闭某些块。"""

from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from app.db import kv_get, kv_set
from app.models.tables import Chapter, OutlineNode
from app.services import common

VAR_BUDGET = 6000
PER = {"text": 3000, "outline": 2400, "summary": 2400, "short": 600}
_N = r"(\d{1,5})"
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("range_outline", re.compile(rf"@第{_N}[-~到至]{_N}章章纲")),
    ("range_summary", re.compile(rf"@第{_N}[-~到至]{_N}章摘要")),
    ("vol_outline", re.compile(rf"@第{_N}卷卷纲")),
    ("ch_text", re.compile(rf"@第{_N}章正文")),
    ("ch_outline", re.compile(rf"@第{_N}章章纲")),
    ("ch_summary", re.compile(rf"@第{_N}章摘要")),
    ("prev_summary", re.compile(rf"@前{_N}章摘要")),
    ("fixed", re.compile(r"@(书名|简介|文风|平台|目标字数|总纲|当前章纲)")),
]
CATALOG = [
    ("书名", "@书名"), ("简介", "@简介"), ("文风", "@文风"), ("平台", "@平台"), ("目标字数", "@目标字数"), ("总纲", "@总纲"),
    ("当前章纲", "@当前章纲"), ("第N卷卷纲", "@第1卷卷纲"), ("第N章正文", "@第1章正文"), ("第N章章纲", "@第1章章纲"),
    ("第N章摘要", "@第1章摘要"), ("前N章摘要", "@前5章摘要"), ("第N-M章章纲", "@第1-3章章纲"), ("第N-M章摘要", "@第1-10章摘要"),
]
PLATFORM_LABEL = {"fanqie": "番茄", "qidian": "起点", "generic": "通用", "duanju": "短剧分镜"}


def catalog(s: Session, book_id: int) -> list[dict[str, Any]]:
    return [{"name": n, "insert": ins} for n, ins in CATALOG]


def _cut(t: str, n: int) -> tuple[str, bool]:
    t = (t or "").strip()
    return (t, False) if len(t) <= n else (t[: n - 1] + "…", True)


def _node_text(n: OutlineNode) -> str:
    b = n.beats or {}
    bits = [n.summary or ""] + [f"{k}：{b[k]}" for k in ("goal", "conflict", "payoff", "hook_end") if b.get(k)]
    return "；".join(x for x in bits if x)


def resolve(s: Session, book_id: int, text: str, chapter_number: int | None = None) -> dict[str, Any]:
    text = (text or "").replace("＠", "@")
    if "@" not in text:
        return {"block": "", "used": [], "chars": 0}
    book = common.get_book(s, book_id)
    nodes: list[OutlineNode] | None = None
    chs: dict[int, Chapter] | None = None

    def get_nodes() -> list[OutlineNode]:
        nonlocal nodes
        if nodes is None:
            nodes = common.outline_nodes(s, book_id)
        return nodes

    def get_chs() -> dict[int, Chapter]:
        nonlocal chs
        if chs is None:
            chs = {c.number: c for c in s.exec(select(Chapter).where(Chapter.book_id == book_id))}
        return chs

    seen: set[str] = set()
    out: list[tuple[str, str, str, bool]] = []  # token, label, body, truncated
    ch_nums_outline: set[int] = set()
    ch_nums_summary: set[int] = set()
    tokens: list[tuple[int, str, re.Match[str]]] = []
    for kind, pat in PATTERNS:
        for m in pat.finditer(text):
            if not any(a <= m.start() < a + len(t) for a, t, _ in [(x[0], x[2].group(0), None) for x in tokens]):
                tokens.append((m.start(), kind, m))
    tokens.sort(key=lambda x: x[0])
    for _, kind, m in tokens:
        tok = m.group(0)
        if tok in seen:
            continue
        seen.add(tok)
        if kind == "fixed":
            k = m.group(1)
            if k == "书名":
                out.append((tok, "书名", book.title, False))
            elif k == "简介":
                body, tr = _cut(book.premise or book.tagline or "", PER["short"])
                out.append((tok, "简介", body, tr))
            elif k == "文风":
                st = common.get_style(s, book_id)
                ex = (st.extracted or {}).get("llm") or {}
                body = "；".join(x for x in [st.tone, st.voice_notes, ex.get("summary") or ""] if x)
                out.append((tok, "文风", *_cut(body or "（未设定）", PER["short"])))
            elif k == "平台":
                out.append((tok, "平台", PLATFORM_LABEL.get(book.platform_style, book.platform_style), False))
            elif k == "目标字数":
                out.append((tok, "目标字数", f"全书 {book.target_words} 字，每章约 {book.chapter_words} 字", False))
            elif k == "总纲":
                root = next((n for n in get_nodes() if n.level == "book"), None)
                vols = [n for n in get_nodes() if n.level == "volume"]
                body = (root.summary if root else "") + ("\n" + "\n".join(f"{v.title}：{(v.summary or '')[:120]}" for v in vols) if vols else "")
                out.append((tok, "总纲", *_cut(body or "（还没有大纲）", PER["outline"])))
            elif k == "当前章纲":
                if chapter_number is None:
                    continue
                n = next((x for x in get_nodes() if x.level == "chapter" and x.order == chapter_number), None)
                out.append((tok, f"第{chapter_number}章章纲", *_cut(_node_text(n) if n else "（没有章纲）", PER["short"])))
            continue
        if kind == "vol_outline":
            k = int(m.group(1))
            vols = sorted([n for n in get_nodes() if n.level == "volume"], key=lambda x: x.order)
            v = vols[k - 1] if 0 < k <= len(vols) else None
            if v is None:
                continue
            arcs = [n for n in get_nodes() if n.parent_id == v.id]
            body = (v.summary or "") + ("\n" + "\n".join(f"- {a.title}：{(a.summary or '')[:100]}" for a in arcs) if arcs else "")
            out.append((tok, f"第{k}卷卷纲（{v.title}）", *_cut(body, PER["outline"])))
        elif kind == "ch_text":
            k = int(m.group(1))
            c = get_chs().get(k)
            if c and c.content.strip():
                out.append((tok, f"第{k}章正文", *_cut(c.content, PER["text"])))
        elif kind in ("ch_outline", "range_outline"):
            a = int(m.group(1))
            b = int(m.group(2)) if kind == "range_outline" else a
            ch_nums_outline.update(range(min(a, b), min(max(a, b), min(a, b) + 60) + 1))
        elif kind in ("ch_summary", "range_summary", "prev_summary"):
            if kind == "prev_summary":
                n = min(50, int(m.group(1)))
                ref = chapter_number or (max(get_chs()) + 1 if get_chs() else 1)
                ch_nums_summary.update(range(max(1, ref - n), ref))
            else:
                a = int(m.group(1))
                b = int(m.group(2)) if kind == "range_summary" else a
                ch_nums_summary.update(range(min(a, b), min(max(a, b), min(a, b) + 100) + 1))
    if ch_nums_outline:
        ns = sorted([x for x in get_nodes() if x.level == "chapter" and x.order in ch_nums_outline], key=lambda x: x.order)
        body = "\n".join(f"第{x.order}章《{x.title}》：{_node_text(x)[:160]}" for x in ns)
        if body:
            out.append(("章纲", f"第{min(ch_nums_outline)}–{max(ch_nums_outline)}章章纲", *_cut(body, PER["outline"])))
    if ch_nums_summary:
        cs = [get_chs()[k] for k in sorted(ch_nums_summary) if k in get_chs() and (get_chs()[k].summary or "").strip()]
        body = "\n".join(f"第{c.number}章 {c.title}：{c.summary}" for c in cs)
        if body:
            out.append(("摘要", f"第{min(ch_nums_summary)}–{max(ch_nums_summary)}章摘要", *_cut(body, PER["summary"])))
    parts, used, total = [], [], 0
    for tok, label, body, tr in out:
        if total + len(body) > VAR_BUDGET and parts:
            used.append({"token": tok, "label": label, "chars": 0, "truncated": True, "dropped": True})
            continue
        parts.append(f"〔{label}〕\n{body}")
        total += len(body)
        used.append({"token": tok, "label": label, "chars": len(body), "truncated": tr, "dropped": False})
    block = ("【@变量资料（作者点名引用）】\n" + "\n".join(parts)) if parts else ""
    return {"block": block, "used": used, "chars": total}


# ------------------------------------------------------------------ 上下文构成

PINNED = ("本章写作任务", "作者对本章的额外要求", "@引用设定", "@变量资料", "上一章结尾原文")


def _label(part: str) -> str:
    m = re.match(r"【([^】]+)】", part.strip())
    if not m:
        return ""
    return re.sub(r"（.*$", "", m.group(1)).strip()


def get_exclude(s: Session, book_id: int) -> list[str]:
    v = kv_get(s, f"context_exclude:{book_id}", [])
    return [str(x) for x in v] if isinstance(v, list) else []


def set_exclude(s: Session, book_id: int, blocks: list[str]) -> list[str]:
    clean = [b for b in dict.fromkeys(str(x).strip()[:30] for x in blocks) if b and b not in PINNED][:20]
    kv_set(s, f"context_exclude:{book_id}", clean)
    return clean


def filter_parts(s: Session, book_id: int, parts: list[str]) -> list[str]:
    ex = set(get_exclude(s, book_id))
    if not ex:
        return parts
    return [p for p in parts if _label(p) not in ex]


def context_preview(s: Session, book_id: int, chapter_id: int | None = None) -> dict[str, Any]:
    from app.services.context import build_context_pack

    book = common.get_book(s, book_id)
    node = None
    if chapter_id:
        ch = s.get(Chapter, chapter_id)
        if ch is None or ch.book_id != book_id:
            raise common.NotFound("章节不存在")
        node = s.get(OutlineNode, ch.outline_node_id) if ch.outline_node_id else None
        if node is None:
            node = OutlineNode(book_id=book_id, level="chapter", order=ch.number, title=ch.title, beats={"characters": []})
    else:
        written = {c.number for c in common.written_chapters(s, book_id)}
        nxt = max(written) + 1 if written else 1
        node = next((n for n in common.outline_nodes(s, book_id) if n.level == "chapter" and n.order == nxt), None) or \
            OutlineNode(book_id=book_id, level="chapter", order=nxt, title=f"第{nxt}章", beats={"characters": []})
    ex = set(get_exclude(s, book_id))
    pack = build_context_pack(s, book, node, ignore_exclude=True)
    blocks = []
    for part in pack.suffix.split("\n\n"):
        lab = _label(part)
        if not lab:
            if blocks:
                blocks[-1]["chars"] += len(part) + 2
            continue
        blocks.append({"label": lab, "chars": len(part), "excluded": lab in ex, "pinned": lab in PINNED})
    if pack.prev_tail:  # v0.17：上一章结尾单独放在写作提示最后
        blocks.append({"label": "上一章结尾原文", "chars": len(pack.prev_tail), "excluded": False, "pinned": True})
    return {"chapter": node.order, "fixed_chars": len(pack.prefix), "blocks": blocks,
            "total_chars": len(pack.prefix) + sum(b["chars"] for b in blocks if not b["excluded"]), "exclude": sorted(ex)}
