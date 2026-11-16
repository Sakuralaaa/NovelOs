// 与 novelos/docs/API_CONTRACT.md 一一对应
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted'
export interface Job {
  id: number
  kind: string
  status: JobStatus
  progress: number
  message: string
  result: Record<string, any> | null
  error: string | null
  book_id: number | null
  /** 任务关联的对象，例如 `rank_item:12`（v0.7.1 榜单仿写任务） */
  ref?: string
  created_at: string
  updated_at: string
}

export interface Channel {
  id: number
  name: string
  base_url: string
  api_key_masked: string
  models: string[]
  enabled: boolean
  api_format: ApiFormat
}
export type ApiFormat = 'openai' | 'responses' | 'anthropic' | 'gemini'
export interface ChannelInput {
  name: string
  base_url: string
  api_key?: string
  models: string[]
  enabled?: boolean
  api_format?: ApiFormat
}
export type RouteKey = 'planner' | 'writer' | 'reviewer' | 'search' | 'embedding' | 'image' | 'agent'
export type ImageMode = 'images' | 'chat'
export type Routing = Record<RouteKey, string | null> & { image_mode?: ImageMode }

export type Gender = 'male' | 'female'
export interface RankItem {
  /** v0.7：榜单条目 id（拆解/仿写接口用） */
  id?: number
  book_id_ext: string
  title: string
  author: string
  category: string
  rank: number
  rank_diff?: number
  read_count: number
  word_count: number
  abstract: string
  tags: string[]
  gender: Gender
  /** v0.9：阅读榜 / 新书榜（旧数据为 read） */
  board?: RankBoard
  // ---- v0.9.1 书架卡片 ----
  /** 封面相对路径（如 /api/radar/cover/{book_id_ext}），null 时用占位封面 */
  cover?: string | null
  /** 番茄书页 */
  source_url?: string | null
  first_chapter_url?: string | null
  /** 0 = 未知 */
  chapter_count?: number
  last_chapter_title?: string | null
  last_update_at?: string | null
  /** 番茄章节 itemId，可能为空串 */
  first_chapter_id?: string
  last_chapter_id?: string
}
/** v0.9.1：榜单书详情（抽屉） */
export interface RadarChapterLink { title: string; item_id: string; url: string }
export interface RadarBookDetail {
  item: RankItem
  chapter_total: number | null
  abstract: string
  chapters_head: RadarChapterLink[]
  chapters_tail: RadarChapterLink[]
  fetched_at: string
  detail_error: string | null
  cached?: boolean
}
export type RadarAiKind = 'title' | 'cover' | 'blurb'
export interface RadarAiResult {
  kind: RadarAiKind
  candidates: ({ title: string; why: string } | { prompt: string; style: string } | { blurb: string; hook: string })[]
  dropped: number
  warnings?: string[]
}
export type RankBoard = 'read' | 'new'
export interface RadarSnapshot {
  id: number
  taken_at: string
  source: 'app' | 'web' | 'mock'
  items_count: number
  version?: string
}
export interface TrendTopic {
  category: string
  heat: number
  books: number
  rising: number
  sample_titles: string[]
}
export interface RadarConfig {
  enabled: boolean
  daily_hour: number
  /** v0.9：刷新成功后自动生成风向标日报（PUT 不传表示不改） */
  auto_report?: boolean
}
/** v0.9.2：GET/PUT /api/radar/report/config（自动日报开关仍是 RadarConfig.auto_report） */
export interface RadarReportConfig {
  /** 风向标读取每榜前 N 本（后端 3–50，默认 30） */
  radar_report_top_n: number
  /** 刷新后自动生成的风向标范围，如 overall / board:male:read */
  radar_report_auto_scopes: string[]
}

