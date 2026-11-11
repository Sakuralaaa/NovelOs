"""全局配置。所有值都可用 NOVELOS_ 前缀的环境变量覆盖。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVELOS_", env_file=".env", extra="ignore")

    data_dir: Path = Path("./data")
    secret: str | None = None  # Fernet 主密钥；为空时自动生成并存入 data_dir/secret.key
    static_dir: Path = Path("/app/static")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    disable_scheduler: bool = False

    # LLM 网关
    llm_timeout: float = 120.0
    llm_retries: int = 2  # 同一渠道失败重试次数，之后切到同角色其他渠道
    image_size: str = "1024x1536"

    # 雷达
    radar_base_url: str = "https://api-lf.fanqiesdk.com/api/novel/channel/homepage/rank/rank_list/v2/"
    radar_side_types: list[int] = [10, 12, 13]
    radar_timeout: float = 10.0
    radar_interval_s: float = 1.0  # 单次刷新内请求间隔
    radar_user_agent: str = (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"
    )

    # 写作
    default_chapter_words: int = 2200
    default_target_words: int = 1_000_000
    font_path: str | None = None  # 封面排版用中文字体

    lint: LintThresholds = LintThresholds()

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
