// 与 novelos/docs/API_CONTRACT.md 一一对应
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed'
export interface Job {
  id: number
  kind: string
  status: JobStatus
  progress: number
  message: string
  result: Record<string, any> | null
  error: string | null
  book_id: number | null
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
}
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
    continuity?: number; semantics?: number }
  issues: ReviewIssue[]
  passed: boolean
}
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
  | 'foreshadow_update' | 'foreshadow_delete' | 'package' | 'covers' | 'write_chapter' | 'reskin_ideas'
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
