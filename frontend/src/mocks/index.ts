/**
 * 前端自测用 fetch mock —— 仅当 VITE_USE_MOCK=1 时由 main.tsx 动态加载。
 * 覆盖 API_CONTRACT.md（含 v0.1 增补、v0.4 按要求让 AI 改、v0.5 每本书的专属 Agent）的全部端点，数据为确定性的虚构示例。
 */
import type {
  AgentMessage, AgentProposal, AgentSession, AgentSessionDetail, AgentToolInfo, BibleItem, BibleOp, BibleProposal, BookInfo,
  ForeshadowPlanItem, Impact, OutlineSyncItem, Trope, TropeHit,
  Book, Card, Channel, Chapter, ChapterVariant, Foreshadow, Idea, Job, Lint, OutlineNode, Package,
  RadarConfig, RadarSnapshot, Review, Routing, Style,
} from '@/lib/types'
import { analyzeText } from '@/lib/textAnalysis'
import { countWords } from '@/lib/utils'
import { FEMALE_CATS, MALE_CATS, STYLE_SAMPLE, THICKEN_MAP, buildChapterText, coverDataUrl, makeRankItems } from './data'

const now = () => new Date().toISOString()
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString()
let seq = 1000
const nid = () => ++seq

// ---------------- DB ----------------
const db = {
  channels: [] as (Omit<Channel, 'api_key_masked'> & { api_key: string })[],
  routing: { planner: null, writer: null, reviewer: null, search: null, embedding: null, image: null, agent: null, image_mode: 'images' } as Routing,
  radarConfig: { enabled: true, daily_hour: 8 } as RadarConfig,
  writing: { auto_adopt_best: false, auto_commit: false, default_variants: 1 },
  snapshots: [{ id: 1, taken_at: ago(60 * 5), source: 'mock', items_count: 60 }] as RadarSnapshot[],
  items: makeRankItems(),
  books: [] as Book[],
  ideas: [] as Idea[],
  cards: [] as Card[],
  outline: [] as OutlineNode[],
  chapters: [] as Chapter[],
  foreshadows: [] as Foreshadow[],
  packages: new Map<number, Package>(),
  styles: new Map<number, Style>(),
  jobs: [] as (Job & { _start: number; _dur: number; _steps: string[]; _fin?: () => Record<string, any> | null; _done?: boolean })[],
}

function mkLint(content: string): Lint {
  const a = analyzeText(content)
  const banned = [
    { word: '不禁', count: (content.match(/不禁/g) || []).length },
    { word: '一切都', count: (content.match(/一切都/g) || []).length },
    { word: '总之', count: (content.match(/总之/g) || []).length },
  ].filter((x) => x.count)
  const warnings: string[] = []
  if (a.bare_dialogue_ratio > 0.35) warnings.push('裸对白偏多：对白前后缺少动作、神态或环境描写')
  if (a.summary_ratio > 0.15) warnings.push('存在概述式叙述，读起来像“说明书”，建议改成具体场景')
  if (a.short_sentence_ratio > 0.45) warnings.push('短句占比偏高，节奏碎，建议合并部分短句')
  return {
    ai_score: Math.round(Math.min(95, 20 + a.bare_dialogue_ratio * 50 + a.summary_ratio * 120)),
    dialogue_ratio: +a.dialogue_ratio.toFixed(3),
    repeated_ngrams: [{ text: '冷冰冰的', count: 3 }, { text: '没说话', count: 2 }],
    banned_hits: banned,
    warnings,
    avg_sentence_len: +a.avg_sentence_len.toFixed(1),
    short_sentence_ratio: +a.short_sentence_ratio.toFixed(3),
    bare_dialogue_ratio: +a.bare_dialogue_ratio.toFixed(3),
    summary_ratio: +a.summary_ratio.toFixed(3),
  }
}

function mkReview(seed: number, content: string): Review {
  const base = 68 + (seed % 5) * 4
  const scores = { hook: base + 6, pacing: base - 4, payoff: base + 2, character: base - 8, coherence: base + 10, overall: base }
  const pick = (s: string) => (content.includes(s) ? s : content.split('\n')[2] || '')
  return {
    scores,
    passed: scores.overall >= 70,
    issues: [
      { severity: 'high', dimension: '节奏', quote: pick('于是接下来的几天里，超市的生意渐渐好了起来'), comment: '一句话跳过了好几天，读者没有“看到”生意变好，建议拆成 1–2 个具体交易场景。' },
      { severity: 'mid', dimension: '人物', quote: pick('“开门。”'), comment: '门外人第一次开口，只有台词没有动作，压迫感不足。' },
      { severity: 'mid', dimension: '爽点', quote: pick('系统的提示音在脑子里响起'), comment: '系统出场偏平，可以让主角先犹豫再触发，制造期待。' },
      { severity: 'low', dimension: '连贯', quote: pick('远处传来一声闷响'), comment: '闷响来源后文未交代，记得登记为伏笔或在下一章回应。' },
    ],
  }
}

function seedDemo() {
  const bookId = 1
  const book: Book = {
    id: bookId, title: '我在末世开超市', genre: '末世求生', gender: 'male',
    tagline: '全球冰封第三年，我的超市每天零点自动补货。', status: 'writing',
    target_words: 1_000_000, chapter_words: 2200, cover_url: coverDataUrl('我在末世开超市', 1),
    created_at: ago(60 * 24 * 3), updated_at: ago(12), stats: { chapters: 6, words: 0, foreshadow_open: 3 },
  }
  db.books.push(book)
  db.books.push({
    id: 2, title: '重生八零：糙汉老公宠上天', genre: '年代重生', gender: 'female', tagline: '上辈子错过的人，这辈子我追。',
    status: 'outline', target_words: 600_000, chapter_words: 2000, cover_url: null, created_at: ago(60 * 30), updated_at: ago(60 * 2),
    stats: { chapters: 0, words: 0, foreshadow_open: 0 },
  })
  const cards: Omit<Card, 'id' | 'book_id' | 'updated_at'>[] = [
    { type: 'world', name: '冰封纪元', summary: '全球气温骤降第三年，城市被冰雪掩埋，幸存者以物易物。', data: { 时间: '冰封第 3 年', 气温: '白天 -30℃，夜间 -50℃', 货币: '以物易物，子弹与药品最硬通' }, known_by: ['林野', '苏晚'] },
    { type: 'cheat', name: '超市系统', summary: '每日零点补货，交易可获得“信用点”升级货架。', data: { 补货: '每天 0:00', 升级: '信用点', 限制: '不能主动攻击' }, known_by: ['林野'] },
    { type: 'faction', name: '东区摩托帮', summary: '东区最大的掠夺团伙，首领绰号“金牙”。', data: { 人数: '约 40 人', 据点: '旧加油站' }, known_by: ['林野', '苏晚', '金牙'] },
    { type: 'character', name: '林野', summary: '主角，前便利店店员，谨慎、嘴硬心软。', data: { 年龄: '24', 身份: '超市老板', voice: '话少，短句，爱用反问；生气时反而更客气', catchphrases: ['行。', '先说好，只换不卖。'], habits: ['想事情时用拇指摩挲撬棍', '进门先看货架有没有被动过'], demeanor: '眼皮总是半耷拉着，看人时先看手' }, known_by: [] },
    { type: 'character', name: '苏晚', summary: '带着弟弟逃难的前护士，冷静果断。', data: { 年龄: '27', 身份: '前护士', voice: '语速快，用词精确，带医学术语', catchphrases: ['别动。'], habits: ['下意识整理袖口'], demeanor: '抿嘴，眉心常有一道竖纹' }, known_by: ['林野'] },
    { type: 'item', name: '老猎枪', summary: '父亲留下的双管猎枪，枪托缠着褪色布条。', data: { 弹药: '12 号霰弹', 状态: '保养良好' }, known_by: ['林野'] },
    { type: 'location', name: '野火超市', summary: '东区唯一还亮灯的店，卷帘门被加固过三次。', data: { 位置: '东区长青路 17 号', 面积: '约 200 平' }, known_by: ['苏晚', '金牙'] },
  ]
  cards.forEach((c) => db.cards.push({ ...c, id: nid(), book_id: bookId, updated_at: ago(30) }))

  // 大纲
  const root = { id: nid(), book_id: bookId, parent_id: null, level: 'book', order: 0, title: '总纲：冰封之下的最后一家店', summary: '林野靠超市系统在冰封末世立足，从一家小店扩张为东区的庇护所，最终揭开冰封真相。', beats: null, status: 'expanded', chapter_id: null } as OutlineNode
  db.outline.push(root)
  const vols = ['第一卷 · 开门营业', '第二卷 · 东区风云', '第三卷 · 冰原之下']
  vols.forEach((vt, vi) => {
    const v: OutlineNode = { id: nid(), book_id: bookId, parent_id: root.id, level: 'volume', order: vi, title: vt, summary: ['立足：收留苏晚姐弟，与摩托帮第一次冲突。', '扩张：建立交易网络，卷入三方势力博弈。', '真相：寻找冰封源头。'][vi], beats: null, status: vi === 0 ? 'expanded' : 'planned', chapter_id: null }
    db.outline.push(v)
    if (vi === 0) {
      ;['弧一 · 第一笔交易', '弧二 · 金牙上门'].forEach((at, ai) => {
        const a: OutlineNode = { id: nid(), book_id: bookId, parent_id: v.id, level: 'arc', order: ai, title: at, summary: ai === 0 ? '黄金三章：超市系统觉醒，救下发烧的孩子。' : '摩托帮试探，林野第一次动用猎枪。', beats: null, status: ai === 0 ? 'expanded' : 'planned', chapter_id: null }
        db.outline.push(a)
        if (ai === 0) {
          for (let c = 1; c <= 8; c++) {
            db.outline.push({ id: nid(), book_id: bookId, parent_id: a.id, level: 'chapter', order: c, title: `第${c}章 ${['零点补货', '门外有人', '十二发子弹', '退烧药', '只换不卖', '闷响', '金牙', '第一场雪夜'][c - 1]}`, summary: '主角在 300 字内出场，1000 字内抛出钩子，章尾留悬念。', beats: { 开场: '环境压迫感', 冲突: '交易与信任', 章尾钩子: '远处闷响' }, status: c <= 6 ? 'written' : 'planned', chapter_id: null })
          }
        }
      })
    }
  })

  // 章节
  const titles = ['零点补货', '门外有人', '十二发子弹', '退烧药', '只换不卖', '闷响']
  titles.forEach((t, i) => {
    const content = buildChapterText(i)
    const id = 200 + i
    const ch: Chapter = {
      id, book_id: bookId, number: i + 1, title: t, content, words: countWords(content),
      status: i < 4 ? 'committed' : i === 4 ? 'reviewing' : 'draft',
      review: i < 5 ? mkReview(i, content) : null, lint: mkLint(content), updated_at: ago(60 * (6 - i)),
      changes: { new_entities: i === 2 ? [{ type: 'character', name: '苏晚' }] : [], state_changes: [{ entity: '林野', change: '信用点 +12' }], foreshadow: [{ action: i === 5 ? 'plant' : 'advance', id: null, desc: '远处的闷响' }] },
    }
    if (i === 5) {
      ch.variants = [0, 1, 2].map((v) => {
        const c = buildChapterText(5 + v * 2, 15 + v)
        return { id: 900 + v, content: c, words: countWords(c), lint: mkLint(c), review_overall: [74, 81, 69][v] }
      })
      ch.content = ch.variants[0].content
    }
    db.chapters.push(ch)
    const n = db.outline.find((o) => o.level === 'chapter' && o.order === i + 1)
    if (n) n.chapter_id = id
  })

  db.foreshadows.push(
    { id: nid(), book_id: bookId, desc: '父亲的老猎枪为什么保养得这么好', status: 'planted', planted_ch: 1, last_ch: 1, resolved_ch: null },
    { id: nid(), book_id: bookId, desc: '远处的闷响：冰层下有东西', status: 'planted', planted_ch: 6, last_ch: 6, resolved_ch: null },
    { id: nid(), book_id: bookId, desc: '苏晚弟弟脖子上的编号纹身', status: 'advancing', planted_ch: 3, last_ch: 5, resolved_ch: null },
    { id: nid(), book_id: bookId, desc: '系统提示音像“有人贴着耳朵念账单”', status: 'advancing', planted_ch: 1, last_ch: 4, resolved_ch: null },
    { id: nid(), book_id: bookId, desc: '孩子的高烧是普通感冒', status: 'resolved', planted_ch: 2, last_ch: 4, resolved_ch: 4 },
    { id: nid(), book_id: bookId, desc: '收音机里的求救信号', status: 'dropped', planted_ch: 2, last_ch: 2, resolved_ch: null },
  )

  db.packages.set(bookId, {
    book_id: bookId,
    titles: [
      { title: '我在末世开超市', score: 86 }, { title: '冰封末世：我的超市零点补货', score: 82 },
      { title: '全球冰封，我靠超市养活一座城', score: 79 }, { title: '末日超市：只换不卖', score: 71 },
    ],
    blurb: '全球冰封第三年，城市沉在雪底。\n林野守着一家没人敢抢的小超市——因为它每天零点，货架会自己补满。\n一箱矿泉水换十二发子弹，一盒退烧药换一条命。\n“先说好，只换不卖。”',
    tags: ['末世', '囤货', '系统', '种田', '爽文'],
    cover_prompt: '冰封末世城市，暴雪中一家亮着暖黄灯光的小超市，门前站着一个背着猎枪的年轻男人，电影感，冷暖对比，竖版小说封面构图，顶部留出书名区域',
    covers: [0, 1, 2, 3].map((i) => coverDataUrl('我在末世开超市', i)),
    chosen_cover: coverDataUrl('我在末世开超市', 1),
  })
  db.styles.set(bookId, {
    sample_text: STYLE_SAMPLE, voice_notes: '冷峻克制，多用动作代替心理描写；对白短，前后要有动作或环境。', pov: 'third', tone: '冷峻写实',
    extracted: null,
  })

  db.ideas.push(
    { id: nid(), book_id: bookId, title: '我在末世开超市', logline: '全球冰封，主角的超市每天零点自动补货，以物易物养活一座城。', selling_points: ['囤货爽感', '经营升级', '末世生存'], hook: '一箱矿泉水换十二发子弹。', genre: '末世求生', scores: { heat: 88, novelty: 72, fit: 85, overall: 83 }, chosen: true },
  )
  db.jobs.push({ id: nid(), kind: 'write_next', status: 'succeeded', progress: 100, message: '第 6 章已生成 3 个版本', result: { chapter_id: 205 }, error: null, book_id: bookId, created_at: ago(40), updated_at: ago(38), _start: 0, _dur: 0, _steps: [], _done: true })
  recalc(bookId)
}

