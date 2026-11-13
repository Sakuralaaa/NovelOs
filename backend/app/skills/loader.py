"""写作技能层：按环节加载 markdown 规则包（带来源/协议元数据）与提示词模板。"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from string import Template

_ROOT = Path(__file__).parent
STAGES = ("ideation", "bible", "outline", "chapter_plan", "writing", "review", "humanize", "package")

# 各任务挂载哪些规则包（system 提示词）
TASK_SKILLS: dict[str, tuple[str, ...]] = {
    "ideation": ("ideation",),
    "bible": ("bible",),
    "card_suggest": ("bible",),
    "outline": ("outline", "chapter_plan"),
    "expand": ("outline", "chapter_plan"),
    "scene_plan": ("chapter_plan",),
    "writing_scene": ("writing",),
    "review": ("review",),
    "reader": (),
    "humanize": ("humanize",),
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
    "chapter_rewrite": ("writing", "humanize"),
    "foreshadow_plan": ("outline",),
    "teardown": (),
    "teardown_deep": (),
    "reskin": ("ideation",),
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


def system_prompt(task: str, extra: str = "") -> str:
    parts = [SYSTEM_BASE]
    for stage in TASK_SKILLS.get(task, ()):
        parts.append(load_pack(stage).body)
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)