// ---------- v0.9 风向标日报 ----------
export interface TrendHotWord { word: string; why: string; examples: string[] }
export interface TrendIdeaHook { title: string; pitch: string }
export interface TrendBoard {
  board: string; overview: string; reader_mood: string; opportunity: string; writing_tips: string; idea_hooks: TrendIdeaHook[]
  /** v0.9.2：后端给字符串（可能为空），兼容数组 */
  risks?: string | string[]
}
/** v0.9.2 灵感卡：主角/机制/开局 = 最小立项单元 */
export interface TrendInspiration {
  title: string; logline: string; protagonist?: string; mechanism?: string; opening?: string; selling_points?: string[]; board?: string
}
export interface TrendPlotDevice { name: string; desc: string }
export interface TrendTitlePattern { pattern: string; examples: string[] }
export interface TrendReportBody {
  hot_words: TrendHotWord[]
  boards: TrendBoard[]
  open_directions: string[]
  title_patterns: TrendTitlePattern[]
  pitfalls: string[]
  warnings: string[]
  // ---- v0.9.2（旧报告可能缺）----
  headline?: string
  summary?: string
  inspirations?: TrendInspiration[]
  opening_hooks?: string[]
  plot_devices?: TrendPlotDevice[]
  writing_advice?: string
  risk_alerts?: string[]
  meta?: { top_n?: number; books?: number; books_read?: number; [k: string]: any }
  inputs?: { top_n?: number; books?: number; boards?: Record<string, number>; new_entries?: Record<string, number>; prev_snapshot_id?: number | null }
}
export interface TrendReport {
  id: number
  snapshot_id: number
  scope: string
  created_at: string
  model: string
  stale: boolean
  snapshot: { id: number; taken_at: string; source: RadarSnapshot['source']; version?: string; items_count: number } | null
  /** full=false 的历史列表没有 report，改为 hot_words */
  report?: TrendReportBody
  hot_words?: string[]
}

export type BookStatus = 'idea' | 'bible' | 'outline' | 'writing' | 'packaging' | 'done'
export interface Book {
  id: number
  title: string
  genre: string
  gender: Gender
  tagline: string
  status: BookStatus
  target_words: number
  chapter_words: number
  cover_url: string | null
  created_at: string
  updated_at: string
  stats: { chapters: number; words: number; foreshadow_open: number }
  /** v0.4：核心设定、旧版本数、本书追加的禁用套路 */
  premise?: string
  versions?: number
  last_instruction?: string
  banned_tropes?: Trope[]
  /** v0.5：本书 Agent 的改动直接写入（仍可撤回；删除类永远要确认） */
  agent_auto_apply?: boolean
  /** v0.9：平台风格档（默认 fanqie）、是否做过书测 */
  platform_style?: PlatformStyle
  has_book_test?: boolean
  /** v0.9.3：AI 改动自动采纳 / 逐条审批 */
  approval_mode?: ApprovalMode
  approval_mode_explicit?: boolean
}
export type PlatformStyle = 'fanqie' | 'qidian' | 'generic'

// ---------- v0.9 书测 ----------
export interface BookTestVariant { style: string; title: string; subtitle: string; hook: string; cover_prompt: string }
export type BookTestField = 'title' | 'subtitle' | 'hook' | 'cover_prompt'
export interface BookTest {
  book_id: number
  variants: BookTestVariant[]
  warnings: string[]
  created_at: string
  model: string
  adopted: number | null
  adopted_fields: BookTestField[]
}

export interface Trope { name: string; keywords: string[] }
export interface TropeHit { name: string; hits: string[] }

export interface Idea {
  id: number
  book_id: number | null
  title: string
  logline: string
  selling_points: string[]
  hook: string
  expectations?: string[]
  endgame?: string
  arc?: string[]
  issue?: string
  genre: string
  scores: { heat: number; novelty: number; fit: number; overall: number }
  score_detail?: Record<string, number>
  chosen: boolean
  versions?: number
  last_instruction?: string
  trope_hits?: TropeHit[]
  /** v0.7：普通选题为 null；榜单仿写选题带参考书与自检 */
  source?: IdeaSource | null
}

export interface ReskinSelfCheck { aspect: string; original: string; ours: string; similar: boolean }
export interface IdeaSource {
  kind: 'reskin'
  rank_item_id?: number | null
  ref_title: string
  ref_book_id_ext?: string
  ref_category?: string
  kept: string[]
  changed: string[]
  self_check: ReskinSelfCheck[]
  overlap: { count: number; title?: number; segments: string[] }
  warnings: string[]
}

