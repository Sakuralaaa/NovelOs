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
    "outline": ("outline", "chapter_plan"),
    "expand": ("outline", "chapter_plan"),
    "scene_plan": ("chapter_plan",),
    "writing_scene": ("writing",),
    "review": ("review",),
    "humanize": ("humanize",),
    "thicken": ("humanize", "writing"),
    "summary": (),
    "package": ("package",),
    "style_extract": ("writing",),
    "idea_score": (),
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


@lru_cache
def load_pack(stage: str) -> SkillPack:
    path = _ROOT / "rules" / f"{stage}.md"
    return _parse(path.read_text(encoding="utf-8"), stage)


def all_packs() -> list[SkillPack]:
    return [load_pack(s) for s in STAGES]


@lru_cache
def _template(name: str) -> Template:
    return Template((_ROOT / "prompts" / f"{name}.md").read_text(encoding="utf-8"))


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
