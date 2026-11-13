"""数据库表（SQLModel）。底账唯一来源：facts / foreshadow / chapters；摘要等为派生。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_list() -> Any:
    return Field(default_factory=list, sa_column=Column(JSON, nullable=False))


def _json_dict_nullable() -> Any:
    return Field(default=None, sa_column=Column(JSON, nullable=True))


class KV(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: Optional[Any] = _json_dict_nullable()


class Channel(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    base_url: str
    api_key_enc: str = ""
    models: list[str] = _json_list()
    enabled: bool = True
    # 接口格式：openai（Chat Completions）/ responses（OpenAI Responses）/ anthropic（Messages）/ gemini（generateContent）
    api_format: str = "openai"
    created_at: datetime = Field(default_factory=utcnow)


class TokenUsage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: Optional[int] = None
    model: str = ""
    role: str = ""
    task: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str
    status: str = "queued"
    progress: int = 0
    message: str = ""
    result: Optional[Any] = _json_dict_nullable()
    error: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    book_id: Optional[int] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RadarSnapshot(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    taken_at: datetime = Field(default_factory=utcnow)
    source: str = "mock"
    items_count: int = 0
    version: str = ""  # 番茄榜单版本号（rankVersion），同版本不重复入库


class RankItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(index=True)
    book_id_ext: str
    title: str
    author: str = ""
    category: str = ""
    rank: int = 0
    rank_diff: int = 0  # 较上一版名次变化，正数为上升
    read_count: int = 0
    word_count: int = 0
    abstract: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    tags: list[str] = _json_list()
    gender: str = "male"


class RankTeardown(SQLModel, table=True):
    """v0.7 榜单仿写：一本榜单书的拆解（只学结构）。teardown 按简介等元信息拆；deep 按作者贴的试读原文拆。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    rank_item_id: int = Field(index=True)
    book_id_ext: str = ""
    title: str = ""
    teardown: Optional[dict[str, Any]] = _json_dict_nullable()
    deep: Optional[dict[str, Any]] = _json_dict_nullable()
    created_at: datetime = Field(default_factory=utcnow)