// ---------- v0.9.2 立项向导 ----------
export type IdeaSeedSourceType = 'trend_report' | 'rank_book' | 'paste' | 'fusion' | 'manual'
export interface IdeaSeed {
  title: string; logline: string; protagonist?: string; mechanism?: string; opening?: string; selling_points?: string[]
  genre?: string; gender?: Gender
  source: { type: IdeaSeedSourceType; ref?: string; report_id?: number; book_id_ext?: string }
}
export interface FusionRef { book_id_ext?: string; title?: string; text?: string; weight: number }
export interface FusionResult { ideas: Idea[]; dropped: number; warnings: string[]; idea_ids?: number[] }
export interface ImitateExtract {
  title_guess: string; chapters: { title: string; chars: number }[]; text: string
  /** 后端：chapters 只列前 10 章；text 为前 10 章 ≤20000 字 */
  total_chapters?: number; text_chars?: number; truncated?: boolean; encoding?: string
}

// ---------- v0.7 榜单仿写 ----------
export interface TeardownCore {
  payoff_formula: string
  golden_finger: { type: string; delivery: string }
  protagonist_template: string
  opening_hook: string
  target_readers: string
  transferable: string[]
  must_replace: string[]
  warnings: string[]
}
export interface KeywordHit { keyword: string; at_char: number; chapter: number }
export interface DeepChapter { index: number; title: string; words: number; dialogue_ratio: number; conflict: string; payoff: string; hook: string }
export interface DeepTeardown {
  chapters: DeepChapter[]
  total_words: number
  dialogue_ratio: number
  first_conflict: KeywordHit | null
  first_cheat: KeywordHit | null
  rhythm: string
  learnable: string[]
  overlap: number
  warnings: string[]
}
export interface Teardown {
  id: number
  rank_item_id: number
  book_id_ext?: string
  title: string
  created_at?: string
  cached: boolean
  teardown: TeardownCore | null
  deep: DeepTeardown | null
}
export interface ReskinResult {
  rank_item_id?: number
  teardown_id?: number
  ref_title: string
  idea_ids: number[]
  ideas: Idea[]
  warnings: string[]
}

export type IdeaField = 'title' | 'genre' | 'logline' | 'selling_points' | 'hook' | 'expectations' | 'arc' | 'endgame'

export type CardType = 'world' | 'cheat' | 'power' | 'faction' | 'character' | 'item' | 'location'
export interface Card {
  id: number
  book_id: number
  type: CardType
  name: string
  summary: string
  data: Record<string, any>
  known_by: string[]
  updated_at: string
  trope_hits?: TropeHit[]
  /** v0.9.3：是否可被 @ 引用（默认 true）、弃用状态、人物灵魂五维 */
  ref_enabled?: boolean
  status?: CardStatus
  soul?: Soul | null
}
export interface Fact {
  id: number
  book_id: number
  entity_id: number | null
  key: string
  value: string
  from_chapter: number
  to_chapter: number | null
  visibility: 'author' | 'reader'
}

export type OutlineLevel = 'book' | 'volume' | 'arc' | 'chapter'
export interface OutlineNode {
  id: number
  book_id: number
  parent_id: number | null
  level: OutlineLevel
  order: number
  title: string
  summary: string
  beats: Record<string, any> | null
  status: 'planned' | 'expanded' | 'written'
  chapter_id: number | null
  versions?: number
  last_instruction?: string
}

