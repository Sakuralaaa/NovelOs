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
    # v0.12 模型单价：{模型名: {"in": 元/百万输入 token, "out": 元/百万输出 token}}，作者手填；没填的模型按 0 计
    prices: Optional[dict[str, Any]] = _json_dict_nullable()
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
    ref: str = ""  # 任务关联的对象，例如 "rank_item:12"（v0.7.1：榜单仿写任务按条目查进行中的任务）
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
    # v0.9：榜单类型 read（阅读榜，30 万字以上）/ new（新书榜，30 万字以下）；旧数据迁移后默认 read
    board: str = "read"
    # v0.9.1：番茄书架同款信息（封面、章节、原文跳转）；旧数据迁移后为空串 / 0 / NULL
    cover_url: str = ""  # 番茄签名封面地址（约 7 天过期），对外通过 /api/radar/cover/{book_id_ext} 缓存代理
    first_chapter_id: str = ""
    last_chapter_id: str = ""
    last_chapter_title: str = ""
    last_update_at: Optional[datetime] = None
    chapter_count: int = 0  # 从最新章标题解析的章号估计；0 表示未知


class TrendReport(SQLModel, table=True):
    """v0.9 风向标日报：基于某个快照，由模型写的结构化日报（scope：overall 或 category:<gender>:<name>）。"""
    id: Optional[int] = Field(default=None, primary_key=True)
    snapshot_id: int = Field(index=True)
    scope: str = Field(default="overall", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    report: Optional[dict[str, Any]] = _json_dict_nullable()
    model: str = ""


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
    # v0.9：平台风格档 fanqie（默认）/ qidian / generic，写作提示词与 lint 阈值按档走
    platform_style: str = "fanqie"
    # v0.9 书测：{variants:[{style,title,subtitle,hook,cover_prompt}], created_at, model, adopted:int|None}
    book_test: Optional[dict[str, Any]] = _json_dict_nullable()
    # v0.9.3 审批模式：auto / review；空串表示没显式设置过（对外按 agent_auto_apply 映射，章节 AI 维持旧行为）
    approval_mode: str = ""
    # v0.10 同人：{source_id, source_title, fidelity, direction, extra_source_ids, notes, copyright_ack_at, attached_at}；None 表示原创书
    fanfic: Optional[dict[str, Any]] = _json_dict_nullable()
    # v0.11 完本模式：serial（连载，默认，旧书迁移后也是 serial）/ wanben（完本）
    mode: str = "serial"
    # v0.11 完本设置：{target_words, chapter_words, batch_size, refine_scope, golden_chapters, refine_ranges,
    #   pause_on_unapproved_refine, auto_continue}；None 表示没设置过（读时按默认值补齐）
    wanben: Optional[dict[str, Any]] = _json_dict_nullable()
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
    # v0.9.3：弃用条目不进任何生成上下文；ref_enabled=false 时不能被 @ 引用；soul 为角色灵魂五维（仅 character）
    status: str = "active"
    ref_enabled: bool = True
    soul: Optional[dict[str, Any]] = _json_dict_nullable()
    # v0.12：锁定后任何 AI 生成、同步、批量改都不能改这张卡（作者手动编辑不受限）；versions 为单卡旧版本，最近的在最后
    locked: bool = False
    versions: list[dict[str, Any]] = _json_list()
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
    locked: bool = False  # v0.12：锁定后 AI 重写、展开、同步、整体重新生成都不能改这个节点


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
    aigc: Optional[dict[str, Any]] = _json_dict_nullable()  # v0.9.1 朱雀 AIGC 检测结果（content_hash 判断是否过期）
    # v0.10 同人章节检查：{"ooc": {...,content_hash}, "overlap": {...,content_hash}}
    fanfic_meta: Optional[dict[str, Any]] = _json_dict_nullable()
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
    # v0.17 文风基准：一段 600–1000 字的正文，写作时放在 system 末尾「照这个语感写」；为空时第 1 章定稿后自动回填
    baseline: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
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


# ------------------------------------------------------------------ v0.9.3

class LlmUsage(SQLModel, table=True):
    """每次模型调用（含 mock）一条的持久用量记录；trace 只在内存，这张表给成本提示和本书用量用。"""
    __tablename__ = "llm_usage"
    id: Optional[int] = Field(default=None, primary_key=True)
    route: str = Field(default="", index=True)  # 角色：planner / writer / reviewer / agent …
    model: str = ""
    book_id: Optional[int] = Field(default=None, index=True)
    kind: str = ""  # 所在任务的 Job.kind；不在任务里为 task 名
    task: str = ""
    in_tokens: int = 0
    out_tokens: int = 0
    ms: int = 0
    estimated: bool = False  # 渠道没回 usage，按字数估算
    created_at: datetime = Field(default_factory=utcnow)


class Teardown(SQLModel, table=True):
    """v0.9.3 拆书工作台：一次拆书的产物。原文不入库，只存产物与原文 8 字片段的指纹（crc32，用于去重比对）。"""
    __tablename__ = "teardown_project"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = ""
    source: str = "paste"  # rank_book / paste / txt
    book_id_ext: Optional[str] = None
    chars: int = 0
    result: Optional[dict[str, Any]] = _json_dict_nullable()
    warnings: list[str] = _json_list()
    fingerprint: list[int] = _json_list()
    names: list[str] = _json_list()  # 去专名用的原书专名（书名、作者、人名等），不对外
    model: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class FanficSource(SQLModel, table=True):
    """v0.10 同人原著资料：从作者导入的原著提炼出的设定卡。原文不入库，只存卡与所取片段的 8 字指纹（crc32）。"""
    __tablename__ = "fanfic_source"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = ""
    source: str = "paste"  # paste / txt / search（v0.11.1 联网取材）
    chars: int = 0  # 实际取用（提炼 + 指纹）的字数
    total_chars: int = 0  # 导入原文总字数
    depth: str = "standard"  # quick / standard / deep：提炼轮数
    focus: list[str] = _json_list()  # 作者指定的重点（角色名/剧情关键词），取材时优先
    cards: Optional[dict[str, Any]] = _json_dict_nullable()  # {characters, world, factions, timeline, scenes}
    warnings: list[str] = _json_list()
    fingerprint: list[int] = _json_list()
    model: str = ""
    # v0.11.1 联网取材：检索来源链接、所用热门模板 id、联网检索轮数（纯联网资料 fingerprint 为空）
    refs: list[str] = _json_list()
    template_id: str = ""
    web_rounds: int = 0
    # v0.15 原著世界库：永久设定条目（[{id, cat, sub, name, summary, detail, tags, order}]）+ 简介 + 标签；同一原著的所有同人书共用
    entries: list[dict[str, Any]] = _json_list()
    intro: str = ""
    tags: list[str] = _json_list()
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ v0.9.4

class JobCheckpoint(SQLModel, table=True):
    """v0.9.4 任务断点：多步任务（写章：拆场景→逐场景写→审稿→摘要）每完成一步写一次，进程重启后可从最后完成的步骤续跑。"""
    __tablename__ = "job_checkpoint"
    job_id: int = Field(primary_key=True)
    kind: str = ""
    book_id: Optional[int] = Field(default=None, index=True)
    stage: str = ""  # 最后完成的步骤名，如 scenes / draft:1（v0.17 整章正文）/ variant:1 / chapter / refined / patched / committed
    state: Optional[dict[str, Any]] = _json_dict_nullable()
    resumes: int = 0  # 已续跑次数
    updated_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ v0.11 完本模式

class WanbenBatch(SQLModel, table=True):
    """完本模式的一批连写：批次范围、状态与批末抽检报告（report）。"""
    __tablename__ = "wanben_batch"
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    job_id: Optional[int] = Field(default=None, index=True)
    seq: int = 1  # 本书第几批（从 1 开始）
    start_no: int = 0  # 计划起始章号
    end_no: int = 0  # 计划结束章号
    # running / done（写满本批）/ stopped（遇到需要作者处理的情况停下）/ paused（作者暂停）/ failed（异常）
    status: str = "running"
    stop_reason: str = ""  # refine_pending / pending_chapter / review_failed / awaiting_adopt / paused / target_reached / error
    message: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    chapter_ids: list[int] = _json_list()
    report: Optional[dict[str, Any]] = _json_dict_nullable()
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class WanbenIteration(SQLModel, table=True):
    """完本模式的章节迭代：每轮对一章产出一个新版本（不落正文），作者对比后采纳或丢弃。"""
    __tablename__ = "wanben_iteration"
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    chapter_id: int = Field(index=True)
    number: int = 0
    job_id: Optional[int] = None
    round: int = 1  # 这一章的第几轮迭代（全局累计）
    method: str = "patch"  # patch（定点修）/ rewrite（整章重写）
    instruction: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    base_content: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    content: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    words: int = 0
    review: Optional[dict[str, Any]] = _json_dict_nullable()
    lint: Optional[dict[str, Any]] = _json_dict_nullable()
    # {before:{overall, reader}, after:{overall, reader}, delta:{overall, reader}}
    scores: Optional[dict[str, Any]] = _json_dict_nullable()
    status: str = "pending"  # pending（待采纳）/ adopted / discarded
    created_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ v0.12 生成档案

class Generation(SQLModel, table=True):
    """每次模型调用（对话 / 生图，含 mock）一条档案：成功、空结果、失败都记，输出全文保留，可收藏、追问、删除。

    追问产生的新结果 parent_id 指向原条；原条不会被覆盖。
    """
    __tablename__ = "generation"
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: Optional[int] = Field(default=None, index=True)
    job_id: Optional[int] = Field(default=None, index=True)
    kind: str = Field(default="", index=True)  # 所在任务的 Job.kind；不在任务里为 task 名
    task: str = ""  # 提示词名（chapter / review / bible …）
    route: str = ""  # 角色：planner / writer / reviewer / image …
    model: str = ""  # 渠道名/模型，mock 为 mock
    status: str = Field(default="ok", index=True)  # ok / empty / failed
    error: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    prompt: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))  # 最后一条作者侧消息（截断）
    output: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    output_words: int = 0
    target_words: int = 0  # 有目标字数的生成（写章等）；0 表示没有
    in_tokens: int = 0
    out_tokens: int = 0
    cost_cny: float = 0.0
    ms: int = 0
    starred: bool = False
    parent_id: Optional[int] = Field(default=None, index=True)
    note: str = ""  # 追问时作者写的要求
    created_at: datetime = Field(default_factory=utcnow, index=True)


