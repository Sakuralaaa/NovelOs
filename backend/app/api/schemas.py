"""请求体模型与输出序列化（严格对齐 docs/API_CONTRACT.md）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.llm.crypto import decrypt, mask
from app.models.tables import (
    Book, Card, Channel, Chapter, Fact, Foreshadow, Idea, Job, OutlineNode, Package, RadarSnapshot, RankItem, Style,
)
from app.services import common


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    d = dt.astimezone(timezone.utc)
    # 手工拼 ISO8601，避免依赖 isoformat/strftime 的本地化行为
    return (f"{d.year:04d}-{d.month:02d}-{d.day:02d}T{d.hour:02d}:{d.minute:02d}:{d.second:02d}"
            f".{d.microsecond // 1000:03d}+00:00")


# ------------------------------------------------------------------ 请求体

Gender = Literal["male", "female"]


class ChannelIn(BaseModel):
    name: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key: str = ""
    models: list[str] = []
    enabled: bool = True
    api_format: Literal["openai", "responses", "anthropic", "gemini"] = "openai"


class ChannelUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    enabled: bool | None = None
    api_format: Literal["openai", "responses", "anthropic", "gemini"] | None = None


class ModelFetchIn(BaseModel):
    base_url: str = Field(min_length=1)
    api_key: str = ""
    channel_id: int | None = None  # 编辑已有渠道且没重填 key 时，用库里存的 key
    api_format: Literal["openai", "responses", "anthropic", "gemini"] = "openai"


class RoutingIn(BaseModel):
    planner: str | None = None
    writer: str | None = None
    reviewer: str | None = None
    search: str | None = None
    image_mode: Literal["images", "chat"] | None = None
    embedding: str | None = None
    image: str | None = None


class WritingSettingsIn(BaseModel):
    auto_adopt_best: bool | None = None
    auto_commit: bool | None = None
    default_variants: int | None = Field(default=None, ge=1, le=3)


class RadarConfigIn(BaseModel):
    enabled: bool
    daily_hour: int = Field(ge=0, le=23)


class BookCreate(BaseModel):
    title: str | None = None
    genre: str = ""
    gender: Gender = "male"
    premise: str | None = None


class BookPatch(BaseModel):
    title: str | None = None
    genre: str | None = None
    gender: Gender | None = None
    tagline: str | None = None
    status: Literal["idea", "bible", "outline", "writing", "packaging", "done"] | None = None
    target_words: int | None = Field(default=None, ge=1000)
    chapter_words: int | None = Field(default=None, ge=500, le=10000)


class IdeasGenerate(BaseModel):
    genre: str | None = None
    gender: Gender | None = None
    from_trends: bool = False
    count: int = Field(default=3, ge=1, le=10)


class IdeaRevise(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    route: str | None = None  # "渠道id:模型"，不填走策划路由


class IdeaSuggest(BaseModel):
    field: Literal["title", "genre", "logline", "selling_points", "hook", "expectations", "arc", "endgame"]
    instruction: str = Field(default="", max_length=1000)
    route: str | None = None
    draft: dict[str, Any] | None = None


class IdeaUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=40)
    genre: str | None = None
    logline: str | None = None
    selling_points: list[str] | None = None
    hook: str | None = None
    expectations: list[str] | None = None
    arc: list[str] | None = None
    endgame: str | None = None


CardType = Literal["world", "power", "faction", "character", "item", "location"]


class CardIn(BaseModel):
    type: CardType
    name: str = Field(min_length=1)
    summary: str = ""
    data: dict[str, Any] = {}
    known_by: list[str] = []


class CardUpdate(BaseModel):
    type: CardType | None = None
    name: str | None = None
    summary: str | None = None
    data: dict[str, Any] | None = None
    known_by: list[str] | None = None


class OutlineUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    beats: dict[str, Any] | None = None
    status: Literal["planned", "expanded", "written"] | None = None
    order: int | None = None


class ChapterUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class WriteNextIn(BaseModel):
    variants: int = Field(default=1, ge=1, le=3)


class WriteBatchIn(BaseModel):
    count: int = Field(default=3, ge=1, le=10)
    variants: int | None = Field(default=None, ge=1, le=3)


class AdoptVariantIn(BaseModel):
    variant_id: int


class PackageUpdate(BaseModel):
    titles: list[dict[str, Any]] | None = None
    blurb: str | None = None
    tags: list[str] | None = None
    cover_prompt: str | None = None
    chosen_cover: str | None = None


class CoversIn(BaseModel):
    prompt: str | None = None
    n: int = Field(default=4, ge=1, le=4)


class StyleIn(BaseModel):
    sample_text: str = ""
    voice_notes: str = ""
    pov: Literal["first", "third"] = "third"
    tone: str = ""


# ------------------------------------------------------------------ 输出

def job_out(j: Job) -> dict[str, Any]:
    return {
        "id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message,
        "result": j.result, "error": j.error, "book_id": j.book_id,
        "created_at": iso(j.created_at), "updated_at": iso(j.updated_at),
    }


def channel_out(c: Channel) -> dict[str, Any]:
    try:
        masked = mask(decrypt(c.api_key_enc))
    except ValueError:
        masked = "****（无法解密）"
    return {"id": c.id, "name": c.name, "base_url": c.base_url, "api_key_masked": masked,
            "models": list(c.models or []), "enabled": c.enabled, "api_format": c.api_format or "openai"}


def snapshot_out(sn: RadarSnapshot) -> dict[str, Any]:
    return {"id": sn.id, "taken_at": iso(sn.taken_at), "source": sn.source, "items_count": sn.items_count, "version": sn.version}


def rank_item_out(r: RankItem) -> dict[str, Any]:
    return {"book_id_ext": r.book_id_ext, "title": r.title, "author": r.author, "category": r.category, "rank": r.rank,
            "read_count": r.read_count, "word_count": r.word_count, "abstract": r.abstract, "tags": list(r.tags or []),
            "gender": r.gender, "rank_diff": r.rank_diff}


def book_out(s: Session, b: Book) -> dict[str, Any]:
    return {
        "id": b.id, "title": b.title, "genre": b.genre, "gender": b.gender, "tagline": b.tagline, "status": b.status,
        "target_words": b.target_words, "chapter_words": b.chapter_words, "cover_url": b.cover_url,
        "created_at": iso(b.created_at), "updated_at": iso(b.updated_at), "stats": common.book_stats(s, b.id or 0),
    }


def idea_out(i: Idea) -> dict[str, Any]:
    sc = i.scores or {}
    return {"id": i.id, "book_id": i.book_id, "title": i.title, "logline": i.logline,
            "selling_points": list(i.selling_points or []), "hook": i.hook, "genre": i.genre,
            "expectations": list(i.expectations or []), "endgame": i.endgame, "arc": list(i.arc or []), "issue": str(sc.get("issue") or ""),
            "scores": {k: sc.get(k, 0) for k in ("heat", "novelty", "fit", "overall")}, "chosen": i.chosen,
            "versions": len(i.versions or []), "last_instruction": str((i.versions or [{}])[-1].get("instruction") or "") if i.versions else ""}


def card_out(c: Card) -> dict[str, Any]:
    return {"id": c.id, "book_id": c.book_id, "type": c.type, "name": c.name, "summary": c.summary,
            "data": c.data or {}, "known_by": list(c.known_by or []), "updated_at": iso(c.updated_at)}


def fact_out(f: Fact) -> dict[str, Any]:
    return {"id": f.id, "book_id": f.book_id, "entity_id": f.entity_id, "key": f.key, "value": f.value,
            "from_chapter": f.from_chapter, "to_chapter": f.to_chapter, "visibility": f.visibility}


def node_out(n: OutlineNode) -> dict[str, Any]:
    return {"id": n.id, "book_id": n.book_id, "parent_id": n.parent_id, "level": n.level, "order": n.order,
            "title": n.title, "summary": n.summary, "beats": n.beats, "status": n.status, "chapter_id": n.chapter_id}


LINT_KEYS = ("ai_score", "dialogue_ratio", "repeated_ngrams", "banned_hits", "warnings",
             "avg_sentence_len", "short_sentence_ratio", "bare_dialogue_ratio", "summary_ratio")


def lint_out(l: dict[str, Any] | None) -> dict[str, Any] | None:
    if not l:
        return None
    defaults: dict[str, Any] = {"repeated_ngrams": [], "banned_hits": [], "warnings": []}
    return {k: l.get(k, defaults.get(k, 0)) for k in LINT_KEYS}


def review_out(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if not r:
        return None
    return {"scores": r.get("scores", {}), "issues": r.get("issues", []), "passed": bool(r.get("passed"))}


def chapter_out(c: Chapter, with_content: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": c.id, "book_id": c.book_id, "number": c.number, "title": c.title, "words": c.words, "status": c.status,
        "review": review_out(c.review), "lint": lint_out(c.lint), "updated_at": iso(c.updated_at),
        "changes": c.changes if isinstance(c.changes, dict) else None,
        "variants": [
            {"id": v.get("id"), "content": v.get("content", "") if with_content else "", "words": v.get("words", 0),
             "lint": lint_out(v.get("lint")), "review_overall": v.get("review_overall", 0)}
            for v in (c.variants or [])
        ],
    }
    if with_content:
        out["content"] = c.content
    else:
        for v in out["variants"]:
            v.pop("content", None)
    return out


def foreshadow_out(f: Foreshadow) -> dict[str, Any]:
    return {"id": f.id, "book_id": f.book_id, "desc": f.desc, "status": f.status, "planted_ch": f.planted_ch,
            "last_ch": f.last_ch, "resolved_ch": f.resolved_ch}


def package_out(book_id: int, p: Package | None) -> dict[str, Any]:
    if p is None:
        return {"book_id": book_id, "titles": [], "blurb": "", "tags": [], "cover_prompt": "", "covers": [], "chosen_cover": None}
    return {"book_id": book_id, "titles": [{"title": t.get("title", ""), "score": t.get("score", 0)} for t in p.titles or []],
            "blurb": p.blurb, "tags": list(p.tags or []), "cover_prompt": p.cover_prompt, "covers": list(p.covers or []),
            "chosen_cover": p.chosen_cover}


def style_out(st: Style) -> dict[str, Any]:
    return {"sample_text": st.sample_text, "voice_notes": st.voice_notes, "pov": st.pov, "tone": st.tone,
            "extracted": st.extracted}