class Book(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = "未命名作品"
    genre: str = ""
    gender: str = "male"
    tagline: str = ""
    premise: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    status: str = "idea"
    target_words: int = 1_000_000
    chapter_words: int = 2200
    cover_url: Optional[str] = None
    # 书名/一句话简介/核心设定的旧版本（最近的在最后），用于撤回
    versions: list[dict[str, Any]] = _json_list()
    # 本书追加的禁用套路 [{name, keywords:[]}]，与全局列表合并使用
    banned_tropes: list[dict[str, Any]] = _json_list()
    # v0.5：本书 Agent 的改动直接写入（仍留快照/旧版本可撤回）；删除类操作不受此开关影响，永远要确认
    agent_auto_apply: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Idea(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: Optional[int] = None
    title: str
    logline: str = ""
    selling_points: list[str] = _json_list()
    hook: str = ""
    expectations: list[str] = _json_list()
    endgame: str = ""
    arc: list[str] = _json_list()
    genre: str = ""
    gender: str = "male"
    scores: Optional[dict[str, Any]] = _json_dict_nullable()
    versions: list[dict[str, Any]] = _json_list()  # 修改前的旧版本，最近的在最后
    # v0.7：来源（榜单仿写时为 {kind:"reskin", rank_item_id, ref_title, kept[], changed[], self_check[], overlap, warnings[]}）
    source: Optional[dict[str, Any]] = _json_dict_nullable()
    chosen: bool = False
    created_at: datetime = Field(default_factory=utcnow)


class Card(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    type: str
    name: str
    summary: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    data: Optional[dict[str, Any]] = _json_dict_nullable()
    known_by: list[str] = _json_list()
    updated_at: datetime = Field(default_factory=utcnow)


class Fact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    entity_id: Optional[int] = None
    key: str
    value: str
    from_chapter: int = 0
    to_chapter: Optional[int] = None
    visibility: str = "author"


class OutlineNode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    parent_id: Optional[int] = None
    level: str
    # 对 chapter 级节点，order 即全书章号；其余级别为兄弟节点序号（从 1 开始）
    order: int = 1
    title: str = ""
    summary: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    beats: Optional[dict[str, Any]] = _json_dict_nullable()
    status: str = "planned"
    chapter_id: Optional[int] = None
    versions: list[dict[str, Any]] = _json_list()  # 标题/概要的旧版本，最近的在最后


class Chapter(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    number: int
    title: str = ""
    content: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    words: int = 0
    status: str = "draft"
    review: Optional[dict[str, Any]] = _json_dict_nullable()
    lint: Optional[dict[str, Any]] = _json_dict_nullable()
    summary: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    changes: Optional[dict[str, Any]] = _json_dict_nullable()  # 待提交的 ChangeSet（草稿，未入底账）
    # 多版本：[{id, content, words, lint, review_overall, review, changes, warnings}]；对外只暴露合约字段
    variants: list[dict[str, Any]] = _json_list()
    outline_node_id: Optional[int] = None
    history: list[dict[str, Any]] = _json_list()  # 改写/精修前的旧正文 [{content, title, label, at}]，用于撤回
    updated_at: datetime = Field(default_factory=utcnow)


class Foreshadow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    desc: str
    # planned（计划中，还没写进正文）/ planted / advancing / resolved / dropped
    status: str = "planted"
    planted_ch: int = 0
    last_ch: int = 0
    resolved_ch: Optional[int] = None
    tier: str = ""  # short / mid / long
    plan_plant_ch: Optional[int] = None
    plan_resolve_ch: Optional[int] = None
    note: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    source: str = "chapter"  # chapter（提交章节时登记）/ ai（AI 规划）/ manual（作者手动）/ outline（来自细纲）


class BibleSnapshot(SQLModel, table=True):
    """设定库整体快照：批量改设定前自动保存，可一键回滚。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    note: str = ""
    cards: list[dict[str, Any]] = _json_list()
    created_at: datetime = Field(default_factory=utcnow)


class Package(SQLModel, table=True):
    book_id: int = Field(primary_key=True)
    titles: list[dict[str, Any]] = _json_list()
    blurb: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    tags: list[str] = _json_list()
    cover_prompt: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    covers: list[str] = _json_list()
    chosen_cover: Optional[str] = None


class Style(SQLModel, table=True):
    book_id: int = Field(primary_key=True)
    sample_text: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    voice_notes: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    pov: str = "third"
    tone: str = ""
    extracted: Optional[dict[str, Any]] = _json_dict_nullable()


# ------------------------------------------------------------------ v0.5：每本书专属 Agent

class AgentSession(SQLModel, table=True):
    """一本书的一条 Agent 会话（一本书可以有多条，可清空）。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    title: str = "新对话"
    running_job_id: Optional[int] = None  # 正在跑的 agent_run 任务
    stop_requested: bool = False
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class AgentMessage(SQLModel, table=True):
    """会话里的一条消息：user / assistant（可带 tool_calls）/ tool（工具结果）/ notice（系统提示，如步数上限）。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(index=True)
    book_id: int = Field(index=True)
    role: str
    content: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    tool_calls: list[dict[str, Any]] = _json_list()  # [{id, name, arguments(dict)}]
    tool_call_id: str = ""
    name: str = ""  # tool 消息：工具名
    summary: str = ""  # tool 消息：给作者看的一句话结果
    status: str = "ok"  # ok / error
    proposal_ids: list[int] = _json_list()
    job_ids: list[int] = _json_list()
    created_at: datetime = Field(default_factory=utcnow)


class AgentProposal(SQLModel, table=True):
    """Agent 改动类工具产出的提案：作者采纳才写入（或书级「自动采纳」时直接写入），写入后可撤回。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    session_id: int = Field(index=True)
    message_id: Optional[int] = None
    kind: str
    title: str = ""
    summary: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    payload: Optional[dict[str, Any]] = _json_dict_nullable()
    # pending / applied / rejected / reverted / running（长任务进行中）/ failed
    status: str = "pending"
    destructive: bool = False  # 删除类：永远要作者确认
    needs_review: bool = False  # 有设定冲突等，需要逐条审阅
    auto_applied: bool = False
    result: Optional[dict[str, Any]] = _json_dict_nullable()
    error: str = ""
    job_id: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