# ------------------------------------------------------------------ v0.13 写作笔记

class Note(SQLModel, table=True):
    """书内写作笔记：按目录归类，可置顶；@笔记:标题 可在写章、改写里引用。source 记来源（如脑洞抽卡、神评）。"""
    __tablename__ = "note"
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    folder: str = ""
    title: str = ""
    content: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    tags: list[str] = _json_list()
    pinned: bool = False
    source: Optional[dict[str, Any]] = _json_dict_nullable()
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ v0.13 抽卡立项

class SparkSession(SQLModel, table=True):
    """抽卡立项的一次会话：基本信息 → 世界观 / 主角 / 金手指三轮抽卡 → 立项书。state 整份存 JSON。"""
    __tablename__ = "spark_session"
    id: Optional[int] = Field(default=None, primary_key=True)
    state: Optional[dict[str, Any]] = _json_dict_nullable()
    idea_id: Optional[int] = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ------------------------------------------------------------------ v0.16 一键成书

class AutoRun(SQLModel, table=True):
    """一键成书的一次运行：选题/同人建好的书 → 设定 → 完本规划 → 连写到完结。每本书同一时间只有一个未结束的运行。"""
    __tablename__ = "auto_run"
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    job_id: Optional[int] = None  # 当前（或最近一次）后台任务
    # running / waiting（等作者拍板）/ paused / stopped（出错、额度、渠道全挂）/ done
    status: str = "running"
    stage: str = "setup"  # setup / bible / plan / write / done
    stop_reason: str = ""
    message: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    settings: Optional[dict[str, Any]] = _json_dict_nullable()
    state: Optional[dict[str, Any]] = _json_dict_nullable()  # 内部断点：批次状态、已复盘的卷等
    stats: Optional[dict[str, Any]] = _json_dict_nullable()  # healed / forced / retries / llm_failures / chapters / volumes_reviewed
    events: list[dict[str, Any]] = _json_list()  # 运行日志 [{at, kind, text}]，只留最近 200 条
    flags: list[dict[str, Any]] = _json_list()  # 待看清单 [{chapter_id, number, reason, at, resolved}]
    guidance: list[dict[str, Any]] = _json_list()  # 作者导向 [{text, from_chapter, to_chapter, source, at}]
    started_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = None


class AutoDecision(SQLModel, table=True):
    """一键成书的决策点：开篇确认、卷末下一卷走向。全自动时按推荐项自动拍板，关键时刻模式停下等作者点选。"""
    __tablename__ = "auto_decision"
    id: Optional[int] = Field(default=None, primary_key=True)
    book_id: int = Field(index=True)
    run_id: int = Field(index=True)
    kind: str = "volume"  # opening / volume
    volume: int = 0  # 卷末决策：刚写完的卷序号
    title: str = ""
    context: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    options: list[dict[str, Any]] = _json_list()  # [{title, summary, crisis, closure, turns:[], why}]
    recommended: int = 0
    status: str = "pending"  # pending / answered / auto
    choice: Optional[int] = None
    custom: str = Field(default="", sa_column=Column(Text, nullable=False, default=""))
    created_at: datetime = Field(default_factory=utcnow)
    answered_at: Optional[datetime] = None