function recalc(bookId: number) {
  const b = db.books.find((x) => x.id === bookId)
  if (!b) return
  const chs = db.chapters.filter((c) => c.book_id === bookId)
  b.stats = {
    chapters: chs.length,
    words: chs.reduce((n, c) => n + c.words, 0),
    foreshadow_open: db.foreshadows.filter((f) => f.book_id === bookId && (f.status === 'planted' || f.status === 'advancing')).length,
  }
}
seedDemo()

// ---------------- Jobs ----------------
function createJob(kind: string, bookId: number | null, dur: number, steps: string[], fin: () => Record<string, any> | null): Job {
  const j = { id: nid(), kind, status: 'queued' as const, progress: 0, message: '排队中…', result: null, error: null, book_id: bookId, created_at: now(), updated_at: now(), _start: Date.now(), _dur: dur, _steps: steps, _fin: fin }
  db.jobs.unshift(j)
  return pub(j)
}
function tick(j: (typeof db.jobs)[number]) {
  if (j._done) return
  const el = Date.now() - j._start
  if (el < 350) return
  if (el >= j._dur) {
    try {
      j.result = j._fin?.() ?? {}
      j.status = 'succeeded'
      j.progress = 100
      j.message = '已完成'
    } catch (e: any) {
      j.status = 'failed'
      j.error = e?.message ?? '未知错误'
    }
    j._done = true
  } else {
    j.status = 'running'
    j.progress = Math.round((el / j._dur) * 96)
    j.message = j._steps[Math.min(j._steps.length - 1, Math.floor((el / j._dur) * j._steps.length))]
  }
  j.updated_at = now()
}
function pub(j: any): Job {
  const { _start, _dur, _steps, _fin, _done, ...rest } = j
  void _start; void _dur; void _steps; void _fin; void _done
  return { ...rest }
}

// ---------------- 路由 ----------------
type H = (m: RegExpMatchArray, body: any, url: URL) => any
const routes: [string, RegExp, H][] = []
const on = (method: string, path: string, h: H) => routes.push([method, new RegExp(`^${path.replace(/:(\w+)/g, '(\\d+)')}$`), h])
class HttpErr { constructor(public status: number, public detail: string) {} }
const must = <T,>(v: T | undefined, what = '资源'): T => { if (!v) throw new HttpErr(404, `${what}不存在`); return v }
// 演示：默认已登录；地址带 ?auth=out 时展示登录页（密码 novelos-demo）
if (location.search.includes('auth=out')) sessionStorage.setItem('mock-auth', '0')
const mockAuthed = () => sessionStorage.getItem('mock-auth') !== '0'
const bookOf = (id: string) => must(db.books.find((b) => b.id === +id), '作品')

on('GET', '/health', () => ({ status: 'ok', version: '0.1.0-mock' }))
on('GET', '/jobs', (_m, _b, u) => {
  db.jobs.forEach(tick)
  const bid = u.searchParams.get('book_id')
  return db.jobs.filter((j) => !bid || j.book_id === +bid).slice(0, 50).map(pub)
})
on('GET', '/jobs/:id', (m) => { const j = must(db.jobs.find((x) => x.id === +m[1]), '任务'); tick(j); return pub(j) })