export interface ReviewIssue {
  severity: 'high' | 'mid' | 'low'
  dimension: string
  quote: string
  comment: string
}
export interface Review {
  scores: { hook: number; pacing: number; payoff: number; character: number; coherence: number; overall: number
    /** v0.6：连续性与物理逻辑、语义正确（旧审稿结果没有这两项） */
    continuity?: number; semantics?: number
    /** v0.8.4：追读欲（番茄老读者视角） */
    retention?: number }
  issues: ReviewIssue[]
  passed: boolean
  /** v0.8.4：读者视角打分（0–10）与一句读后感 */
  reader?: { score: number | null; verdict: string }
  /** v0.9：审稿补丁（逐字替换）与应用记录 */
  patches?: ReviewPatch[]
  patch_log?: PatchLogEntry[]
}
export interface ReviewPatch {
  index: number
  original: string
  improved: string
  reason: string
  issue_ref: number | null
  severity: ReviewIssue['severity'] | string
  applied: boolean
}
export interface PatchSkip { index: number; reason: string }
export interface PatchLogEntry { label: string; at: string; applied: number[]; skipped: PatchSkip[] }
export interface Lint {
  ai_score: number
  dialogue_ratio: number
  repeated_ngrams: { text: string; count: number }[]
  banned_hits: { word: string; count: number }[]
  warnings: string[]
  /** v0.1 增补 */
  avg_sentence_len?: number
  short_sentence_ratio?: number
  bare_dialogue_ratio?: number
  summary_ratio?: number
  /** v0.6 手艺类：重复强化词、陈词比喻、量词搭配、群众镜头、对白口癖、口头禅、定点修改清单 */
  intensifiers?: { word: string; count: number; allow: number; over: boolean }[]
  cliche_similes?: { word: string; count: number }[]
  measure_errors?: { word: string; match: string; hint: string; quote: string }[]
  crowd_shots?: number
  dialogue_tics?: { word: string; count: number; over: boolean }[]
  catchphrases?: { who: string; word: string; count: number; over: boolean }[]
  fix_targets?: { kind: string; word: string; quote: string; hint: string }[]
  /** v0.9：本次按哪一档检查、超长段落数（番茄档 >70 字） */
  platform?: PlatformStyle | string
  long_paragraphs?: number
}
export interface ChangeSet {
  new_entities: any[]
  state_changes: any[]
  foreshadow: { action: 'plant' | 'advance' | 'resolve'; id: number | null; desc: string }[]
}
export interface Chapter {
  id: number
  book_id: number
  number: number
  title: string
  content?: string
  words: number
  status: 'draft' | 'reviewing' | 'committed'
  review: Review | null
  lint: Lint | null
  /** 合约未列出，后端若返回则展示 */
  changes?: ChangeSet | null
  /** v0.1 增补：多版本 */
  variants?: ChapterVariant[]
  updated_at: string
  /** v0.4：可撤回的旧正文数 */
  history?: number
  last_history_label?: string
  /** v0.9.1：最近一次朱雀 AIGC 检测 */
  aigc?: AigcResult | null
}
export interface ChapterVariant {
  id: number
  content: string
  words: number
  lint: Lint | null
  review_overall: number | null
}

export interface Style {
  sample_text: string
  voice_notes: string
  pov: 'first' | 'third'
  tone: string
  extracted: Record<string, any> | null
}

export type ForeshadowStatus = 'planned' | 'planted' | 'advancing' | 'resolved' | 'dropped'
export type ForeshadowTier = '' | 'short' | 'mid' | 'long'
export interface Foreshadow {
  id: number
  book_id: number
  desc: string
  status: ForeshadowStatus
  planted_ch: number
  last_ch: number
  resolved_ch: number | null
  tier?: ForeshadowTier
  plan_plant_ch?: number | null
  plan_resolve_ch?: number | null
  note?: string
  source?: 'chapter' | 'ai' | 'manual' | 'outline'
}
export interface ForeshadowPlanItem {
  desc: string; tier: ForeshadowTier; plant_ch: number | null; resolve_ch: number | null; note: string; related: string[]
  duplicate_of?: number | null; in_outline?: boolean
}
export interface ForeshadowOverview {
  outline_planned: { desc: string; chapter: number; node_id: number; tier: string }[]
  committed: number; drafts: number; outline_nodes: number; last_committed: number
}

