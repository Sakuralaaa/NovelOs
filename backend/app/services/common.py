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


def cards(s: Session, book_id: int, type_: str | None = None) -> list[Card]:
    q = select(Card).where(Card.book_id == book_id)
    if type_:
        q = q.where(Card.type == type_)
    return list(s.exec(q.order_by(Card.id)))


def protagonist(s: Session, book_id: int) -> Card | None:
    chars = cards(s, book_id, "character")
    for c in chars:
        if (c.data or {}).get("role") == "protagonist":
            return c
    return chars[0] if chars else None


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
            if c.type in ("world", "power", "faction", "character"):
                lines.append(f"[{c.type}] {c.name}：{c.summary}")
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