on('GET', '/auth/status', () => ({ enabled: true, authenticated: mockAuthed(), username: 'novelos', managed_by_env: false, min_password_len: 8 }))
on('POST', '/auth/login', (_m: any, body: any) => { if (body?.password !== 'novelos-demo') throw new HttpErr(401, '密码不正确'); sessionStorage.setItem('mock-auth', '1'); return { ok: true } })
on('POST', '/auth/logout', () => { sessionStorage.setItem('mock-auth', '0'); return { ok: true } })
on('POST', '/auth/password', () => ({ ok: true }))
on('GET', '/settings/status', () => ({ mock_mode: db.channels.filter((c) => c.enabled).length === 0 }))
const maskCh = (c: (typeof db.channels)[number]): Channel => ({ id: c.id, name: c.name, base_url: c.base_url, models: c.models, enabled: c.enabled, api_format: c.api_format ?? 'openai', api_key_masked: c.api_key ? `${c.api_key.slice(0, 3)}••••${c.api_key.slice(-4)}` : '' })
on('GET', '/settings/channels', () => db.channels.map(maskCh))
on('POST', '/settings/channels', (_m, b) => { const c = { id: nid(), name: b.name, base_url: b.base_url, api_key: b.api_key ?? '', models: b.models ?? [], enabled: b.enabled ?? true, api_format: b.api_format ?? 'openai' }; db.channels.push(c); return maskCh(c) })
on('PUT', '/settings/channels/:id', (m, b) => { const c = must(db.channels.find((x) => x.id === +m[1])); Object.assign(c, { ...b, api_key: b.api_key ? b.api_key : c.api_key }); return maskCh(c) })
on('DELETE', '/settings/channels/:id', (m) => { db.channels = db.channels.filter((x) => x.id !== +m[1]); return null })
on('POST', '/settings/channels/:id/test', (m) => { const c = must(db.channels.find((x) => x.id === +m[1])); return c.base_url.startsWith('http') ? { ok: true, latency_ms: 230 + (c.id % 7) * 41 } : { ok: false, latency_ms: 0, error: 'Base URL 格式不正确' } })
on('GET', '/settings/writing', () => db.writing)
on('PUT', '/settings/writing', (_m, b) => (db.writing = { ...db.writing, ...b }))
on('POST', '/settings/models/fetch', (_m, b) => {
  if (!/^https?:\/\//.test(b.base_url ?? '')) throw new HttpErr(400, '拉取失败：Base URL 格式不正确')
  const base = String(b.base_url)
  const pool = base.includes('deepseek') ? ['deepseek-chat', 'deepseek-reasoner']
    : base.includes('dashscope') ? ['qwen-max', 'qwen-plus', 'qwen-turbo', 'qwen3-235b-a22b', 'text-embedding-v3', 'wanx2.1-t2i-turbo']
    : ['gpt-4o', 'gpt-4o-mini', 'gpt-4.1', 'gpt-4o-search-preview', 'o3-mini', 'text-embedding-3-small', 'text-embedding-3-large', 'gpt-image-1', 'grok-4.20-multi-agent-0309', 'sonar-pro']
  return { models: pool }
})
on('GET', '/settings/routing', () => db.routing)
on('PUT', '/settings/routing', (_m, b) => (db.routing = { ...db.routing, ...b }))

on('POST', '/radar/refresh', () => createJob('radar_refresh', null, 4200, ['连接番茄公开榜单…', '抓取男频榜单…', '抓取女频榜单…', '计算题材热度…'], () => {
  db.snapshots.unshift({ id: nid(), taken_at: now(), source: 'mock', items_count: db.items.length })
  db.items.forEach((it) => (it.read_count = Math.round(it.read_count * (1 + ((it.rank * 7) % 9) / 100))))
  return { snapshot_id: db.snapshots[0].id }
}))
on('GET', '/radar/snapshots', () => db.snapshots)
on('GET', '/radar/latest', (_m, _b, u) => {
  const g = u.searchParams.get('gender'), c = u.searchParams.get('category')
  return { snapshot: db.snapshots[0] ?? null, items: db.items.filter((i) => (!g || i.gender === g) && (!c || i.category === c)) }
})
on('GET', '/radar/trends', () => [...MALE_CATS, ...FEMALE_CATS].map((cat, i) => {
  const its = db.items.filter((x) => x.category === cat)
  return { category: cat, heat: Math.round(its.reduce((n, x) => n + x.read_count, 0) / 1e5) + ((i * 13) % 30), books: its.length, rising: (i * 5) % 4, sample_titles: its.slice(0, 3).map((x) => x.title) }
}).sort((a, b) => b.heat - a.heat))
on('GET', '/radar/config', () => db.radarConfig)
on('PUT', '/radar/config', (_m, b) => (db.radarConfig = { ...db.radarConfig, ...b }))

on('GET', '/books', () => [...db.books].sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
on('POST', '/books', (_m, b) => {
  const book: Book = { id: nid(), title: b.title || `未命名 · ${b.genre}`, genre: b.genre, gender: b.gender, tagline: b.premise ?? '', status: 'bible', target_words: 1_000_000, chapter_words: 2200, cover_url: null, created_at: now(), updated_at: now(), stats: { chapters: 0, words: 0, foreshadow_open: 0 } }
  db.books.push(book); return book
})
on('GET', '/books/:id', (m) => bookOf(m[1]))
on('PATCH', '/books/:id', (m, b) => Object.assign(bookOf(m[1]), b, { updated_at: now() }))
on('DELETE', '/books/:id', (m) => { db.books = db.books.filter((x) => x.id !== +m[1]); return null })

on('POST', '/ideas/generate', (_m, b) => createJob('ideas_generate', null, 3800, ['读取热点题材…', '构建题材矩阵…', '生成选题卡…', '读者小组预评…'], () => {
  const genre = b.genre || (b.gender === 'female' ? '年代重生' : '都市高武')
  const pool = [
    { title: '我能看见所有人的隐藏属性', logline: '主角意外获得洞察能力，从被人看不起的小角色一步步翻盘。', hook: '开局就看见上司头顶写着“明天被抓”。', sp: ['信息差爽点', '打脸', '升级明确'] },
    { title: '开局签到一座城', logline: '每日签到获得城市模块，在乱世里亲手建起一座城。', hook: '第一天签到，得到的是一座废弃火车站。', sp: ['基建经营', '收服人才', '节奏快'] },
    { title: '我的影子会说话', logline: '主角的影子拥有独立意识，替他做出每一个“正确”的选择——直到它开始撒谎。', hook: '影子说：“别开门，门外那个是你自己。”', sp: ['悬疑反转', '高概念', '人设新'] },
  ]
  const ids: number[] = []
  for (let i = 0; i < (b.count || 3); i++) {
    const p = pool[i % pool.length]
    const id = nid(); ids.push(id)
    db.ideas.unshift({ id, book_id: null, title: p.title, logline: p.logline, selling_points: p.sp, hook: p.hook, genre, arc: ['小城立足，收服第一批班底', '打进州府，压服本地世家', '登临王朝，与皇权正面交锋', '飞升上界，挑战旧神秩序'], endgame: '查清金手指的来历，站到这个世界的最顶端', issue: i === 2 ? '高概念好，但爽点兑现偏慢' : '', scores: { heat: 82 - i * 6, novelty: 74 - i * 5, fit: 76 - i * 4, overall: 77 - i * 5 }, chosen: false })
  }
  return { idea_ids: ids }
}))
on('GET', '/ideas', () => db.ideas)
const ideaHist: Record<number, Idea[]> = {}
on('POST', '/ideas/:id/revise', (m, b) => {
  const idea = must(db.ideas.find((x) => x.id === +m[1]), '选题')
  return createJob('idea_revise', null, 2200, ['按意见修改…', '重新打分…'], () => {
    ;(ideaHist[idea.id] ??= []).push({ ...idea })
    Object.assign(idea, { logline: `${idea.logline.replace(/（已按.*）$/, '')}（已按“${String(b.instruction).slice(0, 16)}”调整）`, versions: ideaHist[idea.id].length, last_instruction: b.instruction })
    return { idea_id: idea.id, change: '调整了简介' }
  })
})
on('GET', '/ideas/:id', (m) => must(db.ideas.find((x) => x.id === +m[1]), '选题'))
on('PATCH', '/ideas/:id', (m, b) => {
  const idea = must(db.ideas.find((x) => x.id === +m[1]), '选题')
  ;(ideaHist[idea.id] ??= []).push({ ...idea })
  Object.assign(idea, b, { versions: ideaHist[idea.id].length, last_instruction: '手动修改' })
  return idea
})
on('POST', '/ideas/:id/suggest', (m, b) => {
  const idea = must(db.ideas.find((x) => x.id === +m[1]), '选题') as any
  const cur = (b.draft ?? idea)[b.field] ?? idea[b.field]
  const note = String(b.instruction || '改写').slice(0, 10)
  return createJob('idea_field', null, 1500, ['AI 改写…'], () => ({ field: b.field, value: Array.isArray(cur) ? cur.map((x: string) => `${x}（${note}）`) : `${cur}（${note}）` }))
})
on('POST', '/ideas/rescore', () => createJob('idea_rescore', null, 2000, ['复核打分…'], () => {
  db.ideas.filter((x) => !x.chosen).forEach((x, k) => { const n = 35 + ((k * 17) % 50), f = 40 + ((k * 23) % 50); x.scores = { ...x.scores, novelty: n, fit: f, overall: Math.round(0.15 * x.scores.heat + 0.35 * n + 0.5 * f) } })
  return { count: db.ideas.length }
}))
on('POST', '/ideas/:id/rescore', (m) => {
  const idea = must(db.ideas.find((x) => x.id === +m[1]), '选题')
  return createJob('idea_rescore', null, 1500, ['编辑复核打分…'], () => { idea.scores = { ...idea.scores, novelty: 70, fit: 78, overall: Math.round(0.3 * idea.scores.heat + 0.3 * 70 + 0.4 * 78) }; return { idea_id: idea.id } })
})
on('POST', '/ideas/:id/undo', (m) => {
  const idea = must(db.ideas.find((x) => x.id === +m[1]), '选题')
  const prev = ideaHist[idea.id]?.pop()
  if (prev) Object.assign(idea, prev)
  return idea
})
on('POST', '/ideas/clear', () => { const n = db.ideas.filter((x) => !x.chosen).length; db.ideas = db.ideas.filter((x) => x.chosen); return { deleted: n } })
on('DELETE', '/ideas/:id', (m) => { must(db.ideas.find((x) => x.id === +m[1]), '选题'); db.ideas = db.ideas.filter((x) => x.id !== +m[1]); return { ok: true } })
on('POST', '/ideas/:id/adopt', (m) => {
  const idea = must(db.ideas.find((x) => x.id === +m[1]), '选题')
  const book: Book = { id: nid(), title: idea.title, genre: idea.genre, gender: 'male', tagline: idea.logline, status: 'bible', target_words: 1_000_000, chapter_words: 2200, cover_url: null, created_at: now(), updated_at: now(), stats: { chapters: 0, words: 0, foreshadow_open: 0 } }
  db.books.push(book); idea.chosen = true; idea.book_id = book.id; return book
})

on('POST', '/books/:id/bible/generate', (m) => { const b = bookOf(m[1]); return createJob('bible_generate', b.id, 4000, ['生成世界观…', '设计力量体系…', '塑造人物…', '校验设定一致性…'], () => {
  const add = (type: Card['type'], name: string, summary: string, data: Record<string, any>) => db.cards.push({ id: nid(), book_id: b.id, type, name, summary, data, known_by: [], updated_at: now() })
  if (!db.cards.some((c) => c.book_id === b.id)) {
    add('world', '故事世界', `${b.genre}背景下的主舞台。`, { 时代: '架空现代' })
    add('character', '主角', '性格坚韧，有一个不能说的秘密。', { 年龄: '22', voice: '说话直，爱抬杠', catchphrases: ['那又怎样'], habits: ['摸鼻子'], demeanor: '笑起来只有一边嘴角' })
    add('cheat', '金手指', '主角的核心外挂。', { input: '触碰货架', limit: '每日一次', growth: '信用点升级' })
  }
  if (b.status === 'bible' || b.status === 'idea') b.status = 'outline'
  return { cards: 3 }
}) })
on('GET', '/books/:id/cards', (m, _b, u) => { const t = u.searchParams.get('type'); return db.cards.filter((c) => c.book_id === +m[1] && (!t || c.type === t)) })
on('POST', '/books/:id/cards', (m, b) => { const c = { id: nid(), book_id: +m[1], type: b.type, name: b.name, summary: b.summary ?? '', data: b.data ?? {}, known_by: b.known_by ?? [], updated_at: now() }; db.cards.push(c); return c })
on('PUT', '/cards/:id', (m, b) => Object.assign(must(db.cards.find((c) => c.id === +m[1]), '设定卡'), b, { updated_at: now() }))
on('DELETE', '/cards/:id', (m) => { db.cards = db.cards.filter((c) => c.id !== +m[1]); return null })
on('GET', '/books/:id/facts', (m) => db.cards.filter((c) => c.book_id === +m[1]).slice(0, 4).map((c, i) => ({ id: 5000 + i, book_id: +m[1], entity_id: c.id, key: Object.keys(c.data)[0] ?? '描述', value: String(Object.values(c.data)[0] ?? c.summary), from_chapter: 1, to_chapter: null, visibility: i % 2 ? 'reader' : 'author' })))

on('POST', '/books/:id/outline/generate', (m) => { const b = bookOf(m[1]); return createJob('outline_generate', b.id, 4500, ['生成总纲…', '切分卷结构…', '展开前两弧…', '写章细纲…'], () => {
  if (!db.outline.some((o) => o.book_id === b.id)) {
    const r = { id: nid(), book_id: b.id, parent_id: null, level: 'book', order: 0, title: `总纲：${b.title}`, summary: b.tagline || '主线故事', beats: null, status: 'expanded', chapter_id: null } as OutlineNode
    db.outline.push(r)
    const v = { id: nid(), book_id: b.id, parent_id: r.id, level: 'volume', order: 0, title: '第一卷 · 开局', summary: '主角入局，确立金手指与第一个敌人。', beats: null, status: 'expanded', chapter_id: null } as OutlineNode
    db.outline.push(v)
    const a = { id: nid(), book_id: b.id, parent_id: v.id, level: 'arc', order: 0, title: '弧一 · 黄金三章', summary: '三章内完成困境、金手指、第一次打脸。', beats: null, status: 'expanded', chapter_id: null } as OutlineNode
    db.outline.push(a)
    for (let i = 1; i <= 5; i++) db.outline.push({ id: nid(), book_id: b.id, parent_id: a.id, level: 'chapter', order: i, title: `第${i}章`, summary: '本章细纲：开场冲突 → 金手指显现 → 章尾钩子。', beats: { 钩子: '章尾悬念' }, status: 'planned', chapter_id: null })
  }
  b.status = 'writing'
  return {}
}) })
on('POST', '/outline/:id/expand', (m) => { const n = must(db.outline.find((o) => o.id === +m[1]), '节点'); return createJob('outline_expand', n.book_id, 3000, ['读取上层大纲…', '滚动展开下一层…'], () => {
  const next = n.level === 'book' ? 'volume' : n.level === 'volume' ? 'arc' : 'chapter'
  const k = db.outline.filter((o) => o.parent_id === n.id).length
  for (let i = 0; i < 3; i++) db.outline.push({ id: nid(), book_id: n.book_id, parent_id: n.id, level: next, order: k + i, title: `${next === 'chapter' ? '新章' : next === 'arc' ? '新弧' : '新卷'} ${k + i + 1}`, summary: '滚动展开生成的细纲。', beats: null, status: 'planned', chapter_id: null })
  n.status = 'expanded'
  return {}
}) })
on('GET', '/books/:id/outline', (m) => db.outline.filter((o) => o.book_id === +m[1]))
on('DELETE', '/outline/:id', (m) => {
  const n = must(db.outline.find((o) => o.id === +m[1]), '节点')
  if (n.level === 'book') throw new HttpErr(400, '总纲不能删除，可以重新生成大纲')
  const ids = new Set<number>([n.id]); let grew = true
  while (grew) { grew = false; for (const o of db.outline) if (o.parent_id != null && ids.has(o.parent_id) && !ids.has(o.id)) { ids.add(o.id); grew = true } }
  const linked = db.chapters.filter((c) => db.outline.some((o) => ids.has(o.id) && o.chapter_id === c.id))
  if (linked.some((c) => c.status === 'committed')) throw new HttpErr(409, '这部分大纲下已有提交入账的章节，不能删除')
  db.chapters = db.chapters.filter((c) => !linked.includes(c)); db.outline = db.outline.filter((o) => !ids.has(o.id))
  return { deleted: ids.size }
})
on('DELETE', '/chapters/:id', (m) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  if (c.status === 'committed') throw new HttpErr(409, '已提交入账的章节不能删除')
  db.outline.forEach((o) => { if (o.chapter_id === c.id) { o.chapter_id = null; if (o.status === 'written') o.status = 'planned' } })
  db.chapters = db.chapters.filter((x) => x.id !== c.id); return { ok: true }
})
on('PUT', '/outline/:id', (m, b) => Object.assign(must(db.outline.find((o) => o.id === +m[1]), '节点'), b))

const strip = (c: Chapter) => { const { content, variants, ...rest } = c; void content; return { ...rest, variants: variants?.map((v) => ({ ...v, content: '' })) } }
on('GET', '/books/:id/chapters', (m) => db.chapters.filter((c) => c.book_id === +m[1]).sort((a, b) => a.number - b.number).map(strip))
on('GET', '/chapters/:id', (m) => must(db.chapters.find((c) => c.id === +m[1]), '章节'))
on('PUT', '/chapters/:id', (m, b) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  Object.assign(c, { title: b.title ?? c.title, content: b.content ?? c.content, updated_at: now() })
  c.words = countWords(c.content ?? '')
  recalc(c.book_id)
  return c
})
function writeOne(bookId: number, variants: number) {
  const n = db.chapters.filter((c) => c.book_id === bookId).length + 1
  const content = buildChapterText(n + 2)
  const ch: Chapter = { id: nid(), book_id: bookId, number: n, title: `第${n}章 新的交易`, content, words: countWords(content), status: variants > 1 ? 'draft' : 'reviewing', review: mkReview(n, content), lint: mkLint(content), updated_at: now(), changes: { new_entities: [], state_changes: [{ entity: '主角', change: '信用点 +5' }], foreshadow: [{ action: 'plant', id: null, desc: '新的线索' }] } }
  if (variants > 1) {
    ch.variants = Array.from({ length: variants }, (_, v): ChapterVariant => { const c = buildChapterText(n + v * 3, 14 + v); return { id: nid(), content: c, words: countWords(c), lint: mkLint(c), review_overall: 70 + ((n + v * 7) % 15) } })
    ch.content = ch.variants[0].content
  }
  db.chapters.push(ch)
  recalc(bookId)
  return ch
}
on('POST', '/books/:id/chapters/write-next', (m, b) => { const book = bookOf(m[1]); const v = Math.min(3, Math.max(1, b.variants || 1)); return createJob('write_next', book.id, 5200 + v * 800, ['取下一章细纲…', '组装上下文包…', v > 1 ? `并行写作 ${v} 个版本…` : '写作正文…', '一致性检查…', '证据式审稿…', '人味 lint…', '定点重写…'], () => ({ chapter_id: writeOne(book.id, v).id })) })
on('POST', '/books/:id/chapters/write-batch', (m, b) => { const book = bookOf(m[1]); const n = Math.min(10, b.count || 3); return createJob('write_batch', book.id, 2500 * n, Array.from({ length: n }, (_, i) => `写作第 ${i + 1}/${n} 章…`), () => ({ chapter_ids: Array.from({ length: n }, () => writeOne(book.id, 1).id) })) })
on('POST', '/chapters/:id/review', (m) => { const c = must(db.chapters.find((x) => x.id === +m[1]), '章节'); return createJob('review', c.book_id, 3000, ['节奏编辑审稿…', '爽点编辑审稿…', '人物编辑审稿…', '汇总分数…'], () => { c.review = mkReview(c.number + 1, c.content ?? ''); c.lint = mkLint(c.content ?? ''); c.status = 'reviewing'; return {} }) })
on('POST', '/chapters/:id/humanize', (m) => { const c = must(db.chapters.find((x) => x.id === +m[1]), '章节'); return createJob('humanize', c.book_id, 3200, ['确定性 lint…', '定位 AI 腔片段…', '定点重写…'], () => { c.content = (c.content ?? '').replace(/不禁/g, '').replace(/一切都在往好的方向发展/g, '日子好像真的松动了一点'); c.lint = mkLint(c.content); c.words = countWords(c.content); return {} }) })
on('POST', '/chapters/:id/thicken', (m) => { const c = must(db.chapters.find((x) => x.id === +m[1]), '章节'); return createJob('thicken', c.book_id, 3600, ['识别干对白与概述段落…', '补动作与神态…', '补环境与心理…', '校验情节未改变…'], () => {
  c.content = (c.content ?? '').split('\n').map((p) => THICKEN_MAP[p.trim()] ?? p).join('\n')
  c.words = countWords(c.content); c.lint = mkLint(c.content); recalc(c.book_id)
  return { changed: true }
}) })
on('POST', '/chapters/:id/adopt-variant', (m, b) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  const v = must(c.variants?.find((x) => x.id === b.variant_id), '版本')
  Object.assign(c, { content: v.content, words: v.words, lint: v.lint, status: 'reviewing', variants: [], updated_at: now() })
  recalc(c.book_id)
  return c
})
on('POST', '/chapters/:id/commit', (m) => { const c = must(db.chapters.find((x) => x.id === +m[1]), '章节'); if (c.variants?.length) throw new HttpErr(409, '请先采纳一个版本再提交'); c.status = 'committed'; c.updated_at = now(); return c })