// ---------- v0.4：按要求让 AI 改 ----------
export interface CardDraft { type: CardType; name: string; summary: string; data: Record<string, any>; known_by: string[] }
export interface BibleConflict { card_id: number; name: string; type: CardType; reason: string; source: 'program' | 'ai' }
export type BibleChoice = 'add' | 'skip' | 'keep_old' | 'replace' | 'both' | 'delete_old'
export interface BibleItem {
  key: string; action: 'add' | 'update'; card: CardDraft; target_id: number | null; old: (CardDraft & { id: number }) | null
  conflicts: BibleConflict[]; trope_hits: TropeHit[]; default: BibleChoice
}
export interface BibleProposal {
  book_id: number; mode: 'rewrite' | 'add' | 'optimize'; instruction: string; change: string
  items: BibleItem[]; removals: { card_id: number; name: string; type: CardType; summary: string }[]; facts: any[]
  counts: { add: number; review: number; removals: number }
}
export interface BibleOp { op: 'create' | 'update' | 'delete'; card_id?: number | null; card?: CardDraft }
export interface BibleSnapshot { id: number; note: string; count: number; created_at: string; names: string[] }
export interface Impact {
  terms: string[]; total: number
  cards: { id: number; name: string; type: CardType; terms: string[]; snippet: string }[]
  outline: { id: number; level: OutlineLevel; order: number; title: string; status: string; terms: string[]; snippet: string }[]
  chapters: { id: number; number: number; title: string; status: string; terms: string[]; count: number; snippet: string }[]
}
export interface BookInfo { title: string; tagline: string; premise: string }
export interface BookRevision {
  book_id: number; instruction: string; current: BookInfo; proposal: BookInfo; change: string; terms: string[]
  replacements: Record<string, string>; impact: Impact; trope_hits: TropeHit[]
}
export interface OutlineSyncItem {
  node_id: number; level: OutlineLevel; old: { title: string; summary: string }
  new: { title: string; summary: string; beats?: Record<string, any> }; reason: string; beats_changed?: boolean
}
export interface SyncResult {
  terms: string[]; replacements: Record<string, string>; bible: BibleProposal | null; outline: { items: OutlineSyncItem[] }
  chapters: Impact['chapters']
}

export interface Package {
  book_id: number
  titles: { title: string; score: number }[]
  blurb: string
  tags: string[]
  cover_prompt: string
  covers: string[]
  chosen_cover: string | null
}

export interface WritingSettings {
  auto_adopt_best: boolean
  auto_commit: boolean
  default_variants: 1 | 2 | 3
}

/** v0.9.1：GET/PUT /api/settings/zhuque */
export interface ZhuqueSettings {
  zhuque_configured: boolean
  zhuque_key_tail: string
  zhuque_base_url: string
  zhuque_auto_check: boolean
  zhuque_usage?: { calls: number; tokens: number }
}
/** PUT：zhuque_api_key 空串=清除；zhuque_base_url 空串=恢复默认 */
export type ZhuqueSettingsInput = Partial<{ zhuque_api_key: string; zhuque_base_url: string; zhuque_auto_check: boolean }>

// ---------- v0.9.1 AIGC 检测 ----------
export type AigcLabel = 'human' | 'ai' | 'suspect'
export interface AigcSegment { start: number; end: number; label: AigcLabel; conf: number }
export interface AigcResult {
  /** 独立检测（/detect/aigc）的结果没有 checked_at / content_hash / stale */
  checked_at?: string
  content_hash?: string
  /** 服务端判断：检测后正文已改 */
  stale?: boolean
  ai_segment_ratio?: number | null
  suspect_segment_ratio?: number | null
  chars?: number
  is_merge?: boolean
  softmax: number
  ratio: number
  labels_ratio: { human: number; ai: number; suspect: number }
  level: 'low' | 'mid' | 'high'
  /** 章节列表里的 aigc 不带 segments */
  segments?: AigcSegment[]
  tokens: number
  chunks: number
}

// ---------- v0.5：每本书的专属 Agent ----------
export interface AgentSession {
  id: number; book_id: number; title: string; messages: number; running: boolean; running_job_id: number | null
  last_user: string; created_at: string; updated_at: string
}
export interface AgentToolCall { id: string; name: string; arguments: Record<string, any>; label: string; kind: 'read' | 'write' }
export interface AgentMessage {
  id: number; role: 'user' | 'assistant' | 'tool' | 'notice'; content: string; tool_calls: AgentToolCall[]; tool_call_id: string
  name: string; summary: string; status: 'ok' | 'error'; proposal_ids: number[]; job_ids: number[]; created_at: string
  label?: string; kind?: 'read' | 'write'
}
export type AgentProposalKind = 'book_info' | 'bible' | 'card_delete' | 'outline_nodes' | 'chapter_rewrite' | 'foreshadow_add'
  | 'foreshadow_update' | 'foreshadow_delete' | 'package' | 'covers' | 'write_chapter' | 'reskin_ideas' | 'book_test'
