"""v0.9 平台风格档对 lint 的影响（经验值，未在语料上校准）。

- fanqie（番茄）：手机单手刷，短段、短句、对白推进是常态 →
  放宽：≤8 字短句占比、平均句长下限、对话占比上限、单句段瀑布流、群众反应镜头；
  收紧：超过 70 字的段落计为问题（手机上超过 3 行），点名让定点修拆段。
- qidian（起点）/ generic（通用）：沿用原有阈值，不查长段。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import LintThresholds
from app.lint.craft_zh import CROWD_SHOTS_MAX

PLATFORMS = ("fanqie", "qidian", "generic")
WATERFALL_RUN_MAX_DEFAULT = 4


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    waterfall_run_max: int = WATERFALL_RUN_MAX_DEFAULT  # 连续单句成段的段数上限
    crowd_shots_max: int = CROWD_SHOTS_MAX              # 群众/配角反应镜头上限
    long_para_chars: int | None = None                  # 超过这个字数的段落计问题；None 不查
    long_para_fix_max: int = 5                          # 最多点名几个长段让定点修拆分
    merge_short_sentences: bool = True                  # 描写增厚时是否把“短句碎段”合并（番茄档不合并）
    overrides: dict[str, Any] = field(default_factory=dict)  # 覆盖 LintThresholds 的字段

    def thresholds(self, th: LintThresholds) -> LintThresholds:
        return th.model_copy(update=self.overrides) if self.overrides else th


PROFILES: dict[str, PlatformProfile] = {
    "generic": PlatformProfile("generic"),
    "qidian": PlatformProfile("qidian"),
    "fanqie": PlatformProfile(
        "fanqie", waterfall_run_max=8, crowd_shots_max=5, long_para_chars=70, merge_short_sentences=False,
        overrides={"short_sentence_ratio_max": 0.50, "avg_sentence_len_min": 9.0, "dialogue_warn": 0.55},
    ),
}


def get_profile(platform: str | None) -> PlatformProfile:
    return PROFILES.get(platform or "generic", PROFILES["generic"])


def thresholds_for(th: LintThresholds, platform: str | None) -> LintThresholds:
    return get_profile(platform).thresholds(th)