on('GET', '/books/:id/foreshadows', (m) => db.foreshadows.filter((f) => f.book_id === +m[1]))

const pkgOf = (id: number) => db.packages.get(id) ?? { book_id: id, titles: [], blurb: '', tags: [], cover_prompt: '', covers: [], chosen_cover: null }
on('POST', '/books/:id/package/generate', (m) => { const b = bookOf(m[1]); return createJob('package_generate', b.id, 3500, ['分析题材卖点…', '生成书名候选…', '撰写简介…', '匹配番茄标签…'], () => {
  const p = pkgOf(b.id)
  db.packages.set(b.id, { ...p, titles: [{ title: b.title, score: 84 }, { title: `${b.genre}：${b.title.slice(-4)}`, score: 77 }, { title: `开局${b.title.slice(0, 4)}`, score: 70 }], blurb: p.blurb || `${b.tagline || '一段不一样的故事。'}\n\n（以上为演示模式生成的简介）`, tags: p.tags.length ? p.tags : [b.genre, '爽文', '系统'], cover_prompt: p.cover_prompt || `${b.genre}题材小说封面，竖版构图，电影感光影，顶部留出书名区域` })
  if (b.status === 'writing') b.status = 'packaging'
  return {}
}) })
on('POST', '/books/:id/covers/generate', (m, body) => { const b = bookOf(m[1]); return createJob('covers_generate', b.id, 4200, ['组装封面提示词…', '调用生图模型…', '叠加书名排版…'], () => {
  const p = pkgOf(b.id)
  const shift = (p.covers.length / 4) | 0
  db.packages.set(b.id, { ...p, covers: [...p.covers, ...Array.from({ length: body.n || 4 }, (_, i) => coverDataUrl(b.title, i + shift + 1 + p.covers.length))] })
  return {}
}) })
on('POST', '/books/:id/cards/suggest', (m, body) => { const b = bookOf(m[1]); const d = body.draft ?? {}; return createJob('card_suggest', b.id, 1200, ['按要求改设定…'], () => {
  if (!body.field) return { card: { ...d, summary: `${d.summary ?? ''}${body.instruction ? `（${body.instruction}）` : ''}` } }
  if (body.field === 'catchphrases' || body.field === 'habits') return { value: ['这事我接了', '先看看再说'] }
  return { value: `改写后的内容${body.instruction ? `：${body.instruction}` : ''}` }
}) })
on('POST', '/books/:id/covers/prompt', (m, body) => { const b = bookOf(m[1]); return createJob('cover_prompt', b.id, 1500, ['按要求改提示词…'], () => ({ prompt: `${body.current || '主角立于高处'}\n${body.instruction}` })) })
on('POST', '/books/:id/covers/delete', (m, body) => { const id = +m[1]; const p = pkgOf(id); const covers = p.covers.filter((u: string) => u !== body.url); const chosen = p.chosen_cover === body.url ? covers[covers.length - 1] ?? null : p.chosen_cover; const n = { ...p, covers, chosen_cover: chosen }; db.packages.set(id, n); bookOf(m[1]).cover_url = chosen; return n })
on('GET', '/books/:id/package', (m) => pkgOf(+m[1]))
on('PUT', '/books/:id/package', (m, b) => { const p = { ...pkgOf(+m[1]), ...b }; db.packages.set(+m[1], p); if (b.chosen_cover) bookOf(m[1]).cover_url = b.chosen_cover; return p })