export type AgentProposalStatus = 'pending' | 'applied' | 'rejected' | 'reverted' | 'running' | 'failed'
export interface AgentProposal {
  id: number; book_id: number; session_id: number; message_id: number | null; kind: AgentProposalKind; kind_label: string
  title: string; summary: string; payload: Record<string, any>; status: AgentProposalStatus; destructive: boolean
  needs_review: boolean; auto_applied: boolean; result: Record<string, any> | null; error: string; job_id: number | null
  revertible: boolean; created_at: string; updated_at: string
}
export interface AgentJobState { id: number; status: Job['status']; progress: number; message: string; error: string | null }
export interface AgentSessionDetail {
  session: AgentSession; messages: AgentMessage[]; proposals: AgentProposal[]
  proposal_jobs: Record<string, AgentJobState | null>; job: Job | null
}
export interface AgentToolInfo { name: string; label: string; kind: 'read' | 'write'; description: string }

// ---------- v0.9.3 完整度 / 引导 / 设定 AI / 灵魂 / 审批 / 成本 / 拆书（docs/API_CONTRACT.md「v0.9.3」节）----------
export interface CompletenessItem {
  key: string
  label: string
  done: boolean
  weight: number
  /** 未完成时的一句提示，完成时为空串 */
  hint: string
  /** route：target 是前端路由；job：target 是要 POST（空 body）的接口路径（含 /api 前缀），返回 Job */
  action?: { type: 'route' | 'job'; target: string } | null
}
export interface Completeness { book_id: number; score: number; items: CompletenessItem[] }

export type OnboardingKey = 'model' | 'project' | 'bible_outline' | 'first_chapter'
export interface OnboardingState {
  steps: Record<OnboardingKey, boolean>
  order: OnboardingKey[]
  labels: Partial<Record<OnboardingKey, string>>
  auto: Partial<Record<OnboardingKey, boolean>>
  current: OnboardingKey | null
  dismissed: boolean
}

export type FieldAiMode = 'fill' | 'rewrite' | 'expand'
export interface FieldAiResult { entry_id: number; field: string; mode: FieldAiMode; before: unknown; value: unknown; note?: string }

export type CardStatus = 'active' | 'deprecated'
export type SoulKey = 'desire' | 'fear' | 'wound' | 'belief' | 'voice'
export type Soul = Record<SoulKey, string>
export interface SoulResult { entry_id: number; mode: 'fill' | 'rewrite'; before: Soul; soul: Soul; note?: string }

export interface RefEntry { id: number; name: string; type: CardType | string; type_label?: string; brief?: string }

export type ApprovalMode = 'auto' | 'review'

export type EstimateKind = 'chapter_write' | 'chapter_rewrite' | 'polish_voice' | 'humanize' | 'thicken' | 'review' | 'outline' | 'bible'
  | 'report' | 'idea' | 'field_ai' | 'soul' | 'teardown' | 'package' | 'aigc'
export interface Estimate {
  kind: EstimateKind
  input_tokens_est: number
  output_tokens_est: number
  calls_est: number
  route: string
  model: string
  seconds_est: number
  seconds_source?: 'history' | 'default'
  note?: string
}
export interface UsageRow { calls: number; in_tokens: number; out_tokens: number; ms: number }
export interface BookUsage extends UsageRow {
  book_id: number | null
  by_kind: (UsageRow & { kind: string })[]
  by_route: (UsageRow & { route: string })[]
  last_at: string | null
}

