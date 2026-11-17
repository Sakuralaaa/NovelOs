"""全局配置。所有值都可用 NOVELOS_ 前缀的环境变量覆盖。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LintThresholds(BaseModel):
    """人味 lint 阈值。

    注意：以下全部是经验值，未在番茄同题材人写作品语料上校准（计划 v0.2 用 P10–P90 校准）。
    """

    ai_score_rewrite: float = 45.0  # ai_score 超过该值触发定点重写（经验值，未校准）
    dialogue_warn: float = 0.40  # 对话占比超过 40% 警告（经验值，未校准）
    dialogue_low_warn: float = 0.05  # 对话占比低于 5% 提示（经验值，未校准）
    banned_per_k_warn: float = 2.0  # 每千字 AI 腔命中数超过该值警告（经验值，未校准）
    banned_per_k_max: float = 4.0  # 每千字命中达到该值时该项扣满（经验值，未校准）
    ngram_min: int = 4
    ngram_max: int = 6
    ngram_min_count: int = 3  # 全书出现次数 ≥ 该值才算复用（经验值，未校准）
    ngram_report_max: int = 20
    para_cv_min: float = 0.35  # 段落长度变异系数低于该值视为过于均匀（经验值，未校准）
    punct_per_k_max: float = 4.0  # 每千字破折号/省略号达到该值扣满（经验值，未校准）
    first3_monologue_chars: int = 200  # 前三章无对话长段上限（经验值，未校准）
    avg_sentence_len_min: float = 12.0  # 平均句长低于该值视为“全是短句”（经验值，未校准）
    short_sentence_ratio_max: float = 0.35  # ≤8 字短句占比上限（经验值，未校准）
    bare_dialogue_max: float = 0.5  # 裸对白比例上限：每段对白至少一半配动作/神态（经验值，未校准）
    summary_ratio_max: float = 0.12  # 概述式叙述占比上限（估计值，经验阈值，未校准）
    thicken_max_paragraphs: int = 8  # 单次精修最多改写的段落数


class PlatformLintProfile(BaseModel):
    """v0.9.4：按平台风格档集中的 lint 阈值（番茄档 / 出版档两套）。

    原来散在 humanlint.py、craft_zh.py、platform.py 里的常量都集中到这里；用 NOVELOS_LINT_PROFILES（JSON）可整体覆盖。
    校准记录见 docs/research/lint-calibration-v094.md（样章少，仍是经验值）。
    """

    waterfall_run_max: int = 4            # 连续单句成段（无对白、<waterfall_short_chars 字）的段数上限
    waterfall_short_chars: int = 30       # 单句段短于这个字数才算瀑布流的一段
    crowd_shots_max: int = 3              # 群众/配角反应镜头上限
    long_para_chars: int | None = None    # 超过这个字数的段落算长段；None 不查
    long_para_min_count: int = 3          # 长段至少这么多段才算问题（零星一两段长段是正常排版）
    long_para_min_ratio: float = 0.10     # 且长段占全章段落比例 ≥ 这个值
    long_para_fix_max: int = 3            # 最多点名几个长段让定点修拆分
    merge_short_sentences: bool = True    # 描写增厚时是否把“短句碎段”合并（番茄档不合并）
    intensifier_min_allow: int = 2        # 强化词每词允许次数下限
    intensifier_per_k: float = 0.6        # 强化词每千字允许次数
    dialogue_tic_max: int = 2             # 对白句末口癖（嘛/对吧…）每章上限
    catchphrase_max: int = 1              # 人物卡口头禅每章上限（v0.17：2 → 1）
    habit_max: int = 2                    # v0.17 人物卡习惯动作：同一个每章上限
    weak_adverb_per_k_max: float = 3.0    # 弱化副词每千字上限
    subject_start_max: float = 0.60       # 叙述句以他/她/人名开头的占比上限
    sent_cv_min: float = 0.40             # 句长变异系数下限
    overrides: dict[str, Any] = Field(default_factory=dict)  # 覆盖 LintThresholds 的字段


def default_lint_profiles() -> dict[str, PlatformLintProfile]:
    return {
        # 番茄档：手机单手刷，短段短句、对白推进是常态。v0.9.4 校准：长段 70→100 字且要成片出现才报（见校准文档）
        "fanqie": PlatformLintProfile(
            waterfall_run_max=8, crowd_shots_max=5, long_para_chars=100, long_para_min_count=3, long_para_min_ratio=0.10,
            long_para_fix_max=3, merge_short_sentences=False,
            overrides={"short_sentence_ratio_max": 0.50, "avg_sentence_len_min": 9.0, "dialogue_warn": 0.55},
        ),
        # 出版档（起点 / 通用）：沿用原有阈值，不查长段
        "publish": PlatformLintProfile(),
    }


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVELOS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    secret: str | None = None  # Fernet 主密钥；为空时自动生成并存入 data_dir/secret.key
    # 登录鉴权（见 app/auth.py）
    password: str | None = None  # 登录密码；留空则使用 data/auth.json，首次启动自动生成
    basic_user: str = "novelos"
    basic_password: str | None = None  # 旧版变量，等同于 NOVELOS_PASSWORD
    auth_disabled: bool = False  # 仅限本机开发/测试：关闭登录
    api_key: str | None = None  # 额外的固定 API 密钥（须以 nvk_ 开头）；也可在“设置 → API 密钥”里生成
    llm_trace: bool = True  # 在内存里保留最近的模型调用（提示词与输出），供调试提示词；重启清空
    llm_trace_max: int = 200
    tokens_per_char: float = 1.0  # v0.9.3 成本提示：中文约 1 字≈1 token 的换算系数
    llm_usage_log: bool = True  # v0.9.3 每次模型调用写一条持久用量（llm_usage 表）
    cookie_secure: bool | None = None  # 会话 Cookie 的 Secure 标记；None=按请求是否 HTTPS 自动判断
    static_dir: Path = Path("/app/static")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    disable_scheduler: bool = False

    # LLM 网关
    llm_timeout: float = 120.0
    search_timeout: float = 600.0  # 联网搜索整体上限（多 agent 搜索可能几分钟不出字）
    llm_retries: int = 2  # 同一渠道失败重试次数，之后切到同角色其他渠道
    image_size: str = "1024x1536"

    # 雷达
    radar_base_url: str = "https://api-lf.fanqiesdk.com/api/novel/channel/homepage/rank/rank_list/v2/"
    radar_side_types: list[int] = [10, 12, 13]
    radar_per_board: int = 30  # 网页榜单：每个题材榜取前 N 本（10–100）
    radar_boards: list[str] = ["read", "new"]  # v0.9：read 阅读榜 / new 新书榜
    radar_timeout: float = 10.0
    radar_interval_s: float = 1.0  # 单次刷新内请求间隔
    # v0.9.1：封面缓存与书页详情
    radar_cache_covers: bool = True  # 抓榜完成后在后台预缓存本次快照的封面（失败忽略）
    radar_cover_max_bytes: int = 2 * 1024 * 1024
    radar_cover_timeout: float = 10.0
    radar_detail_ttl_h: float = 24.0  # 书页详情（章节目录、完整简介）缓存时长
    # v0.9.2：风向标日报每榜读前 N 本（3–50）；自动日报生成哪些 scope（/api/radar/config 可改，存库优先）
    radar_report_top_n: int = 30
    radar_report_auto_scopes: list[str] = ["overall"]
    radar_user_agent: str = (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
    )

    # v0.9.1：朱雀 AIGC 文本检测（密钥与开关存在库里，见 /api/settings/zhuque）
    zhuque_default_base_url: str = "https://ai-gateway.edgeone.link"
    zhuque_timeout: float = 30.0
    zhuque_chunk_chars: int = 8000  # 每块最多字数，按段落切块

    # 写作
    default_chapter_words: int = 2200
    default_target_words: int = 1_000_000
    font_path: str | None = None  # 封面排版用中文字体

    lint: LintThresholds = LintThresholds()
    # v0.9.4：平台风格档 → lint 阈值档（fanqie→番茄档，qidian/generic→出版档）
    lint_profiles: dict[str, PlatformLintProfile] = Field(default_factory=default_lint_profiles)
    lint_platform_map: dict[str, str] = {"fanqie": "fanqie", "qidian": "publish", "generic": "publish"}

    @field_validator("cookie_secure", "password", "basic_password", "api_key", mode="before")
    @classmethod
    def _blank_is_none(cls, v):  # docker compose 会把未设置的变量传成空字符串
        return None if isinstance(v, str) and not v.strip() else v

    @property
    def db_path(self) -> Path:
        return self.data_dir / "novelos.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.media_dir.mkdir(parents=True, exist_ok=True)
    return s
