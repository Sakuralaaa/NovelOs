"""平台风格档对 lint 的影响。

v0.9：fanqie（番茄）放宽短句/短段/对白占比/瀑布流/群众镜头，收紧长段；qidian / generic 沿用原有阈值。
v0.9.4：阈值集中到 app.config（Settings.lint_profiles：番茄档 fanqie / 出版档 publish 两套），
按 Settings.lint_platform_map 选用（fanqie→番茄档，qidian/generic→出版档）。这里只负责把配置变成 PlatformProfile。
校准记录：docs/research/lint-calibration-v094.md。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import LintThresholds, PlatformLintProfile, get_settings

PLATFORMS = ("fanqie", "qidian", "generic")
WATERFALL_RUN_MAX_DEFAULT = 4


@dataclass(frozen=True)
class PlatformProfile:
    name: str
    tier: str = "publish"                               # v0.9.4：阈值档 fanqie（番茄档）/ publish（出版档）
    waterfall_run_max: int = WATERFALL_RUN_MAX_DEFAULT  # 连续单句成段的段数上限
    waterfall_short_chars: int = 30
    crowd_shots_max: int = 3                            # 群众/配角反应镜头上限
    long_para_chars: int | None = None                  # 超过这个字数的段落算长段；None 不查
    long_para_min_count: int = 3
    long_para_min_ratio: float = 0.10
    long_para_fix_max: int = 3                          # 最多点名几个长段让定点修拆分
    merge_short_sentences: bool = True                  # 描写增厚时是否把“短句碎段”合并（番茄档不合并）
    intensifier_min_allow: int = 2
    intensifier_per_k: float = 0.6
    dialogue_tic_max: int = 2
    catchphrase_max: int = 1
    habit_max: int = 2
    weak_adverb_per_k_max: float = 3.0
    subject_start_max: float = 0.60
    sent_cv_min: float = 0.40
    overrides: dict[str, Any] = field(default_factory=dict)  # 覆盖 LintThresholds 的字段

    def thresholds(self, th: LintThresholds) -> LintThresholds:
        return th.model_copy(update=self.overrides) if self.overrides else th

    def long_para_flagged(self, long_count: int, para_count: int) -> bool:
        """长段要成片出现才算问题：段数 ≥ long_para_min_count 且占比 ≥ long_para_min_ratio。"""
        if not self.long_para_chars or long_count <= 0:
            return False
        return long_count >= self.long_para_min_count and long_count / max(para_count, 1) >= self.long_para_min_ratio

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _build(name: str, tier: str, cfg: PlatformLintProfile) -> PlatformProfile:
    return PlatformProfile(name=name, tier=tier, **cfg.model_dump())


def profiles() -> dict[str, PlatformProfile]:
    st = get_settings()
    cfgs = st.lint_profiles or {}
    out: dict[str, PlatformProfile] = {}
    for plat in PLATFORMS:
        tier = st.lint_platform_map.get(plat, "publish")
        cfg = cfgs.get(tier) or cfgs.get("publish") or PlatformLintProfile()
        out[plat] = _build(plat, tier, cfg)
    return out


class _Profiles(dict):  # 兼容旧代码 PROFILES["fanqie"]：每次读配置
    def __getitem__(self, k: str) -> PlatformProfile:
        return profiles()[k]

    def get(self, k: str, default: Any = None) -> Any:  # type: ignore[override]
        return profiles().get(k, default)


PROFILES: dict[str, PlatformProfile] = _Profiles()


def get_profile(platform: str | None) -> PlatformProfile:
    ps = profiles()
    if platform == "duanju":  # v0.11 短剧分镜档沿用番茄档的 lint 阈值
        platform = "fanqie"
    return ps.get(platform or "generic", ps["generic"])


def thresholds_for(th: LintThresholds, platform: str | None) -> LintThresholds:
    return get_profile(platform).thresholds(th)