export type TeardownSourceType = 'rank_book' | 'paste' | 'txt'
export interface PacingPoint { chapter: number; title: string; conflict: number; payoff: number; hook: number; note?: string }
export interface TeardownResult {
  structure?: { opening?: string; rhythm?: string; chapter_hooks?: string[] }
  characters?: { role: string; template: string; traits: string[]; function: string }[]
  golden_finger?: { mechanism?: string; limits?: string; growth?: string; payoff?: string }
  selling_points?: string[]
  pacing_chart?: PacingPoint[]
  reusable?: { name: string; pattern: string; how_to_use: string }[]
}
export interface TeardownRecord {
  id: number
  title: string
  source: TeardownSourceType
  book_id_ext: string | null
  chars: number
  result: TeardownResult
  warnings: string[]
  model: string
  created_at: string
}
export interface TeardownListItem {
  id: number; title: string; source: TeardownSourceType; book_id_ext: string | null; chars: number; created_at: string
  warnings_count: number; modules: string[]
}
export type TeardownBiblePart = 'characters' | 'golden_finger' | 'reusable' | 'selling_points'

// ---------- v0.9.4 提交前修中等问题 / 数值一致性 / 补丁后重审 / 断点续跑 ----------
export interface JobCheckpoint {
  /** node | scenes | scene:{版本}:{已写}/{总数} | variant:{n} | chapter | adopted | refined | patched */
  stage: string
  resumes: number
  updated_at: string
  chapter_id?: number | null
  number?: number | null
  scenes_total?: number | null
  scenes_done?: number | null
  variants_done?: number | null
}
export interface Job {
  /** v0.9.4：interrupted / failed 且有断点、kind 支持续跑 */
  resumable?: boolean
  checkpoint?: JobCheckpoint | null
}
export type NumericKind = 'weight' | 'height' | 'length' | 'width' | 'thick' | 'depth' | 'range' | 'power' | 'speed' | 'age' | 'days' | 'realm'
/** 对照来源：本章前文原句 `{quote, offset, paragraph}`，或账本/设定卡 `{source, label, value}` */
export interface NumericRelated { quote?: string; offset?: number; paragraph?: number; source?: 'ledger' | string; label?: string; value?: string }
/** 字段已合并进 ReviewIssue（见下方增补） */
export type NumericIssue = ReviewIssue
export interface ReviewIssue {
  /** v0.9.4：程序检查来源，例如 `lint:numeric` */
  source?: string
  position?: { offset: number; paragraph: number; match: string }
  object?: string
  kind?: NumericKind | string
  related?: NumericRelated
}
export interface Lint {
  /** v0.9.4：数值一致性冲突、阈值档 */
  numeric_conflicts?: NumericIssue[]
  lint_tier?: 'fanqie' | 'publish'
}
export interface RereviewInfo {
  round: number
  at: string
  before_overall: number
  after_overall: number
  passed: boolean
  high_left: number
  dropped_issues: number
}
export interface PreCommitFix {
  issues: number[]
  patches_applied: number[]
  patches_skipped: PatchSkip[]
  rewritten: number
  changed: boolean
  at: string
  skipped?: string
}
export interface Review {
  rereview?: RereviewInfo | null
  flagged?: boolean
  flag_reason?: string
  pre_commit_fix?: PreCommitFix | null
}
export interface ReviewPatch {
  /** v0.9.4：0 = 上一轮审稿的补丁，1 = 复审补丁；stale 的手动应用会被跳过 */
  round?: number
  stale?: boolean
}
export interface WritingSettings {
  fix_mid_before_commit?: boolean
  auto_rereview?: boolean
}
export interface BookWritingToggles { fix_mid_before_commit: boolean; auto_rereview: boolean }
export interface BookWritingSettings {
  book_id: number
  /** null = 跟随全局 */
  overrides: { fix_mid_before_commit: boolean | null; auto_rereview: boolean | null }
  effective: BookWritingToggles
  global: BookWritingToggles
}
export type BookWritingSettingsInput = Partial<{ fix_mid_before_commit: boolean | null; auto_rereview: boolean | null }>

