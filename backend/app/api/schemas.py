"""请求体模型与输出序列化（严格对齐 docs/API_CONTRACT.md）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

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
    prices: dict[str, dict[str, float]] = {}


class ChannelUpdate(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    models: list[str] | None = None
    enabled: bool | None = None
    api_format: Literal["openai", "responses", "anthropic", "gemini"] | None = None
    prices: dict[str, dict[str, float]] | None = None  # v0.12：{模型: {in, out, image}}，元/百万 token、元/张


def clean_prices(p: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for m, v in (p or {}).items():
        if not str(m).strip() or not isinstance(v, dict):
            continue
        row = {k: round(max(0.0, float(v.get(k) or 0)), 6) for k in ("in", "out", "image") if v.get(k) not in (None, "")}
        row = {k: x for k, x in row.items() if x}
        if row:
            out[str(m).strip()] = row
    return out


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
    agent: str | None = None


class WritingSettingsIn(BaseModel):
    auto_adopt_best: bool | None = None
    auto_commit: bool | None = None
    default_variants: int | None = Field(default=None, ge=1, le=3)
    # v0.9.4
    fix_mid_before_commit: bool | None = None  # 提交前自动修 continuity/retention 类 mid 问题（默认开）
    auto_rereview: bool | None = None  # 自动应用审稿补丁后重审一次（默认开）
    llm_timeout: int | None = Field(default=None, ge=60, le=1800)  # v0.18.2 单次模型调用等待上限（秒）
    llm_retries: int | None = Field(default=None, ge=0, le=5)  # v0.18.2 同一渠道失败重试次数


class BookWritingSettingsIn(BaseModel):
    """v0.9.4 书级开关：true/false 覆盖全局；null 跟随全局。未出现的字段不改。"""
    fix_mid_before_commit: bool | None = None
    auto_rereview: bool | None = None


class RadarBookAiIn(BaseModel):
    """v0.9.1 单书 AI 灵感：title 书名 / cover 封面提示词 / blurb 简介；n 默认 5（cover 默认 3），1–10。"""
    kind: Literal["title", "cover", "blurb"]
    n: int | None = Field(default=None, ge=1, le=10)


class ZhuqueSettingsIn(BaseModel):
    """v0.9.1 朱雀检测设置，局部更新：不传的项不改；zhuque_api_key 传空串清除；zhuque_base_url 传空串恢复默认。"""
    zhuque_api_key: str | None = Field(default=None, max_length=500)
    zhuque_base_url: str | None = Field(default=None, max_length=300)
    zhuque_auto_check: bool | None = None


class AigcDetectIn(BaseModel):
    text: str = Field(min_length=1, max_length=200_000)
    is_merge: bool = True


class ChapterAigcIn(BaseModel):
    is_merge: bool = True


class RadarConfigIn(BaseModel):
    enabled: bool
    daily_hour: int = Field(ge=0, le=23)
    auto_report: bool | None = None  # v0.9：刷新成功后自动生成风向标日报；不传表示不改


class RadarReportConfigIn(BaseModel):
    """v0.9.2：日报配置（GET/PUT /api/radar/report/config）；不传的项不改。"""
    radar_report_top_n: int | None = Field(default=None, ge=3, le=50)  # 每榜读前 N 本
    radar_report_auto_scopes: list[str] | None = Field(default=None, max_length=8)  # 自动日报 scope 列表（需 auto_report 开）


class TrendReportIn(BaseModel):
    """scope = overall / board:<g>:<read|new> / category:<g>:<read|new>:<题材> / category:<g>:<题材>（旧，视为 read）；
    top_n 每个榜取前 N 本（3–50，不传用配置 radar_report_top_n，默认 30）。"""
    scope: str = "overall"
    top_n: int | None = Field(default=None, ge=3, le=50)


# ------------------------------------------------------------------ v0.9.2：种子立项 / 一键整理 / 多本熔炉

SeedSourceType = Literal["trend_report", "rank_book", "paste", "fusion", "manual"]


class SeedSourceIn(BaseModel):
    type: SeedSourceType = "manual"
    ref: str | None = Field(default=None, max_length=200)
    report_id: int | None = None
    book_id_ext: str | None = Field(default=None, max_length=40)


class IdeaSeedIn(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    logline: str = Field(min_length=1, max_length=500)
    protagonist: str | None = Field(default=None, max_length=300)
    mechanism: str | None = Field(default=None, max_length=300)
    opening: str | None = Field(default=None, max_length=500)
    selling_points: list[str] | None = Field(default=None, max_length=8)
    genre: str | None = Field(default=None, max_length=30)
    gender: Gender | None = None
    source: SeedSourceIn = Field(default_factory=SeedSourceIn)
    expand: bool = False


class IdeaOrganizeIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    genre: str | None = Field(default=None, max_length=30)
    gender: Gender | None = None


class FusionRefIn(BaseModel):
    book_id_ext: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=60)
    text: str | None = Field(default=None, max_length=40000)  # 去空白后 ≤20000 字，服务端再查
    weight: float = Field(default=1.0, gt=0, le=100)


class IdeaFusionIn(BaseModel):
    refs: list[FusionRefIn] = Field(min_length=1, max_length=3)
    notes: str | None = Field(default=None, max_length=1000)
    n: int = Field(default=3, ge=1, le=5)


class ImitateExtractIn(BaseModel):
    text: str = Field(min_length=1)
    filename: str | None = None


PlatformStyle = Literal["fanqie", "qidian", "generic", "duanju"]  # v0.11：duanju 短剧分镜（可选档）


class FanficSpec(BaseModel):
    """v0.10 同人书设置（建书时 fanfic 字段 / POST /books/{id}/fanfic 共用）。"""
    source_id: int
    fidelity: Literal["strict", "moderate", "loose"] = "moderate"
    direction: str = Field(default="canon_fill", max_length=40)  # 取值见 GET /fanfic/directions
    extra_source_ids: list[int] = Field(default_factory=list, max_length=9)
    notes: str = Field(default="", max_length=1000)
    # v0.13 三步立项
    protagonist: dict[str, Any] | None = None  # {source: canon|oc, oc_type, name, brief, canon_name, entry_event}
    pov: str | None = None
    slots: dict[str, str] = Field(default_factory=dict)


class BookCreate(BaseModel):
    title: str | None = None
    genre: str = ""
    gender: Gender = "male"
    premise: str | None = None
    platform_style: PlatformStyle = "fanqie"
    fanfic: FanficSpec | None = None  # v0.10 同人建书；给了就必须 copyright_ack=true
    copyright_ack: bool = False
    # v0.13：建书时直接定篇幅与模式
    target_words: int | None = Field(default=None, ge=10_000, le=20_000_000)
    chapter_words: int | None = Field(default=None, ge=500, le=10_000)
    mode: Literal["serial", "wanben"] | None = None
    volume_chapters: int | None = Field(default=None, ge=5, le=500)


class BookPatch(BaseModel):
    title: str | None = None
    genre: str | None = None
    gender: Gender | None = None
    tagline: str | None = None
    status: Literal["idea", "bible", "outline", "writing", "packaging", "done"] | None = None
    target_words: int | None = Field(default=None, ge=1000)
    chapter_words: int | None = Field(default=None, ge=500, le=10000)
    premise: str | None = None
    banned_tropes: list[dict[str, Any]] | None = None
    agent_auto_apply: bool | None = None
    platform_style: PlatformStyle | None = None
    approval_mode: Literal["auto", "review"] | None = None  # v0.9.3


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


CardType = Literal["world", "cheat", "power", "faction", "character", "item", "location"]


SOUL_KEYS = ("desire", "fear", "wound", "belief", "voice")
SOUL_LABEL = {"desire": "欲望", "fear": "恐惧", "wound": "伤痕", "belief": "信念", "voice": "说话方式"}


class SoulIn(BaseModel):
    """v0.9.3 角色灵魂五维；每项可选，传空串清空。"""
    desire: str | None = Field(default=None, max_length=500)
    fear: str | None = Field(default=None, max_length=500)
    wound: str | None = Field(default=None, max_length=500)
    belief: str | None = Field(default=None, max_length=500)
    voice: str | None = Field(default=None, max_length=500)


class CardIn(BaseModel):
    type: CardType
    name: str = Field(min_length=1)
    summary: str = ""
    data: dict[str, Any] = {}
    known_by: list[str] = []
    status: Literal["active", "deprecated"] = "active"
    ref_enabled: bool = True
    soul: SoulIn | None = None


class CardSuggest(BaseModel):
    instruction: str = Field(default="", max_length=1000)
    route: str | None = None
    card_id: int | None = None
    field: str | None = None  # summary / voice / catchphrases / habits / demeanor / name / data.<键>；不填改整张
    draft: dict[str, Any] = {}


class CardUpdate(BaseModel):
    type: CardType | None = None
    name: str | None = None
    summary: str | None = None
    data: dict[str, Any] | None = None
    known_by: list[str] | None = None
    status: Literal["active", "deprecated"] | None = None
    ref_enabled: bool | None = None
    soul: SoulIn | None = None
    locked: bool | None = None


def merge_soul(old: dict[str, Any] | None, patch: SoulIn | dict[str, Any] | None) -> dict[str, str] | None:
    """按键合并五维：只改传了的键；空串清空；全空返回 None。"""
    cur = {k: str((old or {}).get(k) or "") for k in SOUL_KEYS}
    if patch is not None:
        p = patch.model_dump(exclude_unset=True) if isinstance(patch, BaseModel) else dict(patch)
        for k in SOUL_KEYS:
            if k in p and p[k] is not None:
                cur[k] = str(p[k]).strip()
    return cur if any(cur.values()) else None


def soul_out(c: Card) -> dict[str, str] | None:
    if c.type != "character":
        return None
    return {k: str((c.soul or {}).get(k) or "") for k in SOUL_KEYS}


class OutlineUpdate(BaseModel):
    title: str | None = None
    summary: str | None = None
    beats: dict[str, Any] | None = None
    status: Literal["planned", "expanded", "written"] | None = None
    order: int | None = None
    locked: bool | None = None  # v0.12：锁定后 AI 不能改
    instruction: str | None = Field(default=None, max_length=1000)  # 记进旧版本的说明：采纳 AI 建议时传作者要求


# ------------------------------------------------------------------ v0.4：按要求让 AI 改

class AiAsk(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    route: str | None = None


class BookInfoApply(BaseModel):
    title: str | None = Field(default=None, max_length=40)
    tagline: str | None = None
    premise: str | None = None
    instruction: str = Field(default="", max_length=1000)


class ImpactIn(BaseModel):
    terms: list[str] = Field(default_factory=list, max_length=20)


class SyncIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    terms: list[str] = Field(default_factory=list, max_length=20)
    replacements: dict[str, str] = Field(default_factory=dict)
    targets: list[Literal["bible", "outline"]] = Field(default_factory=lambda: ["bible", "outline"])
    route: str | None = None


class BibleProposeIn(BaseModel):
    mode: Literal["rewrite", "add", "optimize"]
    instruction: str = Field(default="", max_length=1000)
    route: str | None = None


class BibleOp(BaseModel):
    op: Literal["create", "update", "delete"]
    card_id: int | None = None
    card: dict[str, Any] | None = None


class BibleApplyIn(BaseModel):
    mode: Literal["rewrite", "add", "optimize", "sync"] = "add"
    instruction: str = Field(default="", max_length=1000)
    ops: list[BibleOp] = Field(default_factory=list)
    facts: list[dict[str, Any]] = Field(default_factory=list)


class OutlineApplyItem(BaseModel):
    node_id: int
    title: str | None = None
    summary: str | None = None
    beats: dict[str, Any] | None = None


class OutlineApplyIn(BaseModel):
    items: list[OutlineApplyItem]
    instruction: str = Field(default="", max_length=1000)


class ChapterRewriteIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    route: str | None = None
    scope: Literal["all", "selection"] = "all"
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)


class ChapterApplyIn(BaseModel):
    content: str
    label: str = Field(default="按要求改写前", max_length=60)


ForeshadowStatus = Literal["planned", "planted", "advancing", "resolved", "dropped"]


class ForeshadowIn(BaseModel):
    desc: str = Field(min_length=1, max_length=300)
    status: ForeshadowStatus | None = None
    planted_ch: int | None = Field(default=None, ge=0)
    resolved_ch: int | None = Field(default=None, ge=0)
    tier: str | None = None
    plan_plant_ch: int | None = Field(default=None, ge=0)
    plan_resolve_ch: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class ForeshadowPatch(BaseModel):
    desc: str | None = Field(default=None, max_length=300)
    status: ForeshadowStatus | None = None
    planted_ch: int | None = Field(default=None, ge=0)
    last_ch: int | None = Field(default=None, ge=0)
    resolved_ch: int | None = Field(default=None, ge=0)
    tier: str | None = None
    plan_plant_ch: int | None = Field(default=None, ge=0)
    plan_resolve_ch: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=1000)


class ForeshadowPlanIn(BaseModel):
    instruction: str = Field(default="", max_length=1000)
    route: str | None = None
    count: int = Field(default=5, ge=1, le=10)


class ForeshadowBatchIn(BaseModel):
    items: list[dict[str, Any]] = Field(max_length=20)
    attach: bool = True


class TropeItem(BaseModel):
    name: str = Field(default="", max_length=40)
    keywords: list[str] = Field(default_factory=list)


class TropesIn(BaseModel):
    banned: list[TropeItem] = Field(default_factory=list, max_length=40)


class DetropeIn(BaseModel):
    route: str | None = None


class BookTestAdoptIn(BaseModel):
    """v0.9 书测：选第 index 组（0–3）。fields：title→书名，subtitle→一句话简介，hook→包装简介，cover_prompt→包装封面提示词。"""
    index: int = Field(ge=0, le=9)
    fields: list[Literal["title", "subtitle", "hook", "cover_prompt"]] = Field(default_factory=lambda: ["title", "subtitle"])


class PatchApplyIn(BaseModel):
    """v0.9：要应用的审稿补丁下标（review.patches[].index）。"""
    indices: list[int] = Field(min_length=1, max_length=20)


class ChapterUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


class WriteNextIn(BaseModel):
    variants: int = Field(default=1, ge=1, le=3)
    instruction: str = Field(default="", max_length=1000)  # v0.9.3：本章额外要求，可含 @条目名


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
    title_mode: Literal["model", "overlay"] = "model"


class CoverPromptRevise(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)
    current: str | None = None
    route: str | None = None


class CoverDelete(BaseModel):
    url: str


class StyleIn(BaseModel):
    sample_text: str = ""
    baseline: Optional[str] = None  # v0.17 文风基准；不传保持原样
    voice_notes: str = ""
    pov: Literal["first", "third"] = "third"
    tone: str = ""


class TeardownDeepIn(BaseModel):
    """v0.7：作者贴的试读原文（≤20000 字，超限 400）。"""
    text: str


# ------------------------------------------------------------------ 输出

def job_out(j: Job) -> dict[str, Any]:
    return {
        "id": j.id, "kind": j.kind, "status": j.status, "progress": j.progress, "message": j.message,
        "result": j.result, "error": j.error, "book_id": j.book_id, "ref": j.ref or "",
        "created_at": iso(j.created_at), "updated_at": iso(j.updated_at),
    }


def channel_out(c: Channel) -> dict[str, Any]:
    try:
        masked = mask(decrypt(c.api_key_enc))
    except ValueError:
        masked = "****（无法解密）"
    return {"id": c.id, "name": c.name, "base_url": c.base_url, "api_key_masked": masked,
            "models": list(c.models or []), "enabled": c.enabled, "api_format": c.api_format or "openai",
            "prices": dict(c.prices or {})}


def snapshot_out(sn: RadarSnapshot) -> dict[str, Any]:
    return {"id": sn.id, "taken_at": iso(sn.taken_at), "source": sn.source, "items_count": sn.items_count, "version": sn.version}


def rank_item_out(r: RankItem) -> dict[str, Any]:
    return {"id": r.id, "book_id_ext": r.book_id_ext, "title": r.title, "author": r.author, "category": r.category, "rank": r.rank,
            "read_count": r.read_count, "word_count": r.word_count, "abstract": r.abstract, "tags": list(r.tags or []),
            "gender": r.gender, "rank_diff": r.rank_diff, "board": r.board if r.board in ("read", "new") else "read",
            **rank_item_shelf(r)}


def rank_item_shelf(r: RankItem) -> dict[str, Any]:
    """v0.9.1 书架字段：cover 为本站封面代理相对路径（没有封面地址时 null）；source_url / first_chapter_url 是番茄原文链接
    （示例数据的非数字 id 没有书页，为 null）。"""
    from urllib.parse import quote

    from app.radar.fanqie_web import reader_url, source_url

    return {"cover": f"/api/radar/cover/{quote(r.book_id_ext, safe='')}" if (r.cover_url or "").strip() else None,
            "source_url": source_url(r.book_id_ext), "first_chapter_url": reader_url(r.first_chapter_id),
            "chapter_count": int(r.chapter_count or 0), "last_chapter_title": r.last_chapter_title or "",
            "last_update_at": iso(r.last_update_at), "first_chapter_id": r.first_chapter_id or "", "last_chapter_id": r.last_chapter_id or ""}


def book_out(s: Session, b: Book) -> dict[str, Any]:
    vs = list(b.versions or [])
    return {
        "id": b.id, "title": b.title, "genre": b.genre, "gender": b.gender, "tagline": b.tagline, "status": b.status,
        "target_words": b.target_words, "chapter_words": b.chapter_words, "cover_url": b.cover_url,
        "created_at": iso(b.created_at), "updated_at": iso(b.updated_at), "stats": common.book_stats(s, b.id or 0),
        "premise": b.premise, "versions": len(vs), "last_instruction": str(vs[-1].get("instruction") or "") if vs else "",
        "banned_tropes": list(b.banned_tropes or []), "agent_auto_apply": bool(b.agent_auto_apply),
        "platform_style": b.platform_style if b.platform_style in ("fanqie", "qidian", "generic", "duanju") else "fanqie",
        "has_book_test": bool((b.book_test or {}).get("variants")),
        "approval_mode": common.approval_mode(b), "approval_mode_explicit": b.approval_mode in ("auto", "review"),
        "fanfic": b.fanfic or None,  # v0.10 同人设置；原创书为 null
    }



def idea_out(i: Idea, trope_list: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    sc = i.scores or {}
    return {"id": i.id, "book_id": i.book_id, "title": i.title, "logline": i.logline,
            "selling_points": list(i.selling_points or []), "hook": i.hook, "genre": i.genre,
            "expectations": list(i.expectations or []), "endgame": i.endgame, "arc": list(i.arc or []), "issue": str(sc.get("issue") or ""),
            "scores": {k: sc.get(k, 0) for k in ("heat", "novelty", "fit", "overall")}, "score_detail": dict(sc.get("detail") or {}), "chosen": i.chosen,
            "versions": len(i.versions or []), "last_instruction": str((i.versions or [{}])[-1].get("instruction") or "") if i.versions else "",
            "trope_hits": _idea_tropes(i, trope_list), "source": i.source}


def _idea_tropes(i: Idea, tl: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    from app.db import session_scope
    from app.services import tropes

    if tl is None:
        with session_scope() as s:
            tl = tropes.global_tropes(s)
    return tropes.detect(" ".join([i.title, i.logline, i.hook, i.endgame, *(i.selling_points or []), *(i.expectations or []), *(i.arc or [])]), tl)


def card_out(c: Card, trope_list: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    out = {"id": c.id, "book_id": c.book_id, "type": c.type, "name": c.name, "summary": c.summary,
           "data": c.data or {}, "known_by": list(c.known_by or []), "updated_at": iso(c.updated_at),
           "status": c.status if c.status in ("active", "deprecated") else "active",
           "ref_enabled": bool(c.ref_enabled) if c.ref_enabled is not None else True, "soul": soul_out(c),
           "locked": bool(getattr(c, "locked", False)), "versions": len(c.versions or [])}
    if trope_list is not None:
        from app.services import tropes

        out["trope_hits"] = tropes.detect_obj({"name": c.name, "summary": c.summary, "data": c.data or {}}, trope_list)
    return out


def fact_out(f: Fact) -> dict[str, Any]:
    return {"id": f.id, "book_id": f.book_id, "entity_id": f.entity_id, "key": f.key, "value": f.value,
            "from_chapter": f.from_chapter, "to_chapter": f.to_chapter, "visibility": f.visibility}


def node_out(n: OutlineNode) -> dict[str, Any]:
    vs = list(n.versions or [])
    return {"id": n.id, "book_id": n.book_id, "parent_id": n.parent_id, "level": n.level, "order": n.order,
            "title": n.title, "summary": n.summary, "beats": n.beats, "status": n.status, "chapter_id": n.chapter_id,
            "versions": len(vs), "last_instruction": str(vs[-1].get("instruction") or "") if vs else "",
            "locked": bool(getattr(n, "locked", False))}


LINT_KEYS = ("ai_score", "dialogue_ratio", "repeated_ngrams", "banned_hits", "warnings",
             "avg_sentence_len", "short_sentence_ratio", "bare_dialogue_ratio", "summary_ratio",
             # v0.6 手艺类
             "intensifiers", "cliche_similes", "measure_errors", "crowd_shots", "dialogue_tics", "catchphrases", "fix_targets",
             # v0.9 平台风格档：platform（fanqie/qidian/generic）、long_paragraphs（超长段落数）
             "platform", "long_paragraphs",
             # v0.9.4：lint_tier（fanqie 番茄档 / publish 出版档）、numeric_conflicts（数值一致性问题，带位置）
             "lint_tier", "numeric_conflicts")


def lint_out(l: dict[str, Any] | None) -> dict[str, Any] | None:
    if not l:
        return None
    defaults: dict[str, Any] = {"repeated_ngrams": [], "banned_hits": [], "warnings": [], "intensifiers": [], "cliche_similes": [],
                                "measure_errors": [], "dialogue_tics": [], "catchphrases": [], "fix_targets": [], "platform": "generic",
                                "lint_tier": "publish", "numeric_conflicts": []}
    return {k: l.get(k, defaults.get(k, 0)) for k in LINT_KEYS}


def review_out(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if not r:
        return None
    out = {"scores": r.get("scores", {}), "issues": r.get("issues", []), "passed": bool(r.get("passed"))}
    if r.get("reader"):
        out["reader"] = r["reader"]  # v0.8.5：读者视角打分之前被这里丢掉了
    # v0.9：审稿补丁 [{index, original, improved, reason, issue_ref, severity, applied}] 与应用记录
    out["patches"] = list(r.get("patches") or [])
    out["patch_log"] = list(r.get("patch_log") or [])
    # v0.9.4：补丁后重审记录、high 仍在的标记、提交前修中等问题记录
    out["rereview"] = r.get("rereview")
    out["flagged"] = bool(r.get("flagged"))
    out["flag_reason"] = r.get("flag_reason") or ""
    out["pre_commit_fix"] = r.get("pre_commit_fix")
    out["pairwise"] = r.get("pairwise")  # v0.17 多候选成对比较记录
    out["heal"] = r.get("heal")          # v0.17 一键成书自愈记录
    return out


def chapter_out(c: Chapter, with_content: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": c.id, "book_id": c.book_id, "number": c.number, "title": c.title, "words": c.words, "status": c.status,
        "review": review_out(c.review), "lint": lint_out(c.lint), "updated_at": iso(c.updated_at),
        "changes": c.changes if isinstance(c.changes, dict) else None,
        "variants": [
            {"id": v.get("id"), "content": v.get("content", "") if with_content else "", "words": v.get("words", 0),
             "lint": lint_out(v.get("lint")), "review_overall": v.get("review_overall", 0),
             "picked": v.get("picked")}  # v0.17 多候选：成对比较选中的那版为 true，落选为 false，没比较过为 null
            for v in (c.variants or [])
        ],
    }
    # v0.9.1 朱雀检测结果；列表（不带正文）里去掉逐段 segments
    if isinstance(c.aigc, dict):
        from app.services.zhuque import content_hash

        a = c.aigc if with_content else {k: v for k, v in c.aigc.items() if k != "segments"}
        out["aigc"] = {**a, "stale": a.get("content_hash") != content_hash(c.content)}  # 正文改过 → 结果过期
    else:
        out["aigc"] = None
    hist = list(c.history or [])
    out["history"] = len(hist)
    out["last_history_label"] = str(hist[-1].get("label") or "") if hist else ""
    if with_content:
        out["content"] = c.content
    else:
        for v in out["variants"]:
            v.pop("content", None)
    return out


def foreshadow_out(f: Foreshadow) -> dict[str, Any]:
    return {"id": f.id, "book_id": f.book_id, "desc": f.desc, "status": f.status, "planted_ch": f.planted_ch,
            "last_ch": f.last_ch, "resolved_ch": f.resolved_ch, "tier": f.tier or "", "plan_plant_ch": f.plan_plant_ch,
            "plan_resolve_ch": f.plan_resolve_ch, "note": f.note or "", "source": f.source or "chapter"}


def package_out(book_id: int, p: Package | None) -> dict[str, Any]:
    if p is None:
        return {"book_id": book_id, "titles": [], "blurb": "", "tags": [], "cover_prompt": "", "covers": [], "chosen_cover": None}
    return {"book_id": book_id, "titles": [{"title": t.get("title", ""), "score": t.get("score", 0)} for t in p.titles or []],
            "blurb": p.blurb, "tags": list(p.tags or []), "cover_prompt": p.cover_prompt, "covers": list(p.covers or []),
            "chosen_cover": p.chosen_cover}


def style_out(st: Style) -> dict[str, Any]:
    return {"sample_text": st.sample_text, "baseline": st.baseline or "", "voice_notes": st.voice_notes, "pov": st.pov, "tone": st.tone,
            "extracted": st.extracted}