on('GET', '/books/:id/style', (m) => db.styles.get(+m[1]) ?? { sample_text: '', voice_notes: '', pov: 'third', tone: '', extracted: null })
on('PUT', '/books/:id/style', (m, b) => { const s = { ...(db.styles.get(+m[1]) ?? { sample_text: '', voice_notes: '', pov: 'third', tone: '', extracted: null }), ...b }; db.styles.set(+m[1], s); return s })
on('POST', '/books/:id/style/extract', (m) => { const b = bookOf(m[1]); return createJob('style_extract', b.id, 3000, ['切句与分段…', '统计句长分布…', '分析描写密度与对话写法…'], () => {
  const s = db.styles.get(b.id)
  if (!s?.sample_text) throw new Error('请先粘贴范文')
  const a = analyzeText(s.sample_text)
  s.extracted = {
    stats: {
      words: countWords(s.sample_text),
      avg_sentence_len: +a.avg_sentence_len.toFixed(1),
      short_sentence_ratio: +a.short_sentence_ratio.toFixed(3),
      sentence_len_hist: Object.fromEntries(a.sentence_hist.map((h) => [h.bucket, +h.ratio.toFixed(3)])),
      dialogue_ratio: +a.dialogue_ratio.toFixed(3),
      descriptor_per_k: 38.5,
      bare_dialogue_ratio: +a.bare_dialogue_ratio.toFixed(3),
      summary_ratio: +a.summary_ratio.toFixed(3),
    },
    llm: {
      summary: '白描为主，用具体物件传递情绪，长短句交替，不直接写心理。',
      techniques: ['先写看见的，再写想到的', '对白后紧跟一个动作或环境细节', '情绪靠物件承载（冻僵的狗、冷灰）', '环境用长句铺开，转折处用三五字短句收住'],
      dialogue_style: '对白短促，常以动作或环境收尾，很少用“他说”这类说明标签。',
      description_style: '抓一两个有温度的细节，不堆形容词。',
      avoid: ['直接写“他很难过”', '“不禁”“仿佛”等 AI 腔词'],
    },
    excerpt: s.sample_text,
    excerpt_words: countWords(s.sample_text),
  }
  return {}
}) })

on('GET', '/books/:id/export', () => new Response(new Blob(['NovelOS 演示模式导出的发布包占位文件。\n真实后端会返回 zip：建书资料.md、chapters/*.txt、cover.png、AI申报提示.md。\n'], { type: 'text/plain' }), { status: 200, headers: { 'Content-Disposition': `attachment; filename*=UTF-8''${encodeURIComponent('发布包-演示.txt')}` } }))

// ================================================================ v0.4：按要求让 AI 改（补齐前端 mock）
const DEFAULT_TROPES: Trope[] = [
  { name: '父母失踪/神秘消失', keywords: ['父亲失踪', '母亲失踪', '父母失踪', '父母神秘消失'] },
  { name: '隐藏身世/大人物之子', keywords: ['隐藏身世', '真实身世', '大人物之子', '私生子'] },
  { name: '神秘血脉', keywords: ['神秘血脉', '上古血脉', '血脉觉醒'] },
  { name: '退婚流', keywords: ['退婚', '悔婚', '解除婚约'] },
  { name: '被废天才/天才陨落', keywords: ['修为被废', '天才陨落', '丹田被废'] },
]
let tropeList: Trope[] = DEFAULT_TROPES.map((t) => ({ ...t, keywords: [...t.keywords] }))
const detectTropes = (text: string): TropeHit[] => tropeList.map((t) => ({ name: t.name, hits: t.keywords.filter((k) => text.includes(k)) })).filter((h) => h.hits.length)
const bookHist: Record<number, (BookInfo & { instruction: string })[]> = {}
const nodeHist: Record<number, { title: string; summary: string; beats: any }[]> = {}
const chHist: Record<number, { content: string; title: string; label: string }[]> = {}
const bibleSnaps: { id: number; book_id: number; note: string; cards: Card[]; created_at: string }[] = []
const QUOTE_RX = /[『「“"]([^』」”"]{2,20})[』」”"]/g
const termsOf = (ins: string) => {
  const out = [...ins.matchAll(QUOTE_RX)].map((x) => x[1])
  const neg = ins.match(/(?:不要|别|去掉|弱化)(?:再)?(?:强调|提|用)?([\u4e00-\u9fa5]{2,4}?)(?=[，,。、\s]|$)/)
  if (neg && !out.includes(neg[1])) out.push(neg[1])
  return out
}
const infoOf = (b: Book): BookInfo => ({ title: b.title, tagline: b.tagline, premise: b.premise ?? '' })
const strip2 = (s: string, terms: string[], reps: Record<string, string> = {}) => terms.reduce((x, t) => x.split(t).join(reps[t] ?? ''), s).replace(/[，,]{2,}/g, '，')
function impactOf(bookId: number, terms: string[]): Impact {
  const cards = db.cards.filter((c) => c.book_id === bookId).filter((c) => terms.some((t) => JSON.stringify(c).includes(t)))
    .map((c) => ({ id: c.id, name: c.name, type: c.type, terms: terms.filter((t) => JSON.stringify(c).includes(t)), snippet: c.summary.slice(0, 40) }))
  const outline = db.outline.filter((n) => n.book_id === bookId).filter((n) => terms.some((t) => `${n.title}${n.summary}`.includes(t)))
    .map((n) => ({ id: n.id, level: n.level, order: n.order, title: n.title, status: n.status, terms: terms.filter((t) => `${n.title}${n.summary}`.includes(t)), snippet: n.summary.slice(0, 40) }))
  const chapters = db.chapters.filter((c) => c.book_id === bookId && terms.some((t) => (c.content ?? '').includes(t)))
    .map((c) => ({ id: c.id, number: c.number, title: c.title, status: c.status, terms: terms.filter((t) => (c.content ?? '').includes(t)), count: 1, snippet: '' }))
  return { terms, cards, outline, chapters, total: cards.length + outline.length + chapters.length }
}
function reviseResult(b: Book, ins: string) {
  const terms = termsOf(ins)
  const reps = Object.fromEntries(terms.map((t) => [t, ins.includes(`『${t}』`) || ins.includes(`“${t}”`) ? `无名${t.slice(-2)}` : '']))
  const cur = infoOf(b)
  const proposal = { title: cur.title, tagline: strip2(cur.tagline, terms, reps) + '（已按要求调整）', premise: strip2(cur.premise, terms, reps) }
  return { book_id: b.id, instruction: ins, current: cur, proposal, change: `按“${ins.slice(0, 12)}”改了简介`, terms, replacements: reps, impact: impactOf(b.id, terms), trope_hits: detectTropes(JSON.stringify(proposal)) }
}
function snapBible(bookId: number, note: string) {
  const s = { id: nid(), book_id: bookId, note, cards: db.cards.filter((c) => c.book_id === bookId).map((c) => ({ ...c, data: { ...c.data } })), created_at: now() }
  bibleSnaps.unshift(s)
  return s
}
function applyBibleOps(bookId: number, ops: BibleOp[], note: string) {
  const snap = snapBible(bookId, note)
  const n = { created: 0, updated: 0, deleted: 0 }
  for (const op of ops) {
    if (op.op === 'delete') { db.cards = db.cards.filter((c) => !(c.id === op.card_id && c.book_id === bookId)); n.deleted++ }
    else if (op.op === 'update') { const c = db.cards.find((x) => x.id === op.card_id); if (c && op.card) { Object.assign(c, op.card, { updated_at: now() }); n.updated++ } }
    else if (op.card) { db.cards.push({ ...op.card, id: nid(), book_id: bookId, updated_at: now() }); n.created++ }
  }
  return { ...n, snapshot_id: snap.id }
}
function bibleProposalOf(bookId: number, mode: 'rewrite' | 'add' | 'optimize', ins: string, terms: string[] = [], reps: Record<string, string> = {}): BibleProposal {
  const cards = db.cards.filter((c) => c.book_id === bookId)
  const items: BibleItem[] = []
  if (mode === 'optimize') {
    const hit = terms.length ? cards.filter((c) => terms.some((t) => JSON.stringify(c).includes(t))) : cards.slice(0, 2)
    hit.forEach((c, i) => items.push({ key: `n${i + 1}`, action: 'update', target_id: c.id, old: { ...c }, conflicts: [], trope_hits: [], default: 'replace',
      card: { type: c.type, name: strip2(c.name, terms, reps) || c.name, summary: terms.length ? strip2(c.summary, terms, reps) : `${c.summary}（${ins.slice(0, 8)}）`, data: c.data, known_by: c.known_by } }))
  } else {
    items.push({ key: 'n1', action: 'add', target_id: null, old: null, conflicts: [], trope_hits: [], default: 'add', card: { type: 'character', name: '茶馆掌柜', summary: '消息灵通，两头下注。', data: { role: 'supporting' }, known_by: [] } })
    const first = cards[0]
    if (first) items.push({ key: 'n2', action: 'add', target_id: null, old: { ...first }, trope_hits: [], default: 'keep_old', card: { type: first.type, name: first.name, summary: `另一版本：${ins.slice(0, 10)}`, data: {}, known_by: [] },
      conflicts: [{ card_id: first.id, name: first.name, type: first.type, reason: '同名设定，简介与旧卡矛盾', source: 'program' }] })
  }
  return { book_id: bookId, mode, instruction: ins, change: `按“${ins.slice(0, 12)}”${mode === 'optimize' ? '优化' : '新增'}设定`, items, removals: [], facts: [],
    counts: { add: items.filter((x) => !x.conflicts.length && x.action === 'add').length, review: items.filter((x) => x.conflicts.length || x.action === 'update').length, removals: 0 } }
}
function rewriteText(text: string, ins: string) {
  const paras = text.split('\n').filter((p) => p.trim())
  return paras.map((p, i) => (i % 3 === 1 ? (ins.includes('对话') ? `${p}“就这样？”有人低声问了一句。` : p.replace(/，[^，。]{0,12}。$/, '。')) : p)).join('\n')
}

on('POST', '/books/:id/revise', (m, b) => { const book = bookOf(m[1]); return createJob('book_revise', book.id, 1600, ['按要求改作品信息…', '检查下游影响…'], () => reviseResult(book, String(b.instruction ?? ''))) })
on('POST', '/books/:id/info', (m, b) => {
  const book = bookOf(m[1])
  ;(bookHist[book.id] ??= []).push({ ...infoOf(book), instruction: b.instruction || '手动修改' })
  for (const k of ['title', 'tagline', 'premise'] as const) if (b[k] != null) (book as any)[k] = b[k]
  return Object.assign(book, { versions: bookHist[book.id].length, last_instruction: b.instruction, updated_at: now() })
})
on('POST', '/books/:id/undo', (m) => {
  const book = bookOf(m[1])
  const prev = bookHist[book.id]?.pop()
  if (!prev) throw new HttpErr(409, '没有可以撤回的版本')
  return Object.assign(book, { title: prev.title, tagline: prev.tagline, premise: prev.premise, versions: bookHist[book.id].length })
})
on('POST', '/books/:id/impact', (m, b) => impactOf(+m[1], b.terms ?? []))
on('POST', '/books/:id/sync', (m, b) => createJob('book_sync', +m[1], 2000, ['同步设定库…', '同步大纲…'], () => {
  const imp = impactOf(+m[1], b.terms ?? [])
  const items: OutlineSyncItem[] = imp.outline.map((x) => { const n = db.outline.find((o) => o.id === x.id)!; return { node_id: n.id, level: n.level, old: { title: n.title, summary: n.summary }, new: { title: strip2(n.title, b.terms, b.replacements), summary: strip2(n.summary, b.terms, b.replacements) }, reason: '拿掉旧说法' } })
  return { terms: imp.terms, replacements: b.replacements, bible: imp.cards.length ? bibleProposalOf(+m[1], 'optimize', b.instruction, b.terms, b.replacements) : null, outline: { items }, chapters: imp.chapters }
}))
on('POST', '/books/:id/bible/propose', (m, b) => createJob('bible_propose', +m[1], 2200, ['AI 生成设定…', '检测冲突…'], () => bibleProposalOf(+m[1], b.mode, String(b.instruction ?? ''))))
on('POST', '/books/:id/bible/apply', (m, b) => applyBibleOps(+m[1], b.ops ?? [], `${b.mode}前`))
on('GET', '/books/:id/bible/snapshots', (m) => bibleSnaps.filter((s) => s.book_id === +m[1]).map((s) => ({ id: s.id, note: s.note, count: s.cards.length, created_at: s.created_at, names: s.cards.slice(0, 12).map((c) => c.name) })))
on('POST', '/books/:id/bible/snapshots/:sid/restore', (m) => {
  const snap = must(bibleSnaps.find((s) => s.id === +m[2] && s.book_id === +m[1]), '快照')
  const before = snapBible(+m[1], `回滚到「${snap.note}」之前`)
  db.cards = [...db.cards.filter((c) => c.book_id !== +m[1]), ...snap.cards.map((c) => ({ ...c }))]
  return { restored: snap.cards.length, snapshot_id: before.id }
})
on('POST', '/outline/:id/suggest', (m, b) => { const n = must(db.outline.find((o) => o.id === +m[1]), '节点'); return createJob('outline_node', n.book_id, 1400, ['AI 重写节点…'], () => ({ node_id: n.id, current: { title: n.title, summary: n.summary }, proposal: { title: n.title, summary: `${n.summary}（按“${String(b.instruction).slice(0, 10)}”重写）` }, change: '重写了概要', instruction: b.instruction })) })
on('POST', '/outline/:id/undo', (m) => {
  const n = must(db.outline.find((o) => o.id === +m[1]), '节点')
  const prev = nodeHist[n.id]?.pop()
  if (!prev) throw new HttpErr(409, '没有可以撤回的版本')
  return Object.assign(n, prev, { versions: nodeHist[n.id].length })
})
on('POST', '/books/:id/outline/apply', (_m, b) => {
  let updated = 0
  for (const it of b.items ?? []) {
    const n = db.outline.find((o) => o.id === it.node_id)
    if (!n) continue
    ;(nodeHist[n.id] ??= []).push({ title: n.title, summary: n.summary, beats: n.beats })
    Object.assign(n, { title: it.title ?? n.title, summary: it.summary ?? n.summary, versions: nodeHist[n.id].length, last_instruction: b.instruction })
    updated++
  }
  return { updated }
})
on('POST', '/chapters/:id/rewrite', (m, b) => { const c = must(db.chapters.find((x) => x.id === +m[1]), '章节'); return createJob('chapter_rewrite', c.book_id, 2400, ['按要求改写…', '人味检查…'], () => {
  const before = c.content ?? ''
  const after = rewriteText(before, String(b.instruction ?? ''))
  return { chapter_id: c.id, scope: 'all', before, after, changed: before !== after, words_before: countWords(before), words_after: countWords(after), ai_score_after: mkLint(after).ai_score }
}) })
on('POST', '/chapters/:id/apply-rewrite', (m, b) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  ;(chHist[c.id] ??= []).push({ content: c.content ?? '', title: c.title, label: b.label || '按要求改写前' })
  Object.assign(c, { content: b.content, words: countWords(b.content), lint: mkLint(b.content), history: chHist[c.id].length, last_history_label: b.label, updated_at: now() })
  return c
})
on('POST', '/chapters/:id/undo', (m) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  const prev = chHist[c.id]?.pop()
  if (!prev) throw new HttpErr(409, '没有可以撤回的版本')
  return Object.assign(c, { content: prev.content, title: prev.title, words: countWords(prev.content), lint: mkLint(prev.content), history: chHist[c.id].length })
})
on('POST', '/ideas/:id/detrope', (m) => {
  const idea = must(db.ideas.find((x) => x.id === +m[1]), '选题')
  const hits = detectTropes(JSON.stringify(idea))
  if (!hits.length) throw new HttpErr(409, '这个选题没有命中禁用套路')
  return createJob('idea_revise', null, 1600, ['换掉俗套…'], () => { idea.logline = strip2(idea.logline, hits.flatMap((h) => h.hits)); return { idea_id: idea.id } })
})
on('GET', '/settings/tropes', () => ({ banned: tropeList, defaults: DEFAULT_TROPES }))
on('PUT', '/settings/tropes', (_m, b) => { tropeList = b.banned ?? []; return { banned: tropeList, defaults: DEFAULT_TROPES } })
on('GET', '/books/:id/foreshadows/overview', (m) => {
  const chs = db.chapters.filter((c) => c.book_id === +m[1])
  return { outline_planned: [], committed: chs.filter((c) => c.status === 'committed').length, drafts: chs.filter((c) => c.status !== 'committed').length,
    outline_nodes: db.outline.filter((n) => n.book_id === +m[1]).length, last_committed: Math.max(0, ...chs.filter((c) => c.status === 'committed').map((c) => c.number)) }
})
on('POST', '/books/:id/foreshadows/plan', (m, b) => createJob('foreshadow_plan', +m[1], 1800, ['读大纲和设定…', '规划长短线伏笔…'], () => ({ book_id: +m[1], current: 0, outline_max: 8,
  items: Array.from({ length: Math.min(8, b.count || 3) }, (_, i): ForeshadowPlanItem => ({ desc: ['摩托帮账本上被撕掉的一页', '苏晚袖口的旧针眼', '超市地下室那扇锁死的门', '金牙脖子上的旧伤'][i % 4], tier: (['short', 'mid', 'long'] as const)[i % 3], plant_ch: 2 + i, resolve_ch: 8 + i * 10, note: '先当环境细节写，后面揭开', related: ['林野'] })) })))