// ---------------------------------------------------------------- v0.10 同人创作
export type FanficDepth = 'quick' | 'standard' | 'deep'
export type FanficFidelity = 'strict' | 'moderate' | 'loose'
export type FanficDirectionId =
  | 'canon_fill' | 'if_line' | 'transmigration' | 'rebirth' | 'system' | 'au_modern' | 'au_ancient' | 'side_pov'
  | 'cp' | 'villain_redemption' | 'epilogue' | 'crossover'
export type FanficSourceType = 'paste' | 'txt'
export interface SourceCharacter {
  name: string; aliases: string[]; role: string; personality: string; speech_style: string; catchphrases: string[]
  relations: { target: string; relation: string }[]; abilities: string[]; limits: string[]; notes: string
}
export interface SourceWorld { summary: string; rules: string[]; locations: { name: string; desc: string }[] }
export interface SourceFaction { name: string; stance: string; members: string[]; notes: string }
export interface SourceTimelineItem { order: number; event: string; characters: string[]; impact: string }
export interface SourceScene { title: string; summary: string; characters: string[] }
export interface SourceCards {
  characters: SourceCharacter[]; world: SourceWorld; factions: SourceFaction[]; timeline: SourceTimelineItem[]; scenes: SourceScene[]
}
export type SourceCardPart = keyof SourceCards
export interface FanficSourceBrief {
  id: number; title: string; source: FanficSourceType; chars: number; total_chars: number; depth: FanficDepth; focus: string[]
  completeness: number; counts: { characters: number; factions: number; timeline: number; scenes: number }
  warnings_count: number; used_by: number[]; model: string; created_at: string; updated_at: string
}
export interface FanficSource extends FanficSourceBrief { cards: SourceCards; warnings: string[] }
export interface BookFanfic {
  source_id: number; source_title: string; fidelity: FanficFidelity; direction: FanficDirectionId
  extra_source_ids: number[]; notes: string; copyright_ack: boolean; copyright_ack_at: string; attached_at: string
}
export interface FanficInfoDetail extends BookFanfic {
  direction_label: string; fidelity_label: string; source: FanficSourceBrief | null; source_missing: boolean
}
export interface FanficInfo { book_id: number; fanfic: FanficInfoDetail | null }
export interface FanficSpecInput {
  source_id: number; fidelity?: FanficFidelity; direction?: FanficDirectionId; extra_source_ids?: number[]; notes?: string
}
export interface FanficDirection {
  id: FanficDirectionId; label: string; desc: string; tips: string[]; risks: string[]; suggested_fidelity: FanficFidelity; template: string
}
export interface FanficFidelityInfo { id: FanficFidelity; label: string; desc: string; pass_score: number }
export interface FanficCatalog { directions: FanficDirection[]; fidelities: FanficFidelityInfo[]; copyright_notice: string }
export type FanficImportPart = 'characters' | 'factions' | 'world' | 'locations'
export type OocIssueType = 'speech' | 'catchphrase' | 'relation' | 'ability' | 'timeline'
export type OocLevel = 'pass' | 'warn' | 'fail'
export interface OocIssue {
  type: OocIssueType; type_label: string; severity: 'high' | 'mid' | 'low'; quote: string; problem: string; suggestion: string; source: 'model' | 'program'
}
export interface OocCharacter { name: string; score: number; model_score: number | null; level: OocLevel; verdict: string; issues: OocIssue[] }
export interface OocResult {
  fidelity: FanficFidelity; fidelity_label: string; pass_score: number; overall: number; verdict: OocLevel
  characters: OocCharacter[]; summary: string; ignored_issues: number; content_hash: string; checked_at: string; model: string
  stale?: boolean
}
export type OverlapLevel = 'ok' | 'info' | 'warn' | 'high'
export interface FanficOverlap {
  ngram: number; hits: number; segments: number; longest: number; ratio: number; level: OverlapLevel; warning: string
  samples: string[]; content_hash: string; checked_at: string; stale?: boolean
}
export interface ChapterFanficMeta { chapter_id: number; ooc: OocResult | null; overlap: FanficOverlap | null }
/** v0.10：book_out 新字段（原创书为 null）——接口合并，补到 Book 上 */
export interface Book { fanfic?: BookFanfic | null }
