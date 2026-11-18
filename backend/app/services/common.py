"""服务层公共查询。"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session, func, select

from app.models.tables import Book, Card, Chapter, Foreshadow, OutlineNode, Style


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


GENDER_LABEL = {"male": "男频", "female": "女频"}


def get_book(s: Session, book_id: int) -> Book:
    b = s.get(Book, book_id)
    if b is None:
        raise NotFound(f"书 {book_id} 不存在")
    return b


def book_stats(s: Session, book_id: int) -> dict[str, int]:
    chapters = s.exec(
        select(func.count(), func.coalesce(func.sum(Chapter.words), 0)).where(
            Chapter.book_id == book_id, Chapter.status == "committed"
        )
    ).one()
    fo = s.exec(
        select(func.count()).where(Foreshadow.book_id == book_id, Foreshadow.status.in_(["planted", "advancing"]))  # type: ignore[attr-defined]
    ).one()
    return {"chapters": int(chapters[0]), "words": int(chapters[1]), "foreshadow_open": int(fo)}


def cards(s: Session, book_id: int, type_: str | None = None, include_deprecated: bool = False) -> list[Card]:
    """设定条目。默认不含 v0.9.3 的弃用条目（status=deprecated）——所有生成上下文都走这里；
    管理类操作（列表、快照、回滚、按名去重）传 include_deprecated=True。"""
    q = select(Card).where(Card.book_id == book_id)
    if type_:
        q = q.where(Card.type == type_)
    if not include_deprecated:
        q = q.where(Card.status != "deprecated")
    return list(s.exec(q.order_by(Card.id)))


def approval_mode(b: Book) -> str:
    """v0.9.3：显式设置过就用设置；否则按旧的书级 agent_auto_apply 映射（true→auto，false→review）。"""
    if b.approval_mode in ("auto", "review"):
        return b.approval_mode
    return "auto" if b.agent_auto_apply else "review"


def chapter_review_mode(b: Book) -> bool:
    """章节 AI 是否只出对比稿不落库：只在作者显式选了 review 时生效（未设置的旧书维持旧行为）。"""
    return b.approval_mode == "review"


def protagonist(s: Session, book_id: int) -> Card | None:
    """视点主角。v0.17：同人书优先取同人设定里的主角（fanfic.protagonist.card_id → 同名卡），
    其次原创主角卡（origin=oc 且 role=protagonist），最后才是第一张 role=protagonist 的卡。
    同人书里原著主角的卡也标着 protagonist，但它只是重要配角（见 is_canon_lead）。"""
    chars = cards(s, book_id, "character")
    if not chars:
        return None
    book = s.get(Book, book_id)
    ff = getattr(book, "fanfic", None) if book is not None else None
    if isinstance(ff, dict):
        p = ff.get("protagonist") if isinstance(ff.get("protagonist"), dict) else {}
        cid = p.get("card_id")
        if cid:
            hit = next((c for c in chars if c.id == cid), None)
            if hit is not None:
                return hit
        for key in ("name", "canon_name"):
            nm = str(p.get(key) or "").strip()
            if nm and (key == "name" or p.get("source") == "canon"):
                hit = next((c for c in chars if c.name == nm), None)
                if hit is not None:
                    return hit
    for c in chars:
        d = c.data or {}
        if d.get("origin") == "oc" and d.get("role") == "protagonist":
            return c
    for c in chars:
        if (c.data or {}).get("role") == "protagonist":
            return c
    return chars[0]


def is_canon_lead(card: Card, prot: Card | None) -> bool:
    """同人书里原著主角的卡（role=protagonist 但不是本书视点主角）：当重要配角写。"""
    return card.type == "character" and (card.data or {}).get("role") == "protagonist" and prot is not None and card.id != prot.id


def pronoun(book: Book) -> str:
    return "她" if book.gender == "female" else "他"


def voice_of(card: Card) -> dict[str, Any]:
    d = card.data or {}
    return {
        "voice": d.get("voice", ""),
        "catchphrases": list(d.get("catchphrases") or []),
        "habits": list(d.get("habits") or []),
        "demeanor": d.get("demeanor", ""),
    }


def committed_chapters(s: Session, book_id: int, before: int | None = None) -> list[Chapter]:
    q = select(Chapter).where(Chapter.book_id == book_id, Chapter.status == "committed")
    if before is not None:
        q = q.where(Chapter.number < before)
    return list(s.exec(q.order_by(Chapter.number)))


def written_chapters(s: Session, book_id: int, before: int | None = None) -> list[Chapter]:
    """v0.17：已经写出正文的章（已提交 + 写好待审批/待提交的草稿），每个章号一份。
    精修范围里的章不提交也要让后面的章看得到前文。"""
    q = select(Chapter).where(Chapter.book_id == book_id)
    if before is not None:
        q = q.where(Chapter.number < before)
    out: dict[int, Chapter] = {}
    for c in s.exec(q.order_by(Chapter.number, Chapter.id)):
        if c.status != "committed" and not (c.content or "").strip():
            continue
        cur = out.get(c.number)
        if cur is None or (cur.status != "committed" and c.status == "committed"):
            out[c.number] = c
    return [out[k] for k in sorted(out)]


def open_foreshadows(s: Session, book_id: int) -> list[Foreshadow]:
    return list(
        s.exec(
            select(Foreshadow)
            .where(Foreshadow.book_id == book_id, Foreshadow.status.in_(["planted", "advancing"]))  # type: ignore[attr-defined]
            .order_by(Foreshadow.planted_ch)
        )
    )


def outline_nodes(s: Session, book_id: int) -> list[OutlineNode]:
    return list(s.exec(select(OutlineNode).where(OutlineNode.book_id == book_id).order_by(OutlineNode.id)))


def get_style(s: Session, book_id: int) -> Style:
    st = s.get(Style, book_id)
    return st if st is not None else Style(book_id=book_id)


def book_context(s: Session, book: Book, with_cards: bool = True) -> str:
    lines = [
        f"书名：{book.title}",
        f"题材：{book.genre}（{GENDER_LABEL.get(book.gender, book.gender)}）",
    ]
    if book.tagline:
        lines.append(f"一句话卖点：{book.tagline}")
    if book.premise:
        lines.append(f"核心设定：{book.premise}")
    if with_cards:
        for c in cards(s, book.id or 0):
            if c.type in ("world", "cheat", "power", "faction", "character"):
                lines.append(f"[{c.type}] {c.name}：{c.summary}")
    if getattr(book, "fanfic", None):  # v0.10 同人：原著卡摘要 + 遵循规则（大纲/写章/设定等所有带书设定的提示词）
        from app.services.fanfic import context_block

        lines.append(context_block(s, book))
    return "\n".join(lines)


def kit_meta(s: Session, book: Book) -> dict[str, Any]:
    """传给 mock 的书级上下文（真实渠道忽略）。"""
    p = protagonist(s, book.id or 0)
    chars = cards(s, book.id or 0, "character")
    villain = next((c.name for c in chars if (c.data or {}).get("role") == "antagonist"), None)
    ally = next((c.name for c in chars if (c.data or {}).get("role") == "ally"), None)
    item = next((c.name for c in cards(s, book.id or 0, "item")), None)
    loc = next((c.name for c in cards(s, book.id or 0, "location")), None)
    return {
        "title": book.title, "genre": book.genre, "gender": book.gender, "premise": book.premise,
        "protagonist": p.name if p else None, "villain": villain, "ally": ally, "item": item, "location": loc,
    }


# v0.18 起名撞车：模型很爱给主角起同一批名字，多本书主角同名读者一眼就腻
OVERUSED_NAMES = ("林烬", "林渊", "林默", "林凡", "陈默", "叶凡", "萧炎", "楚风", "江叙", "沈渊", "顾渊", "苏晚", "苏清", "林晚")


def used_protagonist_names(s: Session, exclude_book_id: int | None = None, limit: int = 30) -> list[str]:
    names: list[str] = []
    for b in s.exec(select(Book)).all():
        if exclude_book_id and b.id == exclude_book_id:
            continue
        try:
            p = protagonist(s, b.id or 0)
        except Exception:  # noqa: BLE001
            p = None
        if p is not None and p.name and p.name not in names:
            names.append(p.name)
    return names[:limit]


def name_note(s: Session, exclude_book_id: int | None = None) -> str:
    used = [n for n in used_protagonist_names(s, exclude_book_id) if n not in OVERUSED_NAMES]
    avoid = "、".join([*OVERUSED_NAMES, *used])
    return (f"\n\n【起名】主角和主要配角的名字要有辨识度、贴合出身和地域，不要用网文里用滥的名字，也不要和本站别的书重名："
            f"{avoid}。姓氏别总用林、陈、苏、沈、顾、叶、萧。"
            "\n【长线】除非想法里写了，别默认用“父母（父亲）是隐藏的传奇、死因有黑幕”当长线，换成主角自己要争的东西。")