on('POST', '/books/:id/foreshadows/batch', (m, b) => {
  let created = 0
  for (const it of b.items ?? []) { db.foreshadows.push({ id: nid(), book_id: +m[1], desc: it.desc, status: 'planned', planted_ch: 0, last_ch: 0, resolved_ch: null, tier: it.tier, plan_plant_ch: it.plant_ch, plan_resolve_ch: it.resolve_ch, note: it.note, source: it.source ?? 'ai' }); created++ }
  return { created, attached: b.attach ? created : 0 }
})
on('POST', '/books/:id/foreshadows', (m, b) => { const f: Foreshadow = { id: nid(), book_id: +m[1], desc: b.desc, status: b.status ?? 'planned', planted_ch: b.planted_ch ?? 0, last_ch: b.planted_ch ?? 0, resolved_ch: b.resolved_ch ?? null, tier: b.tier ?? '', plan_plant_ch: b.plan_plant_ch ?? null, plan_resolve_ch: b.plan_resolve_ch ?? null, note: b.note ?? '', source: 'manual' }; db.foreshadows.push(f); recalc(+m[1]); return f })
on('PUT', '/foreshadows/:id', (m, b) => { const f = must(db.foreshadows.find((x) => x.id === +m[1]), '伏笔'); Object.assign(f, b); recalc(f.book_id); return f })
on('DELETE', '/foreshadows/:id', (m) => { const f = must(db.foreshadows.find((x) => x.id === +m[1]), '伏笔'); db.foreshadows = db.foreshadows.filter((x) => x.id !== f.id); recalc(f.book_id); return { ok: true } })

