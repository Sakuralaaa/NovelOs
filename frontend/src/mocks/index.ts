/**
 * 前端自测用 fetch mock —— 仅当 VITE_USE_MOCK=1 时由 main.tsx 动态加载。
 * 覆盖 API_CONTRACT.md（含 v0.1 增补）的全部端点，数据为确定性的虚构示例。
 */
import type {
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
  routing: { planner: null, writer: null, reviewer: null, embedding: null, image: null } as Routing,
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
    { type: 'power', name: '超市系统', summary: '每日零点补货，交易可获得“信用点”升级货架。', data: { 补货: '每天 0:00', 升级: '信用点', 限制: '不能主动攻击' }, known_by: ['林野'] },
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
const maskCh = (c: (typeof db.channels)[number]): Channel => ({ id: c.id, name: c.name, base_url: c.base_url, models: c.models, enabled: c.enabled, api_key_masked: c.api_key ? `${c.api_key.slice(0, 3)}••••${c.api_key.slice(-4)}` : '' })
on('GET', '/settings/channels', () => db.channels.map(maskCh))
on('POST', '/settings/channels', (_m, b) => { const c = { id: nid(), name: b.name, base_url: b.base_url, api_key: b.api_key ?? '', models: b.models ?? [], enabled: b.enabled ?? true }; db.channels.push(c); return maskCh(c) })
on('PUT', '/settings/channels/:id', (m, b) => { const c = must(db.channels.find((x) => x.id === +m[1])); Object.assign(c, { ...b, api_key: b.api_key ? b.api_key : c.api_key }); return maskCh(c) })
on('DELETE', '/settings/channels/:id', (m) => { db.channels = db.channels.filter((x) => x.id !== +m[1]); return null })
on('POST', '/settings/channels/:id/test', (m) => { const c = must(db.channels.find((x) => x.id === +m[1])); return c.base_url.startsWith('http') ? { ok: true, latency_ms: 230 + (c.id % 7) * 41 } : { ok: false, latency_ms: 0, error: 'Base URL 格式不正确' } })
on('GET', '/settings/writing', () => db.writing)
on('PUT', '/settings/writing', (_m, b) => (db.writing = { ...db.writing, ...b }))
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
    { title: `${genre}：我能看见所有人的隐藏属性`, logline: '主角意外获得洞察能力，从被人看不起的小角色一步步翻盘。', hook: '开局就看见上司头顶写着“明天被抓”。', sp: ['信息差爽点', '打脸', '升级明确'] },
    { title: `开局签到一座城：${genre}`, logline: '每日签到获得城市模块，在乱世里亲手建起一座城。', hook: '第一天签到，得到的是一座废弃火车站。', sp: ['基建经营', '收服人才', '节奏快'] },
    { title: `${genre}之我的影子会说话`, logline: '主角的影子拥有独立意识，替他做出每一个“正确”的选择——直到它开始撒谎。', hook: '影子说：“别开门，门外那个是你自己。”', sp: ['悬疑反转', '高概念', '人设新'] },
  ]
  const ids: number[] = []
  for (let i = 0; i < (b.count || 3); i++) {
    const p = pool[i % pool.length]
    const id = nid(); ids.push(id)
    db.ideas.unshift({ id, book_id: null, title: p.title, logline: p.logline, selling_points: p.sp, hook: p.hook, genre, scores: { heat: 70 + i * 7, novelty: 85 - i * 9, fit: 78, overall: 80 - i * 4 }, chosen: false })
  }
  return { idea_ids: ids }
}))
on('GET', '/ideas', () => db.ideas)
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
    add('power', '金手指', '主角的核心外挂。', { 代价: '每次使用会失去一段记忆' })
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
  db.packages.set(b.id, { ...p, covers: Array.from({ length: body.n || 4 }, (_, i) => coverDataUrl(b.title, i + shift + 1)) })
  return {}
}) })
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
