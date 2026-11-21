"""写作技能层：按环节加载 markdown 规则包（带来源/协议元数据）与提示词模板。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from string import Template

_ROOT = Path(__file__).parent
STAGES = ("ideation", "bible", "outline", "chapter_plan", "writing", "craft_check", "review", "humanize", "package", "trend_report")

# 各任务挂载哪些规则包（system 提示词）
TASK_SKILLS: dict[str, tuple[str, ...]] = {
    "ideation": ("ideation",),
    "bible": ("bible",),
    "card_suggest": ("bible",),
    "adopt_bible": ("bible",),
    "sparks": ("bible",),
    "outline": ("outline", "chapter_plan"),
    "expand": ("outline", "chapter_plan"),
    "scene_plan": ("chapter_plan",),
    "writing_chapter": ("writing",),   # v0.17 整章一次写：写手只读正面写法
    "writing_scene": ("writing",),     # 旧任务名（v0.16 及以前逐场景写），保留给提示词覆盖与测试
    "chapter_state": (),               # v0.17 写完后从正文抽状态账本与变更声明
    "pairwise": (),                    # v0.17 两版候选成对比较
    "review": ("review", "craft_check"),
    "reader": (),
    "humanize": ("humanize", "craft_check"),
    "thicken": ("humanize", "writing"),
    "summary": (),
    "package": ("package",),
    "cover_prompt": ("package",),
    "style_extract": ("writing",),
    "idea_score": (),
    "idea_revise": ("ideation",),
    "idea_field": ("ideation",),
    "book_revise": ("ideation",),
    "bible_propose": ("bible",),
    "outline_node": ("outline",),
    "outline_sync": ("outline",),
    "chapter_sync": ("chapter_plan",),  # v0.17.1 写章前按上一章实写校正章纲
    "chapter_rewrite": ("writing",),
    "foreshadow_plan": ("outline",),
    "teardown": ("teardown",),
    "teardown_deep": ("teardown",),
    "reskin": ("ideation",),
    "idea_seed": ("ideation",),
    "idea_organize": ("ideation",),
    "idea_fusion": ("ideation",),
    "trend_report": ("trend_report",),
    "book_test": ("package",),
    "radar_book_ai": ("package",),
    "polish_voice": ("humanize", "writing"),
    "field_ai": ("bible",),
    "character_soul": ("bible",),
    "teardown_project": ("teardown",),
}


@dataclass
class SkillSource:
    repo: str
    license: str
    usage: str


@dataclass
class SkillPack:
    stage: str
    title: str
    version: str
    body: str
    sources: list[SkillSource] = field(default_factory=list)


def _parse(text: str, stage: str) -> SkillPack:
    meta: dict[str, str] = {}
    sources: list[SkillSource] = []
    body = text
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        in_sources = False
        for line in fm.strip().splitlines():
            if line.strip() == "sources:":
                in_sources = True
                continue
            if in_sources and line.strip().startswith("- "):
                parts = [p.strip() for p in line.strip()[2:].split("|")]
                parts += [""] * (3 - len(parts))
                sources.append(SkillSource(parts[0], parts[1], parts[2]))
                continue
            in_sources = False
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
    return SkillPack(
        stage=meta.get("stage", stage),
        title=meta.get("title", stage),
        version=meta.get("version", "0.1"),
        body=body.strip(),
        sources=sources,
    )


# ---------- 线上覆盖：data/prompt_overrides/{prompts|rules}/<name>.md ----------
# 用来在真实模型上调提示词而不用重新发版；删掉覆盖文件即恢复内置版本。
KINDS = ("prompts", "rules")


def _override_dir(kind: str) -> Path:
    from app.config import get_settings

    return get_settings().data_dir / "prompt_overrides" / kind


def _check(kind: str, name: str) -> None:
    if kind not in KINDS:
        raise ValueError("kind 只能是 prompts 或 rules")
    if name not in builtin_names(kind):
        raise ValueError(f"没有这个{'提示词' if kind == 'prompts' else '规则包'}：{name}")


def builtin_names(kind: str) -> list[str]:
    return sorted(p.stem for p in (_ROOT / kind).glob("*.md"))


def default_text(kind: str, name: str) -> str:
    _check(kind, name)
    return (_ROOT / kind / f"{name}.md").read_text(encoding="utf-8")


def override_text(kind: str, name: str) -> str | None:
    _check(kind, name)
    p = _override_dir(kind) / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.is_file() else None


def effective_text(kind: str, name: str) -> str:
    o = override_text(kind, name)
    return o if o is not None else default_text(kind, name)


def set_override(kind: str, name: str, text: str) -> None:
    _check(kind, name)
    d = _override_dir(kind)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".{name}.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(d / f"{name}.md")
    _clear_caches()


def clear_override(kind: str, name: str) -> bool:
    _check(kind, name)
    p = _override_dir(kind) / f"{name}.md"
    existed = p.is_file()
    if existed:
        p.unlink()
    _clear_caches()
    return existed


def _clear_caches() -> None:
    load_pack.cache_clear()
    _template.cache_clear()


@lru_cache
def load_pack(stage: str) -> SkillPack:
    return _parse(effective_text("rules", stage), stage)


def all_packs() -> list[SkillPack]:
    return [load_pack(s) for s in STAGES]


@lru_cache
def _template(name: str) -> Template:
    return Template(effective_text("prompts", name))


def render(name: str, **values: object) -> str:
    return _template(name).safe_substitute({k: str(v) for k, v in values.items()})


SYSTEM_BASE = (
    "你是一位熟悉番茄小说读者口味的中文网文作者兼编辑。"
    "严格遵守下列规则；要求输出 JSON 时只输出 JSON，不加解释、不加代码块标记。"
)
# v0.17：写正文的任务用这一句开头，避免「只输出 JSON」和「输出正文」打架
PROSE_BASE = (
    "你是一位熟悉番茄小说读者口味的中文网文作者。"
    "照下面的写法写小说正文，输出的就是可以直接发布的正文。"
)
PROSE_TASKS = ("writing_chapter", "writing_scene", "chapter_rewrite", "polish_voice")


# v0.9 平台风格档：规则包里用 <!-- platform:fanqie --> … <!-- /platform --> 包住只对某个平台生效的小节
# v0.11：新增可选档 duanju（短剧分镜）。它继承番茄档的平台小节（短段、快切），
# 另外在写作/细纲类任务上叠加 rules/duanju.md 规则包（PLATFORM_PACKS）。
PLATFORMS = ("fanqie", "qidian", "generic", "duanju")
PLATFORM_LABEL = {"fanqie": "番茄", "qidian": "起点", "generic": "通用", "duanju": "短剧分镜"}
PLATFORM_BASE: dict[str, str] = {"duanju": "fanqie"}          # 档 → 继承哪个档的 <!-- platform:x --> 小节
PLATFORM_PACKS: dict[str, str] = {"duanju": "duanju"}          # 档 → 额外叠加的规则包（rules/<name>.md）
# 叠加规则包只挂在用到 writing / chapter_plan 规则的任务上（写场景、扩写、细纲、改写、增厚、润色…）
PLATFORM_PACK_STAGES = ("writing", "chapter_plan")
_PLATFORM_BLOCK = re.compile(r"<!--\s*platform:([a-z,]+)\s*-->(.*?)<!--\s*/platform\s*-->", re.S)


def platform_filter(body: str, platform: str | None) -> str:
    """只保留当前平台的小节（可写 platform:fanqie,qidian）；platform 为空时去掉全部平台小节。
    v0.11：duanju 档同时保留它继承的番茄小节（PLATFORM_BASE）。"""
    wanted = {platform, PLATFORM_BASE.get(platform or "")} - {None, ""}

    def keep(m: re.Match[str]) -> str:
        names = m.group(1).split(",")
        return m.group(2).strip("\n") if wanted and any(n in wanted for n in names) else ""
    return re.sub(r"\n{3,}", "\n\n", _PLATFORM_BLOCK.sub(keep, body)).strip()


def _db_stage_skills_text(stage: str, platform: str | None, book_id: int | None = None) -> str | None:
    """v0.20：优先从可插拔技能库读取指定环节（stage）生效的技能文本。
    若存在旧版磁盘覆盖文件（/api/prompts/rules/<stage>）或技能库尚未初始化，返回 None 回退到磁盘规则。"""
    if stage in STAGES and override_text("rules", stage) is not None:
        return None
    try:
        from sqlmodel import select
        from app.db import session_scope
        from app.models.tables import Skill
        from app.services.skills_store import active_skills_for_book, render_skills_text

        with session_scope() as s:
            if s.exec(select(Skill.id).limit(1)).first() is None:
                return None
            if book_id is not None:
                rows = active_skills_for_book(s, book_id, stage)
            else:
                rows = list(s.exec(
                    select(Skill).where(Skill.enabled == True, Skill.is_default == True, Skill.stage == stage)  # noqa: E712
                    .order_by(Skill.id)
                ).all())
            return render_skills_text(rows, platform=platform)
    except Exception:  # noqa: BLE001
        return None


def _db_slug_text(slug: str, platform: str | None) -> str | None:
    """从技能库按 slug 读取单条内置规则（如 builtin-rule-duanju）；若未初始化则返回 None 回退磁盘。"""
    try:
        from sqlmodel import select
        from app.db import session_scope
        from app.models.tables import Skill
        from app.services.skills_store import render_skills_text

        with session_scope() as s:
            if s.exec(select(Skill.id).limit(1)).first() is None:
                return None
            sk = s.exec(select(Skill).where(Skill.slug == slug)).first()
            if sk is None:
                return None
            if not sk.enabled:
                return ""
            return render_skills_text([sk], platform=platform)
    except Exception:  # noqa: BLE001
        return None


def system_prompt(task: str, extra: str = "", platform: str | None = None, book_id: int | None = None) -> str:
    parts = [PROSE_BASE if task in PROSE_TASKS else SYSTEM_BASE]
    stages = TASK_SKILLS.get(task, ())
    for stage in stages:
        db_txt = _db_stage_skills_text(stage, platform, book_id=book_id)
        if db_txt is not None:
            txt = db_txt
        elif stage in STAGES:
            txt = platform_filter(load_pack(stage).body, platform)
        else:
            txt = ""
        if txt:
            parts.append(txt)
    pack = PLATFORM_PACKS.get(platform or "")
    if pack and any(st in PLATFORM_PACK_STAGES for st in stages):  # v0.11 短剧分镜档：叠加专属规则包
        if override_text("rules", pack) is not None:
            ptxt = platform_filter(load_pack(pack).body, platform)
        else:
            db_ptxt = _db_slug_text(f"builtin-rule-{pack}", platform)
            ptxt = db_ptxt if db_ptxt is not None else platform_filter(load_pack(pack).body, platform)
        if ptxt:
            parts.append(ptxt)
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)