// ================================================================ v0.5：每本书的专属 Agent（规则脚本，逐步出现）
type MProposal = AgentProposal & { _undo?: () => void }
interface MSession { id: number; book_id: number; title: string; created_at: string; updated_at: string; messages: AgentMessage[]; queue: { at: number; fn: () => void }[]; job: (typeof db.jobs)[number] | null; stop?: boolean }
const agentSessions: MSession[] = []
const agentProposals: MProposal[] = []
const autoApply = new Map<number, boolean>()
const TOOL_INFO: AgentToolInfo[] = [
  ['get_book_info', '读作品信息', 'read'], ['search_bible', '检索设定库', 'read'], ['get_card', '读设定卡', 'read'], ['get_outline', '读大纲树', 'read'],
  ['get_outline_node', '读大纲节点', 'read'], ['list_chapters', '列章节', 'read'], ['get_chapter', '读章节', 'read'], ['list_foreshadows', '读伏笔', 'read'],
  ['get_style', '读文风', 'read'], ['get_package', '读包装', 'read'], ['get_banned_tropes', '读禁用套路', 'read'], ['find_mentions', '查影响范围', 'read'],
  ['web_search', '联网搜索', 'read'], ['revise_book_info', '改作品信息', 'write'], ['sync_downstream', '同步设定和大纲', 'write'], ['propose_bible', '改设定库', 'write'],
  ['delete_card', '删设定卡', 'write'], ['suggest_outline_node', '改大纲节点', 'write'], ['rewrite_chapter', '改写章节', 'write'], ['plan_foreshadows', '规划伏笔', 'write'],
  ['add_foreshadow', '加伏笔', 'write'], ['update_foreshadow', '改伏笔', 'write'], ['delete_foreshadow', '删伏笔', 'write'], ['propose_package', '改简介/包装', 'write'],
  ['revise_cover_prompt', '改封面提示词', 'write'], ['generate_covers', '生成封面', 'write'], ['write_next_chapter', '写下一章', 'write'],
].map(([name, label, kind]) => ({ name, label, kind: kind as 'read' | 'write', description: label }))
const toolLabel = (n: string) => TOOL_INFO.find((t) => t.name === n) ?? { label: n, kind: 'read' as const }
const KIND_LABEL: Record<string, string> = { book_info: '作品信息', bible: '设定库', outline_nodes: '大纲', chapter_rewrite: '章节改写', foreshadow_add: '新增伏笔', package: '包装', covers: '生成封面', write_chapter: '写下一章' }
const agentSessOut = (s: MSession): AgentSession => ({ id: s.id, book_id: s.book_id, title: s.title, messages: s.messages.length, running: s.queue.length > 0, running_job_id: s.queue.length ? s.job?.id ?? null : null, last_user: s.messages.filter((x) => x.role === 'user').at(-1)?.content.slice(0, 60) ?? '', created_at: s.created_at, updated_at: s.updated_at })
const pumpAgent = (s: MSession) => { const t = Date.now(); while (s.queue.length && s.queue[0].at <= t) { if (s.stop) { s.queue = []; addMsg(s, { role: 'notice', content: '已按你的要求停下。' }); break } s.queue.shift()!.fn() } }
function addMsg(s: MSession, m: Partial<AgentMessage>): AgentMessage {
  const msg: AgentMessage = { id: nid(), role: 'assistant', content: '', tool_calls: [], tool_call_id: '', name: '', summary: '', status: 'ok', proposal_ids: [], job_ids: [], created_at: now(), ...m }
  s.messages.push(msg); s.updated_at = now(); return msg
}
function mkProposal(s: MSession, kind: MProposal['kind'], title: string, summary: string, payload: Record<string, any>, extra: Partial<MProposal> = {}): MProposal {
  const p: MProposal = { id: nid(), book_id: s.book_id, session_id: s.id, message_id: null, kind, kind_label: KIND_LABEL[kind] ?? kind, title, summary, payload, status: 'pending', destructive: false, needs_review: false, auto_applied: false, result: null, error: '', job_id: null, revertible: false, created_at: now(), updated_at: now(), ...extra }
  if (kind === 'bible') p.needs_review = (payload.items ?? []).some((x: any) => x.conflicts?.length)
  agentProposals.push(p)
  if (autoApply.get(s.book_id) && !p.destructive && !p.needs_review) { try { applyMock(p); p.auto_applied = true } catch (e: any) { p.error = `自动采纳失败：${e?.detail ?? e?.message}` } }
  return p
}
function applyMock(p: MProposal, edited?: Record<string, any>, ops?: BibleOp[]) {
  const book = bookOf(String(p.book_id))
  const pl = p.payload
  if (p.kind === 'book_info') {
    const before = infoOf(book)
    ;(bookHist[book.id] ??= []).push({ ...before, instruction: 'Agent' })
    Object.assign(book, { ...pl.proposal, ...(edited ?? {}), versions: bookHist[book.id].length, updated_at: now() })
    p._undo = () => { Object.assign(book, before); bookHist[book.id].pop() }
  } else if (p.kind === 'bible') {
    const use = ops ?? (pl.items as BibleItem[]).filter((x) => !x.conflicts.length).map((x): BibleOp => (x.action === 'update' && x.target_id ? { op: 'update', card_id: x.target_id, card: x.card } : { op: 'create', card: x.card }))
    const r = applyBibleOps(book.id, use, 'Agent 改设定前')
    p.result = r
    p._undo = () => { const snap = bibleSnaps.find((x) => x.id === r.snapshot_id)!; db.cards = [...db.cards.filter((c) => c.book_id !== book.id), ...snap.cards] }
  } else if (p.kind === 'outline_nodes') {
    const olds = (pl.items as OutlineSyncItem[]).map((it) => { const n = db.outline.find((o) => o.id === it.node_id)!; const old = { title: n.title, summary: n.summary }; const e = edited?.items?.find((x: any) => x.node_id === it.node_id) ?? {}; Object.assign(n, it.new, e); return [n, old] as const })
    p._undo = () => olds.forEach(([n, old]) => Object.assign(n, old))
  } else if (p.kind === 'chapter_rewrite') {
    const c = must(db.chapters.find((x) => x.id === pl.chapter_id), '章节')
    if (c.content !== pl.before) throw new HttpErr(409, '这一章在提案之后又改过，请让 Agent 按现在的正文重新改')
    const content = edited?.content ?? pl.after
    Object.assign(c, { content, words: countWords(content), lint: mkLint(content) })
    p._undo = () => Object.assign(c, { content: pl.before, words: countWords(pl.before), lint: mkLint(pl.before) })
  } else if (p.kind === 'foreshadow_add') {
    const items = edited?.items ?? pl.items
    const ids = items.map((it: any) => { const f: Foreshadow = { id: nid(), book_id: book.id, desc: it.desc, status: 'planned', planted_ch: 0, last_ch: 0, resolved_ch: null, tier: it.tier, plan_plant_ch: it.plant_ch, plan_resolve_ch: it.resolve_ch, note: it.note, source: 'ai' }; db.foreshadows.push(f); return f.id })
    p.result = { ids }
    p._undo = () => { db.foreshadows = db.foreshadows.filter((f) => !ids.includes(f.id)) }
  } else if (p.kind === 'package') {
    const pkg = pkgOf(book.id)
    const before = { ...pkg }
    db.packages.set(book.id, { ...pkg, ...pl.after, ...(edited ?? {}) })
    p._undo = () => db.packages.set(book.id, before)
  } else if (p.kind === 'covers' || p.kind === 'write_chapter') {
    const isCover = p.kind === 'covers'
    const j = createJob(isCover ? 'covers_generate' : 'chapter_write_next', book.id, isCover ? 3200 : 5200, isCover ? ['组装封面提示词…', '调用生图模型…', '叠加书名排版…'] : ['取下一章细纲…', '写作正文…', '证据式审稿…', '人味 lint…'], () => {
      if (isCover) {
        const urls = [coverDataUrl(book.title, nid() % 6), coverDataUrl(book.title, nid() % 6)]
        const pkg = pkgOf(book.id)
        db.packages.set(book.id, { ...pkg, covers: [...pkg.covers, ...urls], chosen_cover: pkg.chosen_cover ?? urls[0] })
        Object.assign(p, { status: 'applied', revertible: true, result: { covers: urls } })
        p._undo = () => { const k = pkgOf(book.id); db.packages.set(book.id, { ...k, covers: k.covers.filter((u: string) => !urls.includes(u)) }) }
        return { covers: urls }
      }
      const ch = writeOne(book.id, pl.variants ?? 1)
      Object.assign(p, { status: 'applied', revertible: true, result: { chapter_id: ch.id } })
      p._undo = () => { db.chapters = db.chapters.filter((c) => c.id !== ch.id); recalc(book.id) }
      return { chapter_id: ch.id }
    })
    Object.assign(p, { status: 'running', job_id: j.id, updated_at: now() })
    return j
  }
  Object.assign(p, { status: 'applied', revertible: true, updated_at: now() })
  return null
}
function scriptFor(s: MSession, text: string) {
  const book = bookOf(String(s.book_id))
  const t0 = Date.now()
  let at = t0
  const step = (ms: number, fn: () => void) => { at += ms; s.queue.push({ at, fn }) }
  const pids: number[] = []
  const call = (calls: [string, Record<string, any>][], say = '') => {
    const ids = calls.map(([name], i) => `mock_${nid()}_${i}_${name}`)
    step(650, () => addMsg(s, { role: 'assistant', content: say, tool_calls: calls.map(([name, args], i) => ({ id: ids[i], name, arguments: args, ...toolLabel(name) })) }))
    return ids
  }
  const result = (id: string, name: string, summary: string, data: Record<string, any> = {}, mk?: () => MProposal[]) => step(800, () => {
    const ps = mk?.() ?? []
    ps.forEach((p) => pids.push(p.id))
    const m = addMsg(s, { role: 'tool', tool_call_id: id, name, ...toolLabel(name), summary, content: JSON.stringify({ ok: true, summary, ...data, proposal_ids: ps.map((p) => p.id) }), proposal_ids: ps.map((p) => p.id) })
    ps.forEach((p) => { p.message_id = m.id })
  })
  const finish = (head: string) => step(600, () => {
    const lines = s.messages.filter((m) => m.role === 'tool' && m.created_at >= new Date(t0).toISOString() && m.name !== 'get_book_info').map((m) => `- ${m.summary}`)
    const auto = autoApply.get(s.book_id)
    addMsg(s, { role: 'assistant', content: `${head}\n${lines.join('\n')}${pids.length ? `\n提案 ${pids.map((x) => `#${x}`).join('、')} ${auto ? '已自动采纳，随时可以撤回。' : '在上面，点「采纳」才会写入；不满意可以拒绝，或改完再采纳。'}` : ''}\n（演示模式：以上由规则脚本生成）` })
  })
  const terms = termsOf(text)
  if (/写下一章|写一章|续写/.test(text)) {
    const [id] = call([['write_next_chapter', { variants: 1 }]], '好，按章细纲写下一章。')
    const n = db.chapters.filter((c) => c.book_id === book.id).length + 1
    result(id, 'write_next_chapter', '提案「写下一章」— 等作者采纳', {}, () => [mkProposal(s, 'write_chapter', `写第 ${n} 章`, '按章细纲写作 → 审稿 → 人味检查 → 定点修改，写完是草稿', { variants: 1, number: n })])
    finish('下一章的写作任务准备好了：')
  } else if (text.includes('封面')) {
    const [a, b] = call([['get_package', {}], ['revise_cover_prompt', { instruction: text }]], '先看看现在的包装，再改封面提示词。')
    result(a, 'get_package', '读取包装（书名候选、简介、标签、封面）')
    const prompt = `${pkgOf(book.id).cover_prompt || '冰封城市里唯一亮灯的超市，主角立于门口'}，${text.slice(0, 16)}`
    result(b, 'revise_cover_prompt', '提案「改封面提示词」— 等作者采纳', {}, () => [mkProposal(s, 'package', '改封面提示词', text.slice(0, 40), { before: { cover_prompt: pkgOf(book.id).cover_prompt }, after: { cover_prompt: prompt } })])
    const [c] = call([['generate_covers', { prompt, n: 2 }]])
    result(c, 'generate_covers', '提案「生成 2 张封面」— 等作者采纳', {}, () => [mkProposal(s, 'covers', '生成 2 张封面', prompt.slice(0, 80), { prompt, n: 2 })])
    finish('封面这边：')
  } else if (text.includes('伏笔')) {
    const [a, b] = call([['list_foreshadows', {}], ['plan_foreshadows', { instruction: text, count: 3, attach: true }]])
    result(a, 'list_foreshadows', `伏笔 ${db.foreshadows.filter((f) => f.book_id === book.id).length} 条`)
    const items = [{ desc: '摩托帮账本上被撕掉的一页', tier: 'long', plant_ch: 7, resolve_ch: 60, note: '开篇只写缺页，中途有人高价收购' }, { desc: '苏晚袖口的旧针眼', tier: 'mid', plant_ch: 8, resolve_ch: 25, note: '先当细节写' }, { desc: '超市地下室那扇锁死的门', tier: 'short', plant_ch: 9, resolve_ch: 15, note: '门后有人敲' }]
    result(b, 'plan_foreshadows', '提案「规划 3 条伏笔」— 等作者采纳', {}, () => [mkProposal(s, 'foreshadow_add', '规划 3 条伏笔', items.map((x) => x.desc).join('；'), { items, attach: true })])
    finish('伏笔规划好了：')
  } else if (/第\s*\d+\s*章/.test(text) && /改写|节奏|对话|删/.test(text)) {
    const num = Number(text.match(/第\s*(\d+)\s*章/)![1])
    const c = db.chapters.find((x) => x.book_id === book.id && x.number === num)
    const [a, b] = call([['get_chapter', { number: num, part: 'summary' }], ['rewrite_chapter', { number: num, instruction: text }]])
    result(a, 'get_chapter', c ? `读取第 ${num} 章《${c.title}》（摘要）` : `没有找到第 ${num} 章`)
    if (c) {
      const after = rewriteText(c.content ?? '', text)
      result(b, 'rewrite_chapter', `提案「改写第 ${num} 章」— 等作者采纳`, {}, () => [mkProposal(s, 'chapter_rewrite', `改写第 ${num} 章《${c.title}》`, `${c.words} → ${countWords(after)} 字`, { chapter_id: c.id, number: num, title: c.title, instruction: text, before: c.content, after, words_before: c.words, words_after: countWords(after), ai_score_after: mkLint(after).ai_score })])
    } else result(b, 'rewrite_chapter', `改写章节失败：没有找到第 ${num} 章`)
    finish(`第 ${num} 章：`)
  } else if (/别|不要|改|换|同步|去掉|弱化|名/.test(text)) {
    const [a, b] = call([['get_book_info', {}], ['search_bible', { query: terms.join(' ') }]], '我先看看作品信息和设定库里相关的卡。')
    result(a, 'get_book_info', `《${book.title}》：${book.stats.chapters} 章，${db.cards.filter((c) => c.book_id === book.id).length} 张设定卡`)
    result(b, 'search_bible', `设定库里含「${terms.join(' ')}」的共 ${impactOf(book.id, terms).cards.length} 张卡`)
    const [c] = call([['revise_book_info', { instruction: text }]])
    const rev = reviseResult(book, text)
    result(c, 'revise_book_info', '提案「改一句话简介」— 等作者采纳', {}, () => [mkProposal(s, 'book_info', '改一句话简介', rev.change, rev)])
    const [d] = call([['sync_downstream', { instruction: text, terms, replacements: rev.replacements, targets: ['bible', 'outline'] }]])
    result(d, 'sync_downstream', '同步：设定库提案、大纲提案', {}, () => {
      const out: MProposal[] = []
      const bp = bibleProposalOf(book.id, 'optimize', text, terms, rev.replacements)
      if (bp.items.length) out.push(mkProposal(s, 'bible', `同步设定库：${terms.join('、')}`, bp.change, bp))
      const imp = impactOf(book.id, terms)
      const items = imp.outline.map((x) => { const n = db.outline.find((o) => o.id === x.id)!; return { node_id: n.id, level: n.level, old: { title: n.title, summary: n.summary }, new: { title: strip2(n.title, terms, rev.replacements), summary: strip2(n.summary, terms, rev.replacements) }, reason: '拿掉旧说法' } })
      if (items.length) out.push(mkProposal(s, 'outline_nodes', `同步大纲 ${items.length} 个节点`, '拿掉旧说法', { instruction: text, items }))
      return out
    })
    finish('按你的要求，我做了这些：')
  } else {
    const [a] = call([['get_book_info', {}]])
    result(a, 'get_book_info', `《${book.title}》：${book.stats.chapters} 章`)
    step(600, () => addMsg(s, { content: `《${book.title}》现在 ${book.stats.chapters} 章、${db.cards.filter((c) => c.book_id === book.id).length} 张设定卡。告诉我要改哪里，比如「别强调拳法，把碎星神通改个名，同步设定和大纲」，我会先出提案给你看。\n（演示模式：以上由规则脚本生成）` }))
  }
  const job = createJob('agent_run', book.id, at - t0 + 50, ['思考中…', '调用工具…', '整理提案…'], () => ({ proposals: pids }))
  s.job = db.jobs.find((j) => j.id === job.id) ?? null
}
const sessOf = (id: string) => { const s = must(agentSessions.find((x) => x.id === +id), '会话'); pumpAgent(s); return s }
const agentDetail = (s: MSession): AgentSessionDetail => {
  if (s.job) tick(s.job)
  const ps = agentProposals.filter((p) => p.session_id === s.id)
  ps.forEach((p) => { if (p.job_id) { const j = db.jobs.find((x) => x.id === p.job_id); if (j) tick(j) } })
  return {
    session: agentSessOut(s), messages: s.messages, proposals: ps.map(({ _undo, ...p }) => { void _undo; return p }),
    proposal_jobs: Object.fromEntries(ps.filter((p) => p.job_id).map((p) => { const j = db.jobs.find((x) => x.id === p.job_id)!; return [String(p.id), { id: j.id, status: j.status, progress: j.progress, message: j.message, error: j.error }] })),
    job: s.queue.length && s.job ? pub(s.job) : null,
  }
}
on('GET', '/agent/tools', () => ({ tools: TOOL_INFO, max_steps: 12, examples: ['别强调拳法，把『碎星神通』改个名，同步设定和大纲', '第 2 章节奏快一点，对话多一点', '规划 3 条伏笔，前十章至少一条长线', '按现在的设定改封面提示词，生成 2 张封面', '写下一章'] }))
on('GET', '/books/:id/agent/settings', (m) => ({ auto_apply: !!autoApply.get(+m[1]) }))
on('PUT', '/books/:id/agent/settings', (m, b) => { autoApply.set(+m[1], !!b.auto_apply); const book = bookOf(m[1]); book.agent_auto_apply = !!b.auto_apply; return { auto_apply: !!b.auto_apply, book } })
on('GET', '/books/:id/agent/sessions', (m) => agentSessions.filter((s) => s.book_id === +m[1]).map((s) => { pumpAgent(s); return agentSessOut(s) }).sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
on('POST', '/books/:id/agent/sessions', (m, b) => { bookOf(m[1]); const s: MSession = { id: nid(), book_id: +m[1], title: b.title || '新对话', created_at: now(), updated_at: now(), messages: [], queue: [], job: null }; agentSessions.push(s); return agentSessOut(s) })
on('GET', '/agent/sessions/:id', (m) => agentDetail(sessOf(m[1])))
on('PATCH', '/agent/sessions/:id', (m, b) => { const s = sessOf(m[1]); s.title = b.title; return agentSessOut(s) })
on('POST', '/agent/sessions/:id/clear', (m) => { const s = sessOf(m[1]); if (s.queue.length) throw new HttpErr(409, 'Agent 正在工作，先停止再清空'); s.messages = []; s.title = '新对话'; for (let i = agentProposals.length - 1; i >= 0; i--) if (agentProposals[i].session_id === s.id) agentProposals.splice(i, 1); return agentSessOut(s) })
on('DELETE', '/agent/sessions/:id', (m) => { const s = sessOf(m[1]); agentSessions.splice(agentSessions.indexOf(s), 1); return { ok: true } })
on('POST', '/agent/sessions/:id/messages', (m, b) => {
  const s = sessOf(m[1])
  if (s.queue.length) throw new HttpErr(409, 'Agent 还在处理上一条，稍等或先停止')
  const msg = addMsg(s, { role: 'user', content: String(b.content ?? '') })
  if (s.title === '新对话') s.title = msg.content.slice(0, 24)
  s.stop = false
  scriptFor(s, msg.content)
  return { message: msg, job: pub(s.job!) }
})
on('POST', '/agent/sessions/:id/stop', (m) => { const s = sessOf(m[1]); s.stop = true; return agentSessOut(s) })
const propOf = (id: string) => must(agentProposals.find((p) => p.id === +id), '提案')
const propOut = ({ _undo, ...p }: MProposal) => { void _undo; return p }
on('GET', '/agent/proposals/:id', (m) => propOut(propOf(m[1])))
on('POST', '/agent/proposals/:id/apply', (m, b) => {
  const p = propOf(m[1])
  if (p.status !== 'pending' && p.status !== 'failed') throw new HttpErr(409, '这个提案已经处理过了')
  if (p.kind === 'bible' && p.needs_review && !b.ops) throw new HttpErr(409, '这个设定提案和已有设定有冲突，请先逐条审阅')
  const job = applyMock(p, b.edited, b.ops)
  return { proposal: propOut(p), job }
})
on('POST', '/agent/proposals/:id/reject', (m) => { const p = propOf(m[1]); if (p.status !== 'pending') throw new HttpErr(409, '这个提案已经处理过了'); p.status = 'rejected'; return propOut(p) })
on('POST', '/agent/proposals/:id/revert', (m) => { const p = propOf(m[1]); if (p.status !== 'applied' || !p._undo) throw new HttpErr(409, '只有已采纳的提案可以撤回'); p._undo(); Object.assign(p, { status: 'reverted', revertible: false }); return propOut(p) })

// ---------------- 安装 ----------------
export function installMock() {
  const real = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const url = new URL(raw, location.origin)
    if (!url.pathname.startsWith('/api/')) return real(input, init)
    const method = (init?.method || 'GET').toUpperCase()
    const path = url.pathname.slice(4)
    const body = init?.body ? JSON.parse(String(init.body)) : {}
    await new Promise((r) => setTimeout(r, 120 + Math.random() * 160))
    for (const [mth, re, h] of routes) {
      const m = path.match(re)
      if (m && mth === method) {
        try {
          const out = h(m, body, url)
          if (out instanceof Response) return out
          return new Response(out === null || out === undefined ? null : JSON.stringify(out), { status: out === null || out === undefined ? 204 : 200, headers: { 'Content-Type': 'application/json' } })
        } catch (e) {
          const err = e instanceof HttpErr ? e : new HttpErr(500, (e as any)?.message ?? '服务器错误')
          return new Response(JSON.stringify({ detail: err.detail }), { status: err.status, headers: { 'Content-Type': 'application/json' } })
        }
      }
    }
    return new Response(JSON.stringify({ detail: `mock 未实现：${method} ${path}` }), { status: 404 })
  }
  // eslint-disable-next-line no-console
  console.info('%c[NovelOS] 已启用前端 mock（VITE_USE_MOCK=1）', 'color:#5b6cf0')
}
