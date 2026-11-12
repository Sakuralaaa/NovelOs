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
}
export interface ChannelInput {
  name: string
  base_url: string
  api_key?: string
  models: string[]
  enabled?: boolean
}
export type RouteKey = 'planner' | 'writer' | 'reviewer' | 'embedding' | 'image'
export type Routing = Record<RouteKey, string | null>

export type Gender = 'male' | 'female'
export interface RankItem {
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
}

export interface Idea {
  id: number
  book_id: number | null
  title: string
  logline: string
  selling_points: string[]
  hook: string
  genre: string
  scores: { heat: number; novelty: number; fit: number; overall: number }
  chosen: boolean
}

export type CardType = 'world' | 'power' | 'faction' | 'character' | 'item' | 'location'
export interface Card {
  id: number
  book_id: number
  type: CardType
  name: string
  summary: string
  data: Record<string, any>
  known_by: string[]
  updated_at: string
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
}

export interface ReviewIssue {
  severity: 'high' | 'mid' | 'low'
  dimension: string
  quote: string
  comment: string
}
export interface Review {
  scores: { hook: number; pacing: number; payoff: number; character: number; coherence: number; overall: number }
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

export interface Foreshadow {
  id: number
  book_id: number
  desc: string
  status: 'planted' | 'advancing' | 'resolved' | 'dropped'
  planted_ch: number
  last_ch: number
  resolved_ch: number | null
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
