/**
 * 前端自测用 fetch mock —— 仅当 VITE_USE_MOCK=1 时由 main.tsx 动态加载。
 * 覆盖 API_CONTRACT.md（含 v0.1 增补、v0.4 按要求让 AI 改、v0.5 每本书的专属 Agent）的全部端点，数据为确定性的虚构示例。
 */
import type {
  AgentMessage, AgentProposal, AgentSession, AgentSessionDetail, AgentToolInfo, BibleItem, BibleOp, BibleProposal, BookInfo,
  ForeshadowPlanItem, Impact, OutlineSyncItem, Trope, TropeHit,
  Book, Card, Channel, Chapter, ChapterVariant, Foreshadow, Idea, Job, Lint, OutlineNode, Package,
  RadarConfig, RadarSnapshot, Review, Routing, Style, Teardown, TrendReportBody, FanficTemplate,
} from '@/lib/types'
import { analyzeText } from '@/lib/textAnalysis'
import { countWords } from '@/lib/utils'
import { WANBEN_RESUMABLE, registerWanbenMocks } from './wanben'
import { registerAutoMocks } from './autopilot'
import { FF_TEMPLATES, FF_TEMPLATE_CATEGORIES } from './fanficTemplates'
import { FEMALE_CATS, MALE_CATS, STYLE_SAMPLE, THICKEN_MAP, buildChapterText, coverDataUrl, makeRankItems } from './data'

const now = () => new Date().toISOString()
const ago = (min: number) => new Date(Date.now() - min * 60_000).toISOString()
let seq = 1000
const nid = () => ++seq

// ---------------- DB ----------------
const db = {
  channels: [] as (Omit<Channel, 'api_key_masked'> & { api_key: string })[],
  routing: { planner: null, writer: null, reviewer: null, search: null, embedding: null, image: null, agent: null, image_mode: 'images' } as Routing,
  radarConfig: { enabled: true, daily_hour: 8, auto_report: true } as RadarConfig,
  reportConfig: { radar_report_top_n: 30, radar_report_auto_scopes: ['overall', 'board:male:read'] },
  writing: { auto_adopt_best: false, auto_commit: false, default_variants: 1, llm_timeout: 360, llm_retries: 2, sticky_session: true },
  zhuque: { zhuque_configured: true, zhuque_key_tail: '9fQ2', zhuque_base_url: 'https://ai-gateway.edgeone.link', zhuque_auto_check: false, zhuque_usage: { calls: 12, tokens: 38210 } },
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
    intensifiers: [{ word: '死死', count: (content.match(/死死/g) || []).length, allow: 2, over: (content.match(/死死/g) || []).length > 2 }].filter((x) => x.count),
    cliche_similes: /灌了铅/.test(content) ? [{ word: '空气像灌了铅', count: 1 }] : [],
    measure_errors: [],
    crowd_shots: 0,
    dialogue_tics: [],
    catchphrases: [],
    fix_targets: [],
  }
}

function mkReview(seed: number, content: string): Review {
  const base = 68 + (seed % 5) * 4
  const scores = { hook: base + 6, pacing: base - 4, payoff: base + 2, character: base - 8, coherence: base + 10, continuity: base + 4, semantics: base + 8, overall: base }
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
    premise: '冰封末世，超市系统每日零点补货；主角只换不卖，靠规矩在东区立足。', approval_mode: 'review',
  }
  db.books.push(book)
  db.books.push({
    id: 2, title: '重生八零：糙汉老公宠上天', genre: '年代重生', gender: 'female', tagline: '上辈子错过的人，这辈子我追。',
    status: 'outline', target_words: 600_000, chapter_words: 2000, cover_url: null, created_at: ago(60 * 30), updated_at: ago(60 * 2), approval_mode: 'auto',
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
  cards.forEach((c) => db.cards.push({ ...c, id: nid(), book_id: bookId, updated_at: ago(30), status: 'active', ref_enabled: true, soul: null }))
  // v0.9.3：主角五维填了三项（完整度里「主角卡」得 5 分）；老猎枪默认不进 @ 引用；一张弃用条目
  const lin = db.cards.find((c) => c.name === '林野')!
  lin.data.role = 'protagonist'
  lin.soul = { desire: '守住超市，让身边几个人活过这个冬天', fear: '再一次眼睁睁看着别人死在门外', wound: '', belief: '只换不卖，规矩比人情硬', voice: '' }
  db.cards.find((c) => c.name === '苏晚')!.soul = { desire: '', fear: '', wound: '', belief: '', voice: '' }
  db.cards.find((c) => c.name === '老猎枪')!.ref_enabled = false
  db.cards.push({ id: nid(), book_id: bookId, type: 'faction', name: '西区教会', summary: '早期设定：冰封是神罚。后来改成东区三方势力，这条弃用。', data: { 首领: '白袍主教' }, known_by: [], updated_at: ago(300), status: 'deprecated', ref_enabled: true, soul: null })

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
    sample_text: STYLE_SAMPLE, baseline: STYLE_SAMPLE.slice(0, 800), voice_notes: '冷峻克制，多用动作代替心理描写；对白短，前后要有动作或环境。', pov: 'third', tone: '冷峻写实',
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
function createJob(kind: string, bookId: number | null, dur: number, steps: string[], fin: () => Record<string, any> | null, ref = ''): Job {
  const j = { id: nid(), kind, status: 'queued' as const, progress: 0, message: '排队中…', result: null, error: null, book_id: bookId, ref, created_at: now(), updated_at: now(), _start: Date.now(), _dur: dur, _steps: steps, _fin: fin }
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

on('GET', '/health', () => ({ status: 'ok', version: '0.9.3-mock' }))
on('GET', '/jobs', (_m, _b, u) => {
  db.jobs.forEach(tick)
  const bid = u.searchParams.get('book_id'); const kind = u.searchParams.get('kind'); const ref = u.searchParams.get('ref')
  return db.jobs.filter((j) => (!bid || j.book_id === +bid) && (!kind || j.kind === kind) && (!ref || (j as any).ref === ref)).slice(0, 50).map(pub)
})
on('GET', '/jobs/:id', (m) => { const j = must(db.jobs.find((x) => x.id === +m[1]), '任务'); tick(j); return pub(j) })

on('GET', '/auth/status', () => ({ enabled: true, authenticated: mockAuthed(), username: 'novelos', managed_by_env: false, min_password_len: 8 }))
on('POST', '/auth/login', (_m: any, body: any) => { if (body?.password !== 'novelos-demo') throw new HttpErr(401, '密码不正确'); sessionStorage.setItem('mock-auth', '1'); return { ok: true } })
on('POST', '/auth/logout', () => { sessionStorage.setItem('mock-auth', '0'); return { ok: true } })
on('POST', '/auth/password', () => ({ ok: true }))
const mockKeys: any[] = []
on('GET', '/mcp-info', () => ({ url: `${location.origin}/api/mcp`, tools: [{ name: 'guide', description: 'NovelOS 使用说明与推荐流程' }, { name: 'list_books', description: '列出所有作品' }, { name: 'chapter_brief', description: '写某章前取上下文' }, { name: 'save_chapter', description: '把你写好的正文存为第 N 章' }, { name: 'call_model', description: '用作者配置的模型生成文本' }, { name: 'api', description: '调用任意 NovelOS 接口' }] }))
on('GET', '/auth/keys', () => ({ keys: mockKeys, env_key_enabled: false }))
on('POST', '/auth/keys', (_m: any, b: any) => { const id = String(Math.floor(1e7 + Math.random() * 9e7)); const token = `nvk_${id}_demo${Math.random().toString(36).slice(2)}`; const k = { id, name: b?.name || '未命名', preview: `nvk_${id}_…${token.slice(-4)}`, created_at: Math.floor(Date.now() / 1000), last_used_at: null }; mockKeys.push(k); return { ...k, token } })
on('DELETE', '/auth/keys/:id', (m: any) => { const i = mockKeys.findIndex((k) => k.id === m[1]); if (i >= 0) mockKeys.splice(i, 1); return { ok: true } })
on('GET', '/settings/status', () => ({ mock_mode: db.channels.filter((c) => c.enabled).length === 0 }))
const maskCh = (c: (typeof db.channels)[number]): Channel => ({ id: c.id, name: c.name, base_url: c.base_url, models: c.models, enabled: c.enabled, api_format: c.api_format ?? 'openai', api_key_masked: c.api_key ? `${c.api_key.slice(0, 3)}••••${c.api_key.slice(-4)}` : '' })
on('GET', '/settings/channels', () => db.channels.map(maskCh))
on('POST', '/settings/channels', (_m, b) => { const c = { id: nid(), name: b.name, base_url: b.base_url, api_key: b.api_key ?? '', models: b.models ?? [], enabled: b.enabled ?? true, api_format: b.api_format ?? 'openai' }; db.channels.push(c); return maskCh(c) })
on('PUT', '/settings/channels/:id', (m, b) => { const c = must(db.channels.find((x) => x.id === +m[1])); Object.assign(c, { ...b, api_key: b.api_key ? b.api_key : c.api_key }); return maskCh(c) })
on('DELETE', '/settings/channels/:id', (m) => { db.channels = db.channels.filter((x) => x.id !== +m[1]); return null })
on('POST', '/settings/channels/:id/test', (m) => { const c = must(db.channels.find((x) => x.id === +m[1])); return c.base_url.startsWith('http') ? { ok: true, latency_ms: 230 + (c.id % 7) * 41 } : { ok: false, latency_ms: 0, error: 'Base URL 格式不正确' } })
on('GET', '/settings/writing', () => db.writing)
on('PUT', '/settings/writing', (_m, b) => (db.writing = { ...db.writing, ...b }))
// v0.9.1 朱雀设置（独立接口；空串 = 清除密钥 / 恢复默认网关）
on('GET', '/settings/zhuque', () => db.zhuque)
on('PUT', '/settings/zhuque', (_m, b) => {
  if (b.zhuque_api_key !== undefined) { const k = String(b.zhuque_api_key || ''); db.zhuque.zhuque_configured = !!k; db.zhuque.zhuque_key_tail = k ? k.slice(-4) : '' }
  if (b.zhuque_base_url !== undefined) {
    const u = String(b.zhuque_base_url || '').trim()
    if (u && !/^https?:\/\//.test(u)) throw new HttpErr(400, '网关地址需要以 http:// 或 https:// 开头')
    db.zhuque.zhuque_base_url = u || 'https://ai-gateway.edgeone.link'
  }
  if (b.zhuque_auto_check !== undefined) db.zhuque.zhuque_auto_check = !!b.zhuque_auto_check
  return db.zhuque
})
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
  const g = u.searchParams.get('gender'), c = u.searchParams.get('category'), bd = u.searchParams.get('board')
  // v0.9.2 mock：新书榜 = 每 3 本取 1 本、重新排名
  let items = db.items.filter((i) => (!g || i.gender === g))
  if (bd === 'new') items = items.filter((_, k) => k % 3 === 1).map((i, k) => ({ ...i, board: 'new' as const, rank: k + 1 }))
  else items = items.map((i) => ({ ...i, board: 'read' as const }))
  return { snapshot: db.snapshots[0] ?? null, items: items.filter((i) => !c || i.category === c), boards: ['new', 'read'] }
})
on('GET', '/radar/trends', () => [...MALE_CATS, ...FEMALE_CATS].map((cat, i) => {
  const its = db.items.filter((x) => x.category === cat)
  return { category: cat, heat: Math.round(its.reduce((n, x) => n + x.read_count, 0) / 1e5) + ((i * 13) % 30), books: its.length, rising: (i * 5) % 4, sample_titles: its.slice(0, 3).map((x) => x.title) }
}).sort((a, b) => b.heat - a.heat))
// v0.7 榜单仿写
const teardowns = new Map<number, Teardown>()
const rankOf = (id: string) => must(db.items.find((x) => x.id === +id), '榜单条目')
function mkTeardown(it: (typeof db.items)[number]): Teardown {
  const male = it.gender === 'male'
  return {
    id: nid(), rank_item_id: it.id!, book_id_ext: it.book_id_ext, title: it.title, created_at: now(), cached: false, deep: null,
    teardown: {
      payoff_formula: male ? '底层受辱 → 金手指觉醒 → 当众打脸 → 资源翻倍 → 更大的舞台' : '被辜负 → 清醒反击 → 身份反转 → 被偏爱 → 双向奔赴',
      golden_finger: { type: male ? '系统 / 面板' : '重生记忆', delivery: male ? '第 1 章结尾露出，第 2 章第一次兑现，每 3 章一次小升级' : '开篇即重生，前 3 章用信息差连续反杀' },
      protagonist_template: male ? '隐忍型小人物，嘴硬心软，有明确的守护对象' : '清醒独立的女主，前世吃过亏，这一世不再委屈自己',
      opening_hook: male ? '开局即绝境：被当众羞辱 + 倒计时危机' : '婚礼当天重生回十年前',
      target_readers: male ? '18–35 岁男性，喜欢快节奏升级与打脸' : '20–35 岁女性，喜欢情绪价值与成长逆袭',
      transferable: ['前 300 字给出冲突', '金手指第 1 章露出、第 2 章兑现', '每章结尾留一个具体的悬念'],
      must_replace: ['书名里的核心意象', '金手指的具体外形与名字', '主角身份与职业', '世界观设定'],
      warnings: it.rank % 4 === 1 ? ['拆解结果与简介有 1 处连续 8 字相同，已提醒'] : [],
    },
  }
}
on('GET', '/radar/items/:id/teardown', (m) => must(teardowns.get(+m[1]), '这本书还没有拆解'))
// v0.7.1：拆解 / 深度拆解 / 换皮选题都是任务接口，立即返回 Job（ref = rank_item:{id}）
const rankRef = (id: number) => `rank_item:${id}`
const activeRankJob = (kind: string, id: number) => db.jobs.find((j) => j.kind === kind && (j as any).ref === rankRef(id) && (tick(j), j.status === 'queued' || j.status === 'running'))
on('GET', '/radar/items/:id/jobs', (m) => { db.jobs.forEach(tick); return db.jobs.filter((j) => (j as any).ref === rankRef(+m[1])).slice(0, 20).map(pub) })
on('POST', '/radar/items/:id/teardown', (m, _b, u) => {
  const it = rankOf(m[1]); const running = activeRankJob('radar_teardown', it.id!)
  if (running) return pub(running)
  const refresh = u.searchParams.get('refresh') === 'true'
  return createJob('radar_teardown', null, refresh || !teardowns.get(it.id!) ? 3200 : 400, ['拆解中：爽点公式、金手指、人设', '检查和简介的重合并保存'], () => {
    const old = teardowns.get(it.id!)
    if (old && !refresh) return { ...old, cached: true }
    const t = { ...mkTeardown(it), deep: old?.deep ?? null }; teardowns.set(it.id!, t); return t
  }, rankRef(it.id!))
})
on('POST', '/radar/items/:id/deep', (m, b) => {
  const it = rankOf(m[1])
  const text = String(b.text ?? ''); const n = text.replace(/\s/g, '').length
  if (!n) throw new HttpErr(400, '请粘贴试读原文')
  if (n > 20000) throw new HttpErr(400, `原文超过 20000 字（现在 ${n} 字），请删减后再试`)
  return createJob('radar_deep', null, 4200, ['统计按章字数与对白比例', '逐章拆解中', '检查和原文的重合并保存'], () => mockDeep(it, text, n), rankRef(it.id!))
})
function mockDeep(it: (typeof db.items)[number], text: string, n: number) {
  const t = teardowns.get(it.id!) ?? mkTeardown(it)
  const parts = text.split(/\n(?=第[一二三四五六七八九十百\d]+章)/).filter((x) => x.trim())
  const chapters = parts.map((p, i) => {
    const w = p.replace(/\s/g, '').length; const dl = (p.match(/“[^”]*”/g) ?? []).join('').length
    return { index: i + 1, title: (p.split('\n')[0] || '').slice(0, 20), words: w, dialogue_ratio: w ? +(dl / w).toFixed(2) : 0,
      conflict: ['被当众退婚', '债主上门', '比试被设局'][i % 3], payoff: ['系统觉醒，当场反杀', '一招逼退对手', '拿回本该属于自己的东西'][i % 3], hook: ['神秘人留下一句话', '更大的敌人现身', '金手指出现新提示'][i % 3] }
  })
  const deep = { chapters, total_words: n, dialogue_ratio: 0.31, first_conflict: { keyword: '退婚', at_char: 186, chapter: 1 }, first_cheat: { keyword: '系统', at_char: 1420, chapter: 1 },
    rhythm: '每章 1 个小冲突 + 1 个小爽点，第 3 章出现第一个大反转；对白占三成，推进快。', learnable: ['冲突在前 200 字内出现', '金手指露出后立刻给一次小兑现', '章末钩子都落在具体的人或物上'], overlap: 0, warnings: [] }
  const out = { ...t, deep, cached: false }; teardowns.set(it.id!, out); return out
}
on('POST', '/radar/items/:id/reskin', (m) => {
  const it = rankOf(m[1]); const running = activeRankJob('radar_reskin', it.id!)
  if (running) return pub(running)
  return createJob('radar_reskin', null, 6000, ['读取拆解', '生成选题 1/3', '生成选题 2/3', '生成选题 3/3', '评分与相似点自检'], () => mockReskin(it), rankRef(it.id!))
})
function mockReskin(it: (typeof db.items)[number]) {
  const t = teardowns.get(it.id!) ?? mkTeardown(it); teardowns.set(it.id!, t)
  const seeds = [
    { title: '我在废土当判官', logline: '核冬天第十年，一个被流放的书记员发现自己判下的每一桩案子都会成真。', genre: '废土 · 规则' },
    { title: '潮汐守夜人', logline: '海上城邦每晚涨潮，灯塔学徒能看见潮水里沉着的旧日记忆。', genre: '海洋奇幻' },
    { title: '县城修钟匠', logline: '九十年代的小县城，修钟匠的徒弟能把一座钟拨回三分钟。', genre: '年代 · 异能' },
  ]
  const ideas: Idea[] = seeds.map((x, k) => ({
    id: nid(), book_id: null, title: x.title, logline: x.logline, genre: x.genre, hook: '开篇三百字内主角就被逼到绝境，然后能力第一次兑现。',
    selling_points: ['结构同款的快节奏爽点', '全新的世界观和金手指外形'], expectations: ['主角会不会被反噬'], arc: ['立足', '扩张', '对决'], endgame: '查清能力的来源',
    scores: { heat: 78 - k * 4, novelty: 80 - k * 6, fit: 74 - k * 3, overall: 77 - k * 4 }, chosen: false,
    source: {
      kind: 'reskin', rank_item_id: it.id, ref_title: it.title, ref_book_id_ext: it.book_id_ext, ref_category: it.category,
      kept: t.teardown!.transferable, changed: ['主角身份：' + x.title.slice(-3), '金手指外形', '世界观：' + x.genre],
      self_check: [
        { aspect: '主角身份', original: t.teardown!.protagonist_template.slice(0, 16), ours: x.logline.slice(0, 16), similar: false },
        { aspect: '金手指', original: t.teardown!.golden_finger.type, ours: x.logline.slice(-14), similar: k === 1 },
        { aspect: '开篇钩子', original: t.teardown!.opening_hook, ours: '被逼到绝境后能力第一次兑现', similar: false },
        { aspect: '世界观', original: it.category, ours: x.genre, similar: false },
      ],
      overlap: { count: k === 1 ? 1 : 0, title: 0, segments: k === 1 ? ['一个普通人意外获得'] : [] },
      warnings: k === 1 ? ['与原书简介连续 8 字相同：「一个普通人意外获得」', '模型自检仍偏像：金手指'] : [],
    },
  }))
  db.ideas.unshift(...ideas)
  return { rank_item_id: it.id, teardown_id: t.id, ref_title: it.title, idea_ids: ideas.map((x) => x.id), ideas, warnings: ideas.flatMap((x) => x.source!.warnings.map((w) => `《${x.title}》：${w}`)) }
}
// v0.9.1 书架详情 / AI 书名·封面词·简介
const extOf = (ext: string) => must(db.items.find((x) => x.book_id_ext === ext), '榜单书')
const CH_NAMES = ['意外', '交易', '第一桶金', '暗流', '试探', '反击', '收网', '新的规则', '夜访', '赌约', '破局', '旧债']
on('GET', '/radar/books/:id/detail', (m) => {
  const it = extOf(m[1])
  if ((it.id ?? 0) % 8 === 6) return { item: it, chapter_total: null, abstract: '', chapters_head: [], chapters_tail: [], fetched_at: now(), detail_error: '番茄书页暂时打不开（mock：模拟抓取失败）', cached: false }
  const total = it.chapter_count || 120
  const link = (n: number) => ({ title: `第${n}章 ${CH_NAMES[n % CH_NAMES.length]}`, item_id: `${it.book_id_ext}${n}`, url: `https://fanqienovel.com/reader/${it.book_id_ext}${String(n).padStart(4, '0')}` })
  return {
    item: it, chapter_total: total,
    abstract: `${it.abstract}\n\n【${it.category}】${it.tags.join(' / ')}。前期节奏快，三章内金手指到账，十章内第一次大打脸。`,
    chapters_head: Array.from({ length: Math.min(50, total) }, (_, i) => link(i + 1)),
    // 与后端一致：第 50 章之后的最后 10 章，不与前 50 章重复；总数 ≤50 时为空
    chapters_tail: total > 50 ? Array.from({ length: Math.min(10, total - 50) }, (_, i) => link(total - Math.min(10, total - 50) + i + 1)) : [],
    fetched_at: now(), detail_error: null, cached: false,
  }
})
on('POST', '/radar/books/:id/ai', (m, b) => {
  const it = extOf(m[1]); const kind = String(b.kind || 'title'); const n = Math.max(1, Math.min(10, +b.n || (kind === 'cover' ? 3 : 5)))
  const head = it.title.split(/[：:]/)[0]
  const j = createJob('radar_book_ai', null, 2600, ['读取书名与简介…', '生成候选…', '与原书做相似度过滤…'], () => {
    const pool = kind === 'title'
      ? ['全城停电后，我的便利店亮了', '开局负债百万，我靠签到翻身', '我的系统只在午夜营业', '被退学那天，我觉醒了推演', '我在废城收破烂，捡到了神级图纸', '外卖员？不，我是规则的修订者', '冷宫种田三年，皇帝求我出山', '离职当天，我继承了一座山门']
        .map((t, k) => ({ title: t, why: ['反差开局 + 明确金手指，三秒能看懂', '负面处境起手，期待感强', '时间限定制造神秘感', '“那天”句式点出转折', '低开高走的身份落差', '否定句式 + 身份反转', '女频经典落差：失宠到被求', '现实痛点 + 爽点承诺'][k] }))
      : kind === 'cover'
        ? ['竖版 3:4 网文封面，冷色调废土城市夜景，少年背影站在亮着灯的便利店门口，霓虹招牌，电影感光影，留出上方 1/3 写书名', '竖版封面，东方玄幻，白衣少年立于断崖，身后巨大金色符文阵，云海翻涌，史诗感，高对比', '竖版封面，都市高武，雨夜街头，主角半身特写，眼中有蓝色数据流，赛博质感，暗调', '竖版封面，古风女频，红墙宫院一角，少女回眸，手持药篮，柔光，水彩质感', '竖版封面，末世囤货，冰封城市俯瞰，一座发光的仓库，暖光与冷色对比，极简构图']
          .map((p, k) => ({ prompt: p, style: ['电影海报风', '国风厚涂', '赛博朋克', '水彩国风', '极简扁平'][k] }))
        : [`他被所有人看不起的那天，${head}的规则只对他一个人生效。\n第一天，他还清了债；第三天，那些人开始排队求他。`, `别人穿越带系统，她穿越只带了一本账。\n可这本账，记的是满朝文武的把柄。`, `末世第七天，城里只剩一家店还开着门。\n老板说：钱不收，只收秘密。`, `被逐出宗门时，他只带走了一把扫帚。\n十年后，宗门大阵碎了，所有人才想起——那把扫帚扫过的地方，从未落过灰。`]
          .map((t, k) => ({ blurb: t, hook: ['屈辱开局 + 独享规则', '反差道具 + 权谋张力', '设定悬念 + 交易钩子', '伏笔反转'][k] }))
    const dropped = (it.id ?? 0) % 3 === 0 ? 1 : 0
    return { kind, book_id_ext: it.book_id_ext, ref_title: it.title, candidates: pool.slice(0, n), dropped, warnings: dropped ? [`已丢弃「${head}之后」：和原书名/简介有 1 处连续 8 字相同`] : [] }
  })
  return { ...j, job_id: j.id }
})
// ---------------- v0.9.2 风向标（scope：overall / board:<g>:<read|new> / category:<g>:<read|new>:<name>）----------------
type MReport = { id: number; snapshot_id: number; scope: string; created_at: string; model: string; stale: boolean; snapshot: any; report: TrendReportBody }
const reports: MReport[] = []
const normScope = (s: string) => { const m = /^category:(male|female):(?!read:|new:)(.+)$/.exec(s); return m ? `category:${m[1]}:read:${m[2]}` : s }
function scopeBoards(scope: string): string[] {
  const m = /^(board|category):(male|female):(read|new)/.exec(scope)
  if (!m) return ['男频阅读榜', '男频新书榜', '女频阅读榜', '女频新书榜']
  return [`${m[2] === 'male' ? '男频' : '女频'}${m[3] === 'new' ? '新书榜' : '阅读榜'}`]
}
function mkReportBody(scope: string, legacy = false, salt = 0): TrendReportBody {
  const female = scope.includes(':female')
  const cat = /^category:[a-z]+:[a-z]+:(.+)$/.exec(scope)?.[1]
  const words = female ? ['清醒大女主', '年代致富', '假千金反杀', '团宠萌宝', '先婚后爱', '马甲文'] : ['中式怪诞', '规则出题人', '国家公器入局', '神明食材化', '系统反向打工', '末世基建']
  const boards = scopeBoards(scope).map((b, k) => ({
    board: b,
    overview: `${b}${cat ? `的「${cat}」` : ''}头部被${words[(k + salt) % 6]}与${words[(k + 2 + salt) % 6]}占据，新上榜作品普遍在前三章就交代金手指。`,
    reader_mood: b.includes('女') ? '读者厌倦了无脑虐，更想看女主清醒止损、靠能力赢回主动权。' : '读者想要“合理的强”：金手指要有代价，打脸要有铺垫，讨厌降智反派。',
    opportunity: b.includes('新书') ? '新书榜上「职业 + 规则」的组合还没有头部，空位明显。' : '阅读榜长尾里“国家/组织入局”的视角稀缺，适合差异化切入。',
    writing_tips: '开篇 300 字内给冲突，第 1 章末露出金手指，第 2 章第一次兑现。',
    idea_hooks: [{ title: female ? '退婚后我成了首富亲妈' : '我在诡异世界当出题人', pitch: female ? '被退婚当天，她发现自己是首富失散二十年的亲生母亲的女儿' : '全球被拉进规则怪谈，主角却是那个出题的人' }],
    ...(legacy ? {} : { risks: '同质化：系统流开局过多，慎写真实机构名称' }),
  }))
  const base: TrendReportBody = {
    hot_words: words.map((w, i) => ({ word: w, why: `${w}相关作品本周新上榜 ${3 + ((i + salt) % 4)} 本`, examples: [] })),
    boards,
    open_directions: ['民俗职业 + 规则怪谈：殡葬、扎纸、守夜人', '把“国家队”写成主角的后援而非对手', '女频：年代背景下的技术流致富'],
    title_patterns: [
      { pattern: '规则怪谈：从[民俗职业/身份]开始[颠覆/收容]不可名状', examples: ['规则怪谈：从扎纸匠开始收容神明'] },
      { pattern: '开局[一个反常身份]，我[反向操作]', examples: ['开局诡异出题人，我给怪物送分'] },
      { pattern: '[时代]：我靠[冷门技能]养活全家', examples: ['八零：我靠修收音机养活全家'] },
      { pattern: '被[身份]后，我成了[更高身份]', examples: [] },
    ],
    pitfalls: ['金手指出现超过第 3 章，追读断崖', '反派降智只为给主角送脸', '规则怪谈只堆规则不给解法', '前 10 章换三次地图'],
    warnings: legacy ? [] : ['热词「神明食材化」只在 2 本书出现，置信度低'],
  }
  if (legacy) return base
  return {
    ...base,
    headline: female ? '清醒止损压过虐恋，年代技术流成新蓝海' : '「中式怪诞 × 规则出题」接棒系统流，国家入局成爽点新支点',
    summary: female ? '女频头部的情绪价值从“被偏爱”转向“自己赢”，年代题材里技术流致富的书追读最稳；虐恋开局的新书普遍掉榜。'
      : '男频阅读榜前排被规则怪谈与中式民俗包围，主角从“被规则折磨”变成“制定规则的人”；新书里国家公器入局的设定明显增加，爽点从个人打脸扩展到集体胜利。',
    inspirations: [
      { title: female ? '八零：我靠修收音机养活全家' : '诡异世界：我是唯一的出题人', logline: female ? '下岗女工带着全家在八零年代靠修电器起家' : '全球副本的规则，都是我昨晚随手写的', protagonist: female ? '纺织厂下岗女工，手巧嘴硬，带着两个弟弟' : '失业的中学数学老师，擅长出刁钻题', mechanism: female ? '前世维修知识 + 年代信息差' : '出题即生效：他写下的规则会成为副本法则', opening: female ? '下岗名单贴出来那天，她把厂里的废收音机全收了' : '第一道题出完，全班同学被拉进了副本', selling_points: ['身份反转', '规则爽点', '智斗'], board: scopeBoards(scope)[0] },
      { title: female ? '假千金她靠玄学杀疯了' : '我把神明做成了火锅', logline: female ? '被赶出豪门那天，她算出了全家人的死期' : '诸神降临，他是唯一能把神明处理成食材的厨子', protagonist: female ? '被抱错的假千金，道观长大，嘴毒心软' : '老街火锅店第三代传人', mechanism: female ? '看相算命 + 真千金反向求助' : '食神图谱：吃掉神明部件获得权柄', opening: female ? '真千金进门第一天，她说：“你印堂发黑，三日内有血光之灾”' : '一只神明的触手伸进了后厨', selling_points: ['猎奇', '美食', '升级'] },
      { title: '殡仪馆夜班：我能看见死者最后七秒', logline: '每具遗体都会给他留下一道题', protagonist: '殡仪馆夜班化妆师', mechanism: '触碰遗体看到死者最后 7 秒', opening: '第一晚，遗体睁眼说了一个车牌号', selling_points: ['悬疑破案', '中式怪诞', '单元剧'] },
      { title: '国家队请我出山', logline: '异能复苏，国家给他的编号是 001', protagonist: '退伍后开小卖部的老兵', mechanism: '国家后援通联：每完成任务解锁一项国家级支援', opening: '一辆没有牌照的车停在小卖部门口', selling_points: ['国家入局', '热血', '集体胜利'] },
    ],
    opening_hooks: ['开局即规则：第一句话就是一条副本规则', '身份反差：最不该出现在这里的人出现了', '倒计时：三日内必须解决的死局', '反常识：怪物在向主角求饶'],
    plot_devices: [
      { name: '逻辑天平', desc: '每次违反规则都要付出等价代价，让爽点可计算' },
      { name: '战术代差爆破', desc: '用现代知识碾压古旧体系，一章一次小爆点' },
      { name: '民俗禁忌倒挂', desc: '把禁忌变成主角的武器' },
      { name: '国家后援通联', desc: '个人困境升级为集体行动，给大场面' },
    ],
    writing_advice: '前三章每章主角亲自压一次对手；金手指第 1 章末露出、第 2 章兑现。\n规则类设定先给读者一条能验证的小规则，再放大。',
    risk_alerts: ['规则怪谈赛道同质化严重，书名避开“规则怪谈”四字开头', '涉及国家机构时不要写真实部门名称', '神明食材化题材注意不要写得过于血腥'],
    meta: { scope, top_n: db.reportConfig.radar_report_top_n, books_read: boards.length * db.reportConfig.radar_report_top_n },
  }
}
function addReport(scope: string, legacy = false, minsAgo = 0, salt = 0, stale = false) {
  const r: MReport = { id: nid(), snapshot_id: db.snapshots[0]?.id ?? 1, scope, created_at: ago(minsAgo), model: 'mock', stale, snapshot: db.snapshots[0] ?? null, report: mkReportBody(scope, legacy, salt) }
  reports.unshift(r); return r
}
// 种子：总榜（新字段）、男频阅读榜 3 期（含旧格式往期）、女频阅读榜只有旧格式；其余 scope 404
addReport('overall', true, 60 * 24 * 4)
addReport('overall', false, 60 * 3)
addReport('board:male:read', true, 60 * 24 * 4, 1)
addReport('board:male:read', false, 60 * 24 * 2, 2, true)
addReport('board:male:read', false, 60 * 2)
addReport('board:female:read', true, 60 * 5)
const latestOf = (scope: string) => reports.filter((r) => r.scope === normScope(scope)).sort((a, b) => b.id - a.id)[0]
const checkScope = (s: string) => { if (!/^(overall|board:(male|female):(read|new)|category:(male|female):((read|new):)?.+)$/.test(s)) throw new HttpErr(400, `不认识的 scope：${s}`) }
const reportLatest = (_m: any, _b: any, u: URL) => {
  const scope = u.searchParams.get('scope') || 'overall'; checkScope(scope)
  const r = latestOf(scope); if (!r) throw new HttpErr(404, '还没有这个范围的风向标'); return r
}
on('GET', '/radar/report/latest', reportLatest)
on('GET', '/radar/report', reportLatest)
on('GET', '/radar/reports', (_m, _b, u) => {
  const scope = u.searchParams.get('scope'); const full = u.searchParams.get('full') === 'true'; const limit = +(u.searchParams.get('limit') || 10)
  return reports.filter((r) => !scope || r.scope === normScope(scope)).sort((a, b) => b.id - a.id).slice(0, limit)
    .map((r) => (full ? r : { ...r, report: undefined, hot_words: r.report.hot_words.map((h) => h.word) }))
})
on('POST', '/radar/report', (_m, b) => {
  const scope = normScope(b?.scope || 'overall'); checkScope(scope)
  const j = createJob('radar_report', null, 3600, ['读取榜单快照…', `读每榜前 ${db.reportConfig.radar_report_top_n} 本…`, '总结热词与读者情绪…', '生成灵感卡与工具箱…'], () => {
    reports.forEach((r) => { if (r.scope === scope) r.stale = false })
    return addReport(scope, false, 0, reports.length)
  }, `trend_report:${scope}`)
  return { ...j, job_id: j.id }
})

// ---------------- v0.9.2 立项向导 ----------------
function seedIdea(b: any, extra: Partial<Idea> = {}): Idea {
  const gender = b.gender || 'male'
  const idea: Idea = {
    id: nid(), book_id: null, title: String(b.title || '未命名选题').replace(/^《|》$/g, ''), logline: b.logline || '', genre: b.genre || (gender === 'female' ? '年代重生' : '都市高武'),
    selling_points: (b.selling_points?.length ? b.selling_points : ['高概念', '爽点明确', '人设新']).slice(0, 5),
    hook: b.opening || b.hook || '开局即危机，主角当场做出反常选择。',
    scores: { heat: 78, novelty: 72, fit: 74, overall: 74 }, chosen: false, ...extra,
  }
  db.ideas.unshift(idea); return idea
}
on('POST', '/ideas/from-seed', (_m, b) => {
  if (!b?.title || !b?.logline) throw new HttpErr(422, 'title 与 logline 必填')
  if (!b.expand) return { idea: seedIdea(b) }
  const j = createJob('idea_seed', null, 3000, ['读取灵感卡…', '补全钩子与卖点…', '规划主线阶段…', '评分…'], () => ({
    idea: seedIdea(b, {
      hook: b.opening ? `${b.opening}——${b.protagonist ? `${b.protagonist}当场` : '主角当场'}做出了没人想到的选择。` : '开局即危机。',
      arc: ['立足：用金手指解决第一个死局', '扩张：机制升级，卷入更大的势力', '对决：规则背后的出题者现身', '终局：改写世界规则'],
      endgame: '揭开机制的来历，成为新的规则制定者', expectations: ['每章一个小爽点', '三章一个大反转'],
    }),
  }), `seed:${b.source?.type ?? 'manual'}`)
  return { job_id: j.id }
})
on('POST', '/ideas/organize', (_m, b) => {
  const text = String(b?.text || '').trim()
  if (text.replace(/\s/g, '').length < 10) throw new HttpErr(400, '想法太短了，至少写 10 个字')
  const first = text.split(/[\n。！？]/).find((x) => x.trim()) || text
  const j = createJob('idea_organize', null, 2800, ['理解你的想法…', '提炼书名与一句话卖点…', '补全钩子与主线…', '评分…'], () => ({
    idea: seedIdea({ title: first.slice(0, 12).replace(/[，,：:]/g, ''), logline: first.slice(0, 40), genre: b.genre, gender: b.gender, selling_points: ['设定新', '悬念足', '可持续'] }, {
      arc: ['开局：能力觉醒与第一案', '发展：卷入更大的局', '高潮：真相反转', '结局：亲手了结'], endgame: '查清能力来历，了结二十年旧案',
    }),
  }), 'organize')
  return { job_id: j.id }
})
on('POST', '/ideas/fusion', (_m, b) => {
  const refs = (b?.refs ?? []) as { book_id_ext?: string; title?: string; text?: string; weight: number }[]
  if (!refs.length || refs.length > 3) throw new HttpErr(400, '熔炉需要 1–3 本参考书')
  const titles = refs.map((r) => r.title || db.items.find((i) => i.book_id_ext === r.book_id_ext)?.title || '参考书')
  const n = Math.max(1, Math.min(5, b.n || 3))
  const j = createJob('idea_fusion', null, 4200, ['九维度拆解参考书…', '按权重提取卖点…', '融合配方…', '生成选题并做相似自检…'], () => {
    const pool = [
      { title: '我在殡仪馆给神明化妆', logline: '每位来客都是落难的神，而他是唯一能让神体面离开的人', sp: ['中式怪诞', '单元剧', '身份反差'] },
      { title: '规则之外：国家给我发了个编号', logline: '规则副本降临，国家把唯一的“出题人”编进了特别行动队', sp: ['国家入局', '规则爽点', '集体胜利'] },
      { title: '八零年代修神仙', logline: '修电器的年轻人发现，送来修理的收音机里住着神仙', sp: ['年代', '奇幻', '温情'] },
      { title: '我的火锅店只接待诸神', logline: '深夜十二点后，老街火锅店的客人都不是人', sp: ['美食', '猎奇', '经营'] },
      { title: '诡异复苏：我负责出题', logline: '全世界都在答题，只有他知道答案', sp: ['智斗', '高概念', '逆袭'] },
    ]
    const ideas = pool.slice(0, n).map((p, k) => seedIdea({ title: p.title, logline: p.logline, selling_points: p.sp }, { scores: { heat: 80 - k * 3, novelty: 76 - k * 4, fit: 72 - k * 2, overall: 76 - k * 3 } }))
    // 最后一个不入库：演示「保存并打开」
    const loose = n >= 3 ? { ...ideas[ideas.length - 1], id: 0 } : null
    if (loose) db.ideas = db.ideas.filter((x) => x.id !== ideas[ideas.length - 1].id)
    return { ideas: loose ? [...ideas.slice(0, -1), loose] : ideas, dropped: n >= 3 ? 1 : 0, warnings: [`融合自：${titles.map((t, k) => `${t} ${refs[k].weight}%`).join(' + ')}`] }
  }, 'fusion')
  return { job_id: j.id }
})
function splitChapters(text: string) {
  const lines = text.split(/\r?\n/)
  const out: { title: string; chars: number }[] = []
  let cur: { title: string; chars: number } | null = null
  for (const l of lines) {
    if (/^\s*第[一二三四五六七八九十百千零\d]+[章节回]/.test(l)) { cur = { title: l.trim(), chars: 0 }; out.push(cur) }
    else if (cur) cur.chars += l.replace(/\s/g, '').length
  }
  return out
}
on('POST', '/radar/imitate/extract', (_m, b) => {
  const text = String(b?.__file_text ?? b?.text ?? '')
  if (!text.trim()) throw new HttpErr(400, '没有读到正文')
  const name = String(b?.__file_name || '').replace(/\.txt$/i, '')
  const chs = splitChapters(text)
  const body = text.length > 20000 ? text.slice(0, 20000) : text
  return { title_guess: name || text.split(/\n/)[0].slice(0, 16), encoding: 'utf-8', total_chapters: chs.length, chapters: chs.length ? chs.slice(0, 10) : [{ title: '全文', chars: text.replace(/\s/g, '').length }], text: body, text_chars: body.replace(/\s/g, '').length, truncated: body.length < text.length }
})

on('GET', '/radar/report/config', () => db.reportConfig)
on('PUT', '/radar/report/config', (_m, b) => {
  if (b.radar_report_top_n !== undefined) { const n = Number(b.radar_report_top_n); if (!Number.isInteger(n) || n < 3 || n > 50) throw new HttpErr(422, 'radar_report_top_n 需在 3–50'); db.reportConfig.radar_report_top_n = n }
  if (b.radar_report_auto_scopes !== undefined) { (b.radar_report_auto_scopes as string[]).forEach(checkScope); db.reportConfig.radar_report_auto_scopes = [...new Set(b.radar_report_auto_scopes as string[])] }
  return db.reportConfig
})
on('GET', '/radar/config', () => db.radarConfig)
on('PUT', '/radar/config', (_m, b) => (db.radarConfig = { ...db.radarConfig, ...b }))

on('GET', '/books', () => [...db.books].sort((a, b) => b.updated_at.localeCompare(a.updated_at)))
on('POST', '/books', (_m, b) => {
  const book: Book = { id: nid(), title: b.title || `未命名 · ${b.genre}`, genre: b.genre, gender: b.gender, tagline: b.premise ?? '', status: 'bible', target_words: b.target_words || 1_000_000, chapter_words: b.chapter_words || 2200, cover_url: null, created_at: now(), updated_at: now(), stats: { chapters: 0, words: 0, foreshadow_open: 0 }, approval_mode: 'review' }
  db.books.push(book); return book
})
on('GET', '/books/:id', (m) => bookOf(m[1]))
on('PATCH', '/books/:id', (m, b) => {
  const book = bookOf(m[1]); const p = { ...b }
  if (p.approval_mode !== undefined) { if (!['auto', 'review'].includes(p.approval_mode)) throw new HttpErr(422, 'approval_mode 只能是 auto 或 review'); p.agent_auto_apply = p.approval_mode === 'auto' }
  else if (p.agent_auto_apply !== undefined) p.approval_mode = p.agent_auto_apply ? 'auto' : 'review'
  return Object.assign(book, p, { updated_at: now() })
})
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
on('GET', '/books/:id/cards', (m, _b, u) => {
  const t = u.searchParams.get('type'); const all = u.searchParams.get('include_deprecated') === 'true'
  return db.cards.map(normCard).filter((c) => c.book_id === +m[1] && (!t || c.type === t) && (all || c.status !== 'deprecated'))
})
on('POST', '/books/:id/cards', (m, b) => { const c = normCard({ id: nid(), book_id: +m[1], type: b.type, name: b.name, summary: b.summary ?? '', data: b.data ?? {}, known_by: b.known_by ?? [], updated_at: now(), status: b.status ?? 'active', ref_enabled: b.ref_enabled ?? true, soul: null }); if (c.type === 'character' && b.soul) c.soul = { ...emptySoul(), ...b.soul }; db.cards.push(c); return c })
on('GET', '/cards/:id/versions', (m) => {
  const c: any = must(db.cards.find((x) => x.id === +m[1]), '设定卡')
  return [...(c._versions ?? [])].map((v: any, n: number) => ({ n, ...v })).reverse()
})
on('POST', '/cards/:id/versions/:n/restore', (m) => {
  const c: any = normCard(must(db.cards.find((x) => x.id === +m[1]), '设定卡'))
  const v = (c._versions ?? [])[+m[2]]; if (!v) throw new HttpErr(404, '这个版本不存在')
  c._versions = [...(c._versions ?? []), { label: `回滚到「${v.label}」之前`, at: now(), type: c.type, name: c.name, summary: c.summary, data: { ...c.data }, known_by: [...c.known_by] }]
  Object.assign(c, { type: v.type, name: v.name, summary: v.summary, data: { ...v.data }, known_by: [...v.known_by], updated_at: now() })
  return { ...c, versions: c._versions.length, _versions: undefined }
})
on('PUT', '/cards/:id', (m, b) => {
  const c: any = normCard(must(db.cards.find((x) => x.id === +m[1]), '设定卡'))
  const contentKeys = ['type', 'name', 'summary', 'data', 'known_by', 'soul']
  if (b && contentKeys.some((k) => k in b)) c._versions = [...(c._versions ?? []), { label: '手动编辑', at: now(), type: c.type, name: c.name, summary: c.summary, data: { ...c.data }, known_by: [...c.known_by] }].slice(-20)
  c.versions = (c._versions ?? []).length
  const { soul, ...rest } = b ?? {}
  Object.assign(c, rest, { updated_at: now() })
  if (c.type === 'character' && soul && typeof soul === 'object') c.soul = { ...(c.soul ?? emptySoul()), ...soul }
  if (c.type !== 'character') c.soul = null
  return c
})
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
    for (let i = 1; i <= 5; i++) db.outline.push({ id: nid(), book_id: b.id, parent_id: a.id, level: 'chapter', order: i, title: `第${i}章`, summary: '本章细纲：开场冲突 → 金手指显现 → 章尾钩子。', beats: { stage_qi: '三句强情绪对话直接引爆冲突。', stage_cheng: '反派步步紧逼，主角顺势下套。', stage_zhuan: '金手指兑现，当众打脸翻盘。', stage_he: '收下具体好处，章末停在新变故半拍上。', hook_end: '章尾悬念' }, status: 'planned', chapter_id: null })
  }
  b.status = 'writing'
  return {}
}) })
on('POST', '/books/:id/outline/batch-chapters', (m, body) => { const b = bookOf(m[1]); const count = Math.min(20, Math.max(1, Number(body?.count) || 10)); return createJob('outline_batch_chapters', b.id, 3000, ['读取前情与设定…', `批量生成 ${count} 章起承转合详纲…`], () => {
  let arc = db.outline.filter((o) => o.book_id === b.id && o.level === 'arc').slice(-1)[0]
  if (!arc) {
    const r = { id: nid(), book_id: b.id, parent_id: null, level: 'book', order: 1, title: b.title, summary: b.tagline || '', beats: null, status: 'expanded', chapter_id: null } as OutlineNode
    const v = { id: nid(), book_id: b.id, parent_id: r.id, level: 'volume', order: 1, title: '第一卷', summary: '开篇立局', beats: null, status: 'expanded', chapter_id: null } as OutlineNode
    arc = { id: nid(), book_id: b.id, parent_id: v.id, level: 'arc', order: 1, title: '第1弧', summary: '批量章纲', beats: null, status: 'expanded', chapter_id: null } as OutlineNode
    db.outline.push(r, v, arc)
  }
  const start = Math.max(0, ...db.outline.filter((o) => o.book_id === b.id && o.level === 'chapter').map((o) => o.order)) + 1
  const created: number[] = []
  for (let i = 0; i < count; i++) {
    const num = start + i
    const id = nid()
    db.outline.push({ id, book_id: b.id, parent_id: arc.id, level: 'chapter', order: num, title: `第${num}章 推进与反转`, summary: '起承转合千字详纲章节', beats: { stage_qi: '开场直接切冲突。', stage_cheng: '对手加码施压。', stage_zhuan: '主角亮底牌反杀。', stage_he: '落袋收益并埋章末悬念。', hook_end: '新变故上门' }, status: 'planned', chapter_id: null })
    created.push(id)
  }
  return { arc_id: arc.id, start_chapter: start, end_chapter: start + count - 1, created, count, heavy: body?.heavy ?? true }
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

const strip = (c: Chapter) => { const { content, variants, aigc, ...rest } = withStale(c); void content; return { ...rest, aigc: aigc ? { ...aigc, segments: undefined } : aigc ?? null, variants: variants?.map((v) => ({ ...v, content: '' })) } }
on('GET', '/books/:id/chapters', (m) => db.chapters.filter((c) => c.book_id === +m[1]).sort((a, b) => a.number - b.number).map(strip))
// v0.9.1：aigc.stale 由“服务端”按 content_hash 判断
const mhash = (t: string) => { let h = 2166136261; for (let i = 0; i < t.length; i++) h = Math.imul(h ^ t.charCodeAt(i), 16777619); return (h >>> 0).toString(16).padStart(8, '0') + 'mock0000' }
const withStale = (c: Chapter) => { if (c.aigc) c.aigc.stale = mhash(c.content ?? '') !== c.aigc.content_hash; return c }
on('GET', '/chapters/:id', (m) => withStale(must(db.chapters.find((c) => c.id === +m[1]), '章节')))
on('PUT', '/chapters/:id', (m, b) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  Object.assign(c, { title: b.title ?? c.title, content: b.content ?? c.content, updated_at: now() })
  c.words = countWords(c.content ?? '')
  recalc(c.book_id)
  return withStale(c)
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
on('POST', '/books/:id/chapters/golden-three', (m) => { const book = bookOf(m[1]); const have = db.chapters.filter((c) => c.book_id === book.id).length; const need = Math.max(0, 3 - have); return createJob('golden_three', book.id, 4500, ['规划黄金三章详纲…', '写作第 1 章…', '写作第 2 章…', '写作第 3 章…'], () => ({ chapter_ids: Array.from({ length: need }, () => writeOne(book.id, 1).id), outline_created: need, stopped: false })) })
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
on('POST', '/chapters/:id/commit', (m) => { const c = must(db.chapters.find((x) => x.id === +m[1]), '章节'); if (c.variants?.length) throw new HttpErr(409, '请先采纳一个版本再提交'); return createJob('chapter_commit', c.book_id, 1200, ['生成本章摘要并写入底账'], () => { c.status = 'committed'; c.updated_at = now(); return { chapter_id: c.id, number: c.number, chapter: c } }) })

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

on('GET', '/books/:id/style', (m) => db.styles.get(+m[1]) ?? { sample_text: '', baseline: '', voice_notes: '', pov: 'third', tone: '', extracted: null })
on('PUT', '/books/:id/style', (m, b) => { const s = { ...(db.styles.get(+m[1]) ?? { sample_text: '', baseline: '', voice_notes: '', pov: 'third', tone: '', extracted: null }), ...b }; db.styles.set(+m[1], s); return s })
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
// v0.9.1 朱雀 AIGC 检测（mock：按段落里的“AI 腔”特征粗略打标）
function mockAigc(text: string) {
  const segs: { start: number; end: number; label: 'human' | 'ai' | 'suspect'; conf: number }[] = []
  const re = /[^\n]+/g
  let mm: RegExpExecArray | null
  let k = 0
  while ((mm = re.exec(text))) {
    const p = mm[0]; if (!p.trim()) continue
    const score = (/(不禁|一切都|总之|仿佛|与此同时|值得一提)/.test(p) ? 0.5 : 0) + (p.length > 60 ? 0.15 : 0) + (((k * 7 + p.length) % 10) / 20)
    const label = score >= 0.55 ? 'ai' : score >= 0.38 ? 'suspect' : 'human'
    segs.push({ start: mm.index, end: mm.index + p.length, label, conf: +Math.min(0.99, 0.5 + score / 2).toFixed(2) })
    k++
  }
  const tot = segs.reduce((n, s) => n + s.end - s.start, 0) || 1
  const by = (l: string) => segs.filter((s) => s.label === l).reduce((n, s) => n + s.end - s.start, 0) / tot
  const ai = by('ai'), suspect = by('suspect'), human = Math.max(0, 1 - ai - suspect)
  const softmax = +Math.min(0.99, ai * 0.95 + suspect * 0.45 + 0.04).toFixed(4)
  let h = 2166136261; for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  void h
  return {
    checked_at: now(), content_hash: mhash(text), stale: false, softmax, ratio: +ai.toFixed(4),
    labels_ratio: { human: +human.toFixed(4), ai: +ai.toFixed(4), suspect: +suspect.toFixed(4) },
    level: softmax >= 0.85 ? 'high' : softmax >= 0.5 ? 'mid' : 'low',
    ai_segment_ratio: +ai.toFixed(4), suspect_segment_ratio: +suspect.toFixed(4), chars: text.length, is_merge: true,
    segments: segs, tokens: Math.round(text.replace(/\s/g, '').length * 1.3), chunks: Math.max(1, Math.ceil(text.length / 20000)),
  }
}
on('POST', '/detect/aigc', (_m, b) => {
  const text = String(b.text ?? '')
  if (!db.zhuque.zhuque_configured) throw new HttpErr(409, '还没有配置朱雀 API Key')
  if (!text.trim()) throw new HttpErr(422, '文本为空')
  if (text.length > 200000) throw new HttpErr(422, '文本太长')
  const j = createJob('aigc_detect', null, 2400, ['提交朱雀检测…', '分段检测中…', '汇总结果…'], () => {
    const { checked_at, content_hash, stale, ...r } = mockAigc(text); void checked_at; void content_hash; void stale
    db.zhuque.zhuque_usage.calls++; db.zhuque.zhuque_usage.tokens += r.tokens
    return r
  })
  return { ...j, job_id: j.id }
})
on('POST', '/books/:id/chapters/:id/aigc', (m) => {
  const c = must(db.chapters.find((x) => x.id === +m[2] && x.book_id === +m[1]), '章节')
  if (!db.zhuque.zhuque_configured) throw new HttpErr(409, '还没有配置朱雀 API Key')
  if (!(c.content ?? '').trim()) throw new HttpErr(409, '正文为空')
  const j = createJob('chapter_aigc', c.book_id, 2400, ['提交朱雀检测…', '分段检测中…', '汇总结果…'], () => {
    const r = mockAigc(c.content ?? ''); c.aigc = r as any
    db.zhuque.zhuque_usage.calls++; db.zhuque.zhuque_usage.tokens += r.tokens
    return { chapter_id: c.id, aigc: r }
  }, `chapter:${c.id}`)
  return { ...j, job_id: j.id }
})
// v0.9.1 语感重塑（mock：拆长句、去套话；结果走预览-采纳流程）
function polishText(t: string) {
  return t.split('\n').map((p) => p
    .replace(/不禁/g, '').replace(/一切都在往好的方向发展/g, '日子总算松了口气').replace(/于是接下来的几天里，/g, '接下来几天，')
    .replace(/，然后/g, '。').replace(/缓缓地/g, '').replace(/仿佛/g, '像')).join('\n')
}
on('POST', '/books/:id/chapters/:id/polish-voice', (m) => {
  const c = must(db.chapters.find((x) => x.id === +m[2] && x.book_id === +m[1]), '章节')
  if (!(c.content ?? '').trim()) throw new HttpErr(409, '正文为空')
  const j = createJob('chapter_polish_voice', c.book_id, 3000, ['分析语感…', '短句化、动作前置…', '核对人名与数值…'], () => {
    const before = c.content ?? ''
    let after = polishText(before)
    if (after === before) after = before.replace(/。/, '。\n\n他没再多想，抬脚就走。')
    const warnings: string[] = []
    if (/\d/.test(before)) warnings.push('数值核对：原文“信用点 +5”在改写稿中仍为 +5，但“三天”变成了“几天”，请确认')
    warnings.push('人名核对：配角「老周」在改写稿第 4 段没有出现，可能被合并进了动作描写')
    const wb = countWords(before), wa = countWords(after)
    if (Math.abs(wa - wb) / Math.max(1, wb) > 0.02) warnings.push(`字数变化：${wb} → ${wa}（${wa >= wb ? '+' : ''}${Math.round(((wa - wb) / Math.max(1, wb)) * 100)}%）`)
    return {
      chapter_id: c.id, scope: 'all', start: 0, end: before.length, instruction: '语感重塑', label: '语感重塑前',
      before, after, changed: after !== before, words_before: wb, words_after: wa, ai_score_after: mkLint(after).ai_score,
      checks: { numbers_missing: [], numbers_added: [], names_checked: ['林野'], names_missing: ['老周'], words_ratio: +((wa - wb) / Math.max(1, wb)).toFixed(3), long_paragraphs: 0 },
      warnings,
    }
  })
  return { ...j, job_id: j.id }
})
on('POST', '/chapters/:id/apply-rewrite', (m, b) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  ;(chHist[c.id] ??= []).push({ content: c.content ?? '', title: c.title, label: b.label || '按要求改写前' })
  Object.assign(c, { content: b.content, words: countWords(b.content), lint: mkLint(b.content), history: chHist[c.id].length, last_history_label: b.label, updated_at: now() })
    return withStale(c)
})
on('POST', '/chapters/:id/undo', (m) => {
  const c = must(db.chapters.find((x) => x.id === +m[1]), '章节')
  const prev = chHist[c.id]?.pop()
  if (!prev) throw new HttpErr(409, '没有可以撤回的版本')
  return withStale(Object.assign(c, { content: prev.content, title: prev.title, words: countWords(prev.content), lint: mkLint(prev.content), history: chHist[c.id].length }))
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

// ---------------- v0.9.3 ----------------
const SOUL_KEYS = ['desire', 'fear', 'wound', 'belief', 'voice'] as const
const emptySoul = () => ({ desire: '', fear: '', wound: '', belief: '', voice: '' })
function normCard(c: Card): Card {
  if (!c.status) c.status = 'active'
  if (c.ref_enabled === undefined) c.ref_enabled = true
  if (c.type !== 'character') c.soul = null
  else if (c.soul === undefined) c.soul = null
  return c
}
const cardOfBook = (bid: string, cid: string) => { bookOf(bid); const c = db.cards.find((x) => x.id === +cid && x.book_id === +bid); return normCard(must(c, '设定条目')) }
const TYPE_LABEL: Record<string, string> = { world: '世界观', cheat: '金手指', power: '力量体系', faction: '势力', character: '人物', item: '道具', location: '地点' }

function fieldValue(c: Card, field: string): unknown {
  if (field === 'name' || field === 'summary') return c[field]
  if (field.startsWith('data.')) return c.data?.[field.slice(5)] ?? ''
  if (field.startsWith('soul.')) return c.soul?.[field.slice(5) as keyof typeof c.soul] ?? ''
  return undefined
}
function checkField(c: Card, field: string) {
  if (!/^(name|summary|data\.[\w\u4e00-\u9fa5]+|soul\.(desire|fear|wound|belief|voice))$/.test(field)) throw new HttpErr(422, `不支持的字段：${field}`)
  if (field.startsWith('soul.') && c.type !== 'character') throw new HttpErr(400, '只有人物条目有灵魂五维')
}
const FILL: Record<string, string> = {
  'soul.desire': '想让东区重新有一盏不灭的灯', 'soul.fear': '自己定下的规矩，有一天会害死信他的人', 'soul.wound': '冰封第一夜没给邻居开门，第二天在门口看见冻僵的母子',
  'soul.belief': '只换不卖：东西可以给，尊严不能白拿', 'soul.voice': '话少、短句、爱反问；越生气越客气，最后一句永远是「行。」',
  summary: '外冷内热，做事先算账再讲情分。', name: '无名',
}
on('POST', '/books/:id/bible/:eid/field-ai', (m, b) => {
  const c = cardOfBook(m[1], m[2]); const field = String(b?.field ?? ''); checkField(c, field)
  const mode = b?.mode ?? 'fill'
  if (!['fill', 'rewrite', 'expand'].includes(mode)) throw new HttpErr(422, 'mode 只能是 fill / rewrite / expand')
  if (String(b?.instruction ?? '').length > 500) throw new HttpErr(422, 'instruction 不超过 500 字')
  const before = fieldValue(c, field) ?? ''
  return createJob('field_ai', c.book_id, 1800, ['读取条目与相关设定…', mode === 'expand' ? '扩写…' : mode === 'rewrite' ? '按要求改写…' : '补写…'], () => {
    const ins = String(b?.instruction ?? '').trim()
    const base = Array.isArray(before) ? before.join('；') : String(before ?? '')
    let v: string
    if (mode === 'fill') v = base || FILL[field] || `${c.name}的${field.replace(/^(data|soul)\./, '')}：在冰封末世里显得格外扎眼的一处细节`
    else if (mode === 'expand') v = `${base || FILL[field] || c.summary}${base ? '。' : ''}更具体地说：每逢零点补货前，他都会在卷帘门后站上一刻钟，听外面的风声和脚步。`
    else v = `${ins ? `（按「${ins.slice(0, 12)}」）` : ''}${(base || FILL[field] || c.summary).replace(/。$/, '')}，但说出口的永远只有一半。`
    const value = Array.isArray(before) ? v.split(/[；;]/).map((x) => x.trim()).filter(Boolean) : v
    return { entry_id: c.id, field, mode, before, value, note: mode === 'fill' && base ? '字段已有内容，给的是补全版' : '' }
  }, `card:${c.id}`)
})
on('POST', '/books/:id/bible/:eid/field-ai/apply', (m, b) => {
  const c = cardOfBook(m[1], m[2]); const field = String(b?.field ?? ''); checkField(c, field)
  snapBible(c.book_id, `字段 AI 采纳前：${c.name}`)
  if (field === 'name' || field === 'summary') (c as any)[field] = String(b.value ?? '')
  else if (field.startsWith('data.')) c.data = { ...c.data, [field.slice(5)]: b.value }
  else { c.soul = { ...(c.soul ?? emptySoul()), [field.slice(5)]: String(b.value ?? '') } }
  c.updated_at = now(); return c
})
on('GET', '/books/:id/refs', (m, _b, u) => {
  bookOf(m[1]); const q = (u.searchParams.get('q') ?? '').trim(); const limit = Math.min(100, Math.max(1, Number(u.searchParams.get('limit') ?? 20) || 20))
  const order = ['character', 'world', 'cheat', 'power', 'faction', 'location', 'item']
  return db.cards.map(normCard).filter((c) => c.book_id === +m[1] && c.status === 'active' && c.ref_enabled !== false && (!q || c.name.includes(q)))
    .sort((a, b) => order.indexOf(a.type) - order.indexOf(b.type) || a.id - b.id).slice(0, limit)
    .map((c) => ({ id: c.id, name: c.name, type: c.type, type_label: TYPE_LABEL[c.type] ?? c.type, brief: c.summary.slice(0, 40) }))
})
on('POST', '/books/:id/characters/:eid/soul', (m, b) => {
  const c = cardOfBook(m[1], m[2]); if (c.type !== 'character') throw new HttpErr(400, '只有人物条目有灵魂五维')
  const mode = b?.mode ?? 'fill'; const before = { ...emptySoul(), ...(c.soul ?? {}) }
  return createJob('character_soul', c.book_id, 2600, ['读取人物与关系…', '推演欲望与恐惧…', '校对说话方式…'], () => {
    const fresh: Record<string, string> = { desire: `${c.name}最想要的：${FILL['soul.desire']}`, fear: FILL['soul.fear'], wound: FILL['soul.wound'], belief: FILL['soul.belief'], voice: c.data?.voice || FILL['soul.voice'] }
    const soul = Object.fromEntries(SOUL_KEYS.map((k) => [k, mode === 'rewrite' ? fresh[k] : before[k] || fresh[k]]))
    return { entry_id: c.id, mode, before, soul, note: mode === 'fill' ? '只补了空着的几项，已有的原样保留' : '' }
  }, `card:${c.id}`)
})

on('GET', '/books/:id/completeness', (m) => {
  const book = bookOf(m[1]); const id = book.id
  const cards = db.cards.map(normCard).filter((c) => c.book_id === id && c.status === 'active')
  const chars = cards.filter((c) => c.type === 'character')
  const hero = chars.find((c) => c.data?.role === 'protagonist') ?? chars[0]
  const soulFull = !!hero?.soul && SOUL_KEYS.every((k) => (hero.soul as any)[k]?.trim())
  const nodes = db.outline.filter((o) => o.book_id === id)
  const chNodes = nodes.filter((o) => o.level === 'chapter').sort((a, b) => a.order - b.order)
  const ch1 = db.chapters.find((c) => c.book_id === id && c.number === 1)
  const pkg = pkgOf(id)
  const it = (key: string, label: string, done: boolean, hint: string, action: { type: 'route' | 'job'; target: string }, w = 10) => ({ key, label, done, weight: done ? 10 : w, hint: done ? '' : hint, action })
  const items = [
    it('overview', '概览与一句话卖点', !!book.tagline?.trim() && !!book.premise?.trim(), '补一句话卖点和核心设定，AI 写作时会一直参考', { type: 'route', target: `/books/${id}` }, 0),
    it('world', '世界观', cards.some((c) => c.type === 'world' || c.type === 'power'), '还没有世界观或力量体系，可以一键生成', { type: 'job', target: `/api/books/${id}/bible/generate` }, 0),
    hero
      ? it('protagonist', '主角卡（含灵魂五维）', soulFull, `${hero.name}的灵魂五维还没填全，让 AI 补全空着的几项`, { type: 'job', target: `/api/books/${id}/characters/${hero.id}/soul` }, 5)
      : it('protagonist', '主角卡（含灵魂五维）', false, '还没有主角卡', { type: 'job', target: `/api/books/${id}/bible/generate` }, 0),
    it('supporting', '配角≥2', chars.filter((c) => c !== hero).length >= 2, '主角之外至少再有两个能说话的人物', { type: 'route', target: `/books/${id}/bible` }, 0),
    it('factions_locations', '势力/地点', cards.some((c) => c.type === 'faction' || c.type === 'location'), '加一个势力或地点，让冲突有落脚处', { type: 'route', target: `/books/${id}/bible` }, 0),
    it('outline', '大纲', nodes.some((o) => o.level !== 'chapter'), '先生成总纲和分卷', { type: 'job', target: `/api/books/${id}/outline/generate` }, 0),
    it('chapter_plans', '前三章章纲', [1, 2, 3].every((n) => chNodes[n - 1]?.summary?.trim()), '前三章的章纲要先写好', { type: 'route', target: `/books/${id}/outline` }, 0),
    it('chapter1', '第 1 章', !!ch1?.content?.trim(), '写出第 1 章', { type: 'job', target: `/api/books/${id}/chapters/write-next` }, 0),
    it('title_blurb', '书名与简介', !/^未命名/.test(book.title) && !!(pkg.blurb || book.tagline), '定书名、写简介', { type: 'route', target: `/books/${id}/package` }, 0),
    it('cover', '封面', !!(book.cover_url || pkg.chosen_cover), '还没有封面，去包装页生成', { type: 'route', target: `/books/${id}/package` }, 0),
  ]
  return { book_id: id, score: items.reduce((n, x) => n + x.weight, 0), items }
})

const onboardingManual: Record<string, boolean> = {}
let onboardingDismissed = false
const ONB_ORDER = ['model', 'project', 'bible_outline', 'first_chapter'] as const
function onboardingState() {
  const auto = {
    model: db.channels.some((c) => c.enabled && c.models.length),
    project: db.books.length > 0,
    bible_outline: db.books.some((b) => db.cards.some((c) => c.book_id === b.id) && db.outline.some((o) => o.book_id === b.id)),
    first_chapter: db.chapters.some((c) => !!c.content?.trim()),
  }
  const steps = Object.fromEntries(ONB_ORDER.map((k) => [k, auto[k] || !!onboardingManual[k]])) as Record<string, boolean>
  return { steps, order: [...ONB_ORDER], labels: { model: '配置模型', project: '立项', bible_outline: '生成设定与大纲', first_chapter: '写第一章' }, auto, current: ONB_ORDER.find((k) => !steps[k]) ?? null, dismissed: onboardingDismissed }
}
on('GET', '/onboarding', () => onboardingState())
on('PUT', '/onboarding', (_m, b) => {
  if (b?.steps) for (const [k, v] of Object.entries(b.steps)) { if (!(ONB_ORDER as readonly string[]).includes(k)) throw new HttpErr(422, `未知步骤：${k}`); onboardingManual[k] = !!v }
  if (b?.dismissed !== undefined) onboardingDismissed = !!b.dismissed
  return onboardingState()
})

const EST: Record<string, { route: string; calls: number; out: number; sec: number }> = {
  chapter_write: { route: 'writer', calls: 4, out: 3300, sec: 95 }, chapter_rewrite: { route: 'writer', calls: 2, out: 3000, sec: 60 },
  polish_voice: { route: 'writer', calls: 2, out: 3000, sec: 70 }, humanize: { route: 'writer', calls: 2, out: 2600, sec: 55 },
  thicken: { route: 'writer', calls: 2, out: 3600, sec: 65 }, review: { route: 'reviewer', calls: 3, out: 1800, sec: 40 },
  outline: { route: 'planner', calls: 3, out: 6000, sec: 120 }, bible: { route: 'planner', calls: 2, out: 4000, sec: 80 },
  report: { route: 'planner', calls: 1, out: 3000, sec: 45 }, idea: { route: 'planner', calls: 2, out: 2400, sec: 35 },
  field_ai: { route: 'planner', calls: 1, out: 300, sec: 8 }, soul: { route: 'planner', calls: 1, out: 600, sec: 12 },
  teardown: { route: 'planner', calls: 2, out: 3500, sec: 70 }, package: { route: 'planner', calls: 2, out: 1500, sec: 30 },
}
on('POST', '/estimate', (_m, b) => {
  const e = EST[b?.kind]; if (!e) throw new HttpErr(422, `不认识的 kind：${b?.kind}`)
  if (b.book_id) bookOf(String(b.book_id))
  const ch = b.chapter_id ? must(db.chapters.find((c) => c.id === +b.chapter_id), '章节') : null
  const words = Number(b.words) || (b.book_id ? bookOf(String(b.book_id)).chapter_words : 0) || 2200
  const ctx = 3000 + (ch?.content?.length ?? 0) + db.cards.filter((c) => c.book_id === +b.book_id).length * 120
  const out = /^chapter_|polish|humanize|thicken/.test(b.kind) ? Math.round(words * 1.5) : e.out
  const ch0 = db.channels.find((c) => c.enabled && c.models.length)
  return { kind: b.kind, input_tokens_est: ctx * e.calls, output_tokens_est: out, calls_est: e.calls, route: e.route, model: ch0 ? `${ch0.name}/${ch0.models[0]}` : 'mock', seconds_est: e.sec, seconds_source: e.route === 'writer' ? 'history' : 'default', note: !b.book_id && /^chapter_/.test(b.kind) ? '没给书，按通用默认值估算' : '' }
})
on('GET', '/books/:id/usage', (m) => {
  const book = bookOf(m[1])
  const js = db.jobs.filter((j) => j.book_id === book.id && j.status === 'succeeded')
  const kinds = new Map<string, { kind: string; calls: number; in_tokens: number; out_tokens: number; ms: number }>()
  js.forEach((j, i) => { const k = kinds.get(j.kind) ?? { kind: j.kind, calls: 0, in_tokens: 0, out_tokens: 0, ms: 0 }; k.calls += 2 + (i % 3); k.in_tokens += 5200 + i * 311; k.out_tokens += 2100 + i * 97; k.ms += 38000 + i * 1200; kinds.set(j.kind, k) })
  if (book.id === 1 && !kinds.has('review')) kinds.set('review', { kind: 'review', calls: 12, in_tokens: 61200, out_tokens: 18400, ms: 412000 })
  const by_kind = [...kinds.values()].sort((a, b) => b.in_tokens + b.out_tokens - a.in_tokens - a.out_tokens)
  const sum = (k: 'calls' | 'in_tokens' | 'out_tokens' | 'ms') => by_kind.reduce((n, x) => n + x[k], 0)
  return { book_id: book.id, calls: sum('calls'), in_tokens: sum('in_tokens'), out_tokens: sum('out_tokens'), ms: sum('ms'), by_kind,
    by_route: by_kind.length ? [{ route: 'writer', calls: Math.ceil(sum('calls') * 0.6), in_tokens: Math.round(sum('in_tokens') * 0.7), out_tokens: Math.round(sum('out_tokens') * 0.8), ms: Math.round(sum('ms') * 0.7) }, { route: 'reviewer', calls: Math.floor(sum('calls') * 0.4), in_tokens: Math.round(sum('in_tokens') * 0.3), out_tokens: Math.round(sum('out_tokens') * 0.2), ms: Math.round(sum('ms') * 0.3) }] : [],
    last_at: js[0]?.updated_at ?? null }
})

type MTeardown = { id: number; title: string; source: 'rank_book' | 'paste' | 'txt'; book_id_ext: string | null; chars: number; result: Record<string, any>; warnings: string[]; model: string; created_at: string }
const projTeardowns: MTeardown[] = []
function mkTeardownResult(title: string, n: number) {
  const chapters = Math.max(6, Math.min(24, n))
  return {
    structure: { opening: '开局 300 字内把主角扔进死局：冰封夜、门外敲门、手里只有一把没子弹的枪。', rhythm: '三章一小爽、十章一大爽；每卷末用一次身份反转收束。', chapter_hooks: ['章尾留一个「门外的声音」', '章尾抛出新规则的代价', '章尾让对手先出牌'] },
    characters: [
      { role: '主角', template: '谨慎型底层逆袭者：嘴硬心软，先算账再讲情分', traits: ['谨慎', '守规矩', '护短'], function: '用规则制造爽点：别人越线，他按规矩收账' },
      { role: '女主', template: '专业能力型同伴：冷静、话少、关键时刻救场', traits: ['冷静', '专业', '有底线'], function: '补主角短板，制造信任与分歧' },
      { role: '前期反派', template: '地头蛇：贪、狠、但讲面子', traits: ['贪婪', '好面子'], function: '第一块磨刀石，被主角的规则当众打脸' },
    ],
    golden_finger: { mechanism: '每日定时刷新的资源系统，交易换积分升级', limits: '不能主动攻击；刷新前有空窗期', growth: '升级货架 → 解锁新品类 → 影响势力格局', payoff: '别人缺什么他就有什么，用稀缺物资换人心和情报' },
    selling_points: ['稀缺资源 + 规则型主角：看他怎么立规矩、收账', '小场景大压迫：一家店对抗一整个区', '每卷一次身份或规则反转'],
    pacing_chart: Array.from({ length: chapters }, (_, i) => ({ chapter: i + 1, title: `第${i + 1}章`, conflict: 1 + ((i * 3 + 2) % 5), payoff: 1 + ((i * 2 + (i % 3 === 2 ? 3 : 0)) % 5), hook: i % 3 === 2 ? 5 : 2 + (i % 3), note: i % 3 === 2 ? '三章一爽点' : '' })),
    reusable: [
      { name: '规矩收账', pattern: '对手越线 → 主角按事先立好的规矩当众收账 → 围观者站队', how_to_use: '先在前一章立规矩，后一章让反派踩线' },
      { name: '空窗期危机', pattern: '金手指冷却/刷新前的空窗被敌人利用', how_to_use: '每卷用一次，逼主角靠人而不是靠系统' },
      { name: '门外来客', pattern: '章尾有人敲门，下一章开头揭晓身份', how_to_use: '适合做前三章的章尾钩子' },
    ],
    _title: title,
  }
}
function seedTeardowns() {
  const it = db.items[2]
  const r = mkTeardownResult(it.title, 12); delete (r as any)._title
  projTeardowns.push({ id: 31, title: it.title, source: 'rank_book', book_id_ext: it.book_id_ext, chars: 0, result: r, warnings: ['1 条人设描述和原文有连续 8 字相同，已删掉'], model: 'mock', created_at: ago(60 * 26) })
}
seedTeardowns()
const tdOf = (id: string) => must(projTeardowns.find((t) => t.id === +id), '拆书记录')
on('GET', '/teardowns', () => projTeardowns.map((t) => ({ id: t.id, title: t.title, source: t.source, book_id_ext: t.book_id_ext, chars: t.chars, created_at: t.created_at, warnings_count: t.warnings.length,
  modules: Object.entries(t.result).filter(([, v]) => (Array.isArray(v) ? v.length : v && Object.keys(v).length)).map(([k]) => k) })).sort((a, b) => b.id - a.id))
on('GET', '/teardowns/:id', (m) => tdOf(m[1]))
on('DELETE', '/teardowns/:id', (m) => { const t = tdOf(m[1]); projTeardowns.splice(projTeardowns.indexOf(t), 1); return { ok: true } })
on('POST', '/teardowns', (_m, b) => {
  const src = b?.source
  if (!['rank_book', 'paste', 'txt'].includes(src)) throw new HttpErr(422, 'source 只能是 rank_book / paste / txt')
  const text = String(b.text ?? ''); const n = text.replace(/\s/g, '').length
  if (n > 20000) throw new HttpErr(400, `原文超过 20000 字（现在 ${n} 字）`)
  let title = String(b.title ?? '').trim()
  if (src === 'rank_book') { const it = db.items.find((x) => x.book_id_ext === b.book_id_ext); if (!it) throw new HttpErr(404, '榜单里没有这本书'); title ||= it.title }
  else if (!n) throw new HttpErr(400, '请提供原文')
  title ||= `拆书 #${projTeardowns.length + 1}`
  const chs = Math.max(6, (text.match(/第[一二三四五六七八九十百\d]+章/g) || []).length)
  return createJob('teardown_project', null, 4200, ['读取来源…', '拆结构与开篇…', '拆人设与金手指…', '画节奏图…', '去原书专名、查重…'], () => {
    const r = mkTeardownResult(title, src === 'rank_book' ? 15 : chs); delete (r as any)._title
    const t: MTeardown = { id: nid(), title, source: src, book_id_ext: src === 'rank_book' ? b.book_id_ext : null, chars: n, result: r, warnings: n ? [] : ['没有试读原文，只按榜单信息和已有拆解推断，节奏图仅供参考'], model: 'mock', created_at: now() }
    projTeardowns.push(t)
    return { teardown: t, teardown_id: t.id }
  }, 'teardown')
})
on('POST', '/teardowns/:id/to-idea', (m, b) => {
  const t = tdOf(m[1]); const r = t.result
  const seed = { title: `${(r.golden_finger?.mechanism ?? '新机制').slice(0, 6)}：换个世界再开一次店`, logline: `借鉴《${t.title}》的结构：${r.selling_points?.[0] ?? ''}`, opening: r.structure?.opening, mechanism: r.golden_finger?.mechanism, selling_points: r.selling_points ?? [], genre: '末世求生', source: { type: 'teardown', ref: `teardown#${t.id}`, teardown_id: t.id } }
  if (!b?.expand) { const idea = seedIdea(seed as any); return { idea, idea_id: (idea as any).id } }
  const j = createJob('idea_seed', null, 2800, ['读取拆书产物…', '换皮：换世界、换人设…', '评分…'], () => { const idea = seedIdea(seed as any, { hook: `${r.structure?.opening ?? ''}`, arc: ['立足', '扩张', '对决', '终局'], endgame: '成为新规则的制定者', expectations: ['三章一爽点'] }); return { idea, idea_id: (idea as any).id } }, `teardown:${t.id}`)
  return { job_id: j.id }
})
on('POST', '/teardowns/:id/to-bible', (m, b) => {
  const t = tdOf(m[1]); const book = bookOf(String(b?.book_id ?? 0)); const parts: string[] = b?.parts ?? []
  if (!parts.length || parts.some((p) => !['characters', 'golden_finger', 'reusable', 'selling_points'].includes(p))) throw new HttpErr(422, 'parts 不能为空，且只能是 characters / golden_finger / reusable / selling_points')
  snapBible(book.id, `拆书写入前：${t.title}`)
  const r = t.result; const cards: Card[] = []
  const add = (type: Card['type'], name: string, summary: string, data: Record<string, any>) => { const c = normCard({ id: nid(), book_id: book.id, type, name, summary, data: { ...data, from_teardown: t.id, draft: true }, known_by: [], updated_at: now(), status: 'active', ref_enabled: true, soul: type === 'character' ? emptySoul() : null }); db.cards.push(c); cards.push(c) }
  if (parts.includes('characters')) (r.characters ?? []).forEach((c: any) => add('character', `模板·${c.role}`, c.template, { traits: c.traits, function: c.function }))
  if (parts.includes('golden_finger') && r.golden_finger) add('power', '模板·金手指', r.golden_finger.mechanism ?? '', { limits: r.golden_finger.limits, growth: r.golden_finger.growth, payoff: r.golden_finger.payoff })
  if (parts.includes('reusable')) (r.reusable ?? []).forEach((x: any) => add('world', `套路·${x.name}`, x.pattern, { kind: 'reusable', how_to_use: x.how_to_use }))
  if (parts.includes('selling_points')) (r.selling_points ?? []).forEach((x: string, i: number) => add('world', `卖点 ${i + 1}`, x, { kind: 'selling_point' }))
  return { cards, warnings: [], skipped: 0 }
})

// ---------------- 安装 ----------------
export function installMock() {
  const real = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    const url = new URL(raw, location.origin)
    if (!url.pathname.startsWith('/api/')) return real(input, init)
    const method = (init?.method || 'GET').toUpperCase()
    const path = url.pathname.slice(4)
    let body: any = {}
    if (typeof FormData !== 'undefined' && init?.body instanceof FormData) {
      const f = init.body.get('file') as File | null
      body = { __file_name: f?.name ?? '', __file_text: f ? await f.text() : '' }
    } else if (init?.body) body = JSON.parse(String(init.body))
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

// ---------------- v0.10 同人创作（mock） ----------------
const FF_FIDELITY: Record<string, { label: string; desc: string; pass: number }> = {
  strict: { label: '严格遵循', desc: '严格遵循原著设定与时间线：人设、关系、能力体系、已发生事件都不改。', pass: 80 },
  moderate: { label: '有据延展', desc: '可改支线与结局，人设不变：角色核心性格、说话方式、关系底色不动。', pass: 70 },
  loose: { label: '分歧世界（AU）', desc: 'AU，只保留人物核心：身份、世界、时代都可以换，人物的核心性格与动机不变。', pass: 55 },
}
const FF_DIRS: [string, string, string, string][] = [
  ['canon_fill', '原著向补完', 'strict', '在原著时间线的留白里补写：没写到的日常、幕后、视角之外的事。'],
  ['if_line', 'if 线改写', 'moderate', '从原著某个关键节点分岔：如果当时做了另一个选择，之后会怎样。'],
  ['transmigration', '穿书', 'moderate', '现代人穿进原著世界，带着剧情先知进入故事，和原著角色发生联系后改变剧情。'],
  ['rebirth', '重生', 'moderate', '原著角色带着前世（原著结局）的记忆回到过去，弥补遗憾或改写命运。'],
  ['system', '系统', 'moderate', '给原著角色或穿越者绑定系统，用任务与奖励推动在原著世界里的行动。'],
  ['au_modern', 'AU 现代', 'loose', '把原著角色放进现代都市：校园、职场、娱乐圈等，身份全换，人物核心不变。'],
  ['au_ancient', 'AU 古代', 'loose', '把原著角色放进古代或架空王朝：宫廷、江湖、宅斗等，身份重设，核心性格保留。'],
  ['side_pov', '配角主视角', 'strict', '以原著配角为主角，重看原著故事或写他的独立经历。'],
  ['cp', 'CP 向', 'moderate', '围绕一对角色的感情线展开，可以是原著官配，也可以是读者向的配对。'],
  ['villain_redemption', '反派洗白', 'moderate', '给原著反派补动机、补过去，让读者理解甚至同情他。'],
  ['epilogue', '后日谈', 'moderate', '写原著结局之后的故事：众人各自的去处、新的日常或新的危机。'],
  ['crossover', '跨作品联动', 'loose', '让两部（或多部）作品的角色相遇，碰撞出新的故事。'],
  ['multi_transmigration', '多本穿越', 'moderate', '主角在多部作品的世界之间穿梭，每个世界完成目标后进入下一个。'],
  ['reverse_transmigration', '反向穿越', 'moderate', '原著角色穿到现实世界，用原著里的本事在新世界生活。'],
  ['revival', '角色复活', 'moderate', '原著里死去的角色活了下来，故事从他的存活开始改写。'],
  ['unfinished', '烂尾续写', 'strict', '原著烂尾或断更，接着原著最后一章往下写。'],
]
const FF_CATALOG = {
  directions: FF_DIRS.map(([id, label, sf, desc]) => ({
    id, label, desc, suggested_fidelity: sf,
    tips: ['先确定切入的原著时间点', '角色言行以原著性格为准', `「${label}」的爽点要尽早让读者看到`],
    risks: ['人物 OOC', '和原著情节重合过多'],
    template: `方向：${label}。切入点：；涉及角色：；想看到的走向：`,
    slots: [{ key: 's0', label: '切入点', placeholder: '', optional: true }, { key: 's1', label: '涉及角色', placeholder: '', optional: true }, { key: 's2', label: '想看到的走向', placeholder: '', optional: true }],
  })),
  povs: [{ id: 'first', label: '第一人称主角' }, { id: 'third_limited', label: '第三人称主角限知' }, { id: 'third_multi', label: '第三人称多视角' }, { id: 'canon_pov', label: '原著角色视角' }, { id: 'omniscient', label: '全知视角' }],
  oc_types: [{ id: 'transmigrator', label: '穿越者' }, { id: 'native', label: '原住民原创角色' }, { id: 'soul_swap', label: '魂穿原著角色' }],
  fidelities: Object.entries(FF_FIDELITY).map(([id, f]) => ({ id, label: f.label, desc: f.desc, pass_score: f.pass })),
  copyright_notice: '同人创作仅供个人创作与学习交流使用。原著资料只能来自你有权使用的文本；本工具不保存原文，只保存提炼出的设定卡与无法还原原文的指纹。对外发布前，请遵守发布平台的同人创作规则，并自行确认原著的授权范围；未经原著版权方授权，不得用于任何商业用途。',
}
type MFfSource = { id: number; title: string; source: 'paste' | 'txt' | 'search'; chars: number; total_chars: number; depth: string; focus: string[]; cards: any; warnings: string[]; model: string; created_at: string; updated_at: string; refs?: string[]; template_id?: string; web_rounds?: number; entries?: any[]; intro?: string; tags?: string[] }
const ffSources: MFfSource[] = []
const ffChapterMeta = new Map<number, { ooc?: any; overlap?: any }>()
function ffCards(focus: string[]) {
  const base = [
    { name: '沈渡', aliases: ['阿渡', '沈公子'], role: '主角', personality: '表面散漫，实则心思极细；护短，对承诺看得比命重。', speech_style: '说话慢，爱用反问，紧张时反而开玩笑', catchphrases: ['急什么。', '这事我应下了。'], relations: [{ target: '顾晚棠', relation: '青梅竹马，互相试探' }, { target: '裴照', relation: '宿敌' }], abilities: ['听风剑法', '辨识毒物'], limits: ['不会水', '旧伤在左肩，阴雨天出剑慢半拍'], notes: '' },
    { name: '顾晚棠', aliases: ['棠儿'], role: '主要配角', personality: '冷静果决，嘴硬心软，凡事先算三步。', speech_style: '短句，不带语气词，生气时称对方全名', catchphrases: ['别动。'], relations: [{ target: '沈渡', relation: '青梅竹马' }], abilities: ['机关术', '医术'], limits: ['不会武功'], notes: '' },
    { name: '裴照', aliases: ['裴大人'], role: '反派', personality: '克制、骄傲，坚信秩序高于人情。', speech_style: '官腔，句子长，喜欢引典故', catchphrases: ['规矩就是规矩。'], relations: [{ target: '沈渡', relation: '宿敌，曾是同门' }], abilities: ['寒霜掌', '调动巡城卫'], limits: ['不能离开京城超过三日'], notes: '' },
  ]
  focus.filter((f) => f && !base.some((c) => c.name === f)).slice(0, 3).forEach((f) => base.push({ name: f, aliases: [], role: '主要配角', personality: '（按重点角色补充提炼）', speech_style: '', catchphrases: [], relations: [], abilities: [], limits: [], notes: '' }))
  return {
    characters: base,
    world: { summary: '架空王朝，江湖与朝堂并立；京城十二坊各有门派把守。', rules: ['江湖人入京须登记', '剑法分九品，越品对战极难取胜'], locations: [{ name: '长明坊', desc: '京城最热闹的坊市，暗藏黑市' }, { name: '听风崖', desc: '沈渡师门旧址' }] },
    factions: [{ name: '巡城卫', stance: '朝廷', members: ['裴照'], notes: '负责京城治安' }, { name: '听风门', stance: '江湖', members: ['沈渡'], notes: '已没落' }],
    timeline: [
      { order: 1, event: '听风门一夜覆灭，沈渡下落不明', characters: ['沈渡'], impact: '沈渡与裴照结仇' },
      { order: 2, event: '沈渡化名回京，在长明坊开药铺', characters: ['沈渡', '顾晚棠'], impact: '与顾晚棠重逢' },
      { order: 3, event: '上元夜刺杀案，裴照奉命追查', characters: ['裴照', '沈渡'], impact: '二人第一次正面交锋' },
    ],
    scenes: [{ title: '上元夜屋顶对峙', summary: '灯市之上，两人隔着一条长街对峙，谁也没先出手。', characters: ['沈渡', '裴照'] }],
  }
}
function ffBrief(s: MFfSource) {
  const c = s.cards
  const counts = { characters: c.characters.length, factions: c.factions.length, timeline: c.timeline.length, scenes: c.scenes.length }
  const completeness = Math.min(100, counts.characters * 8 + counts.factions * 5 + counts.timeline * 4 + counts.scenes * 4 + (c.world.summary ? 15 : 0) + c.world.rules.length * 3)
  return { id: s.id, title: s.title, source: s.source, chars: s.chars, total_chars: s.total_chars, depth: s.depth, focus: s.focus, completeness, counts, warnings_count: s.warnings.length,
    used_by: db.books.filter((b) => b.fanfic && (b.fanfic.source_id === s.id || b.fanfic.extra_source_ids?.includes(s.id))).map((b) => b.id), model: s.model, created_at: s.created_at, updated_at: s.updated_at,
    template_id: s.template_id ?? '', web_rounds: s.web_rounds ?? 0, refs_count: s.refs?.length ?? 0,
    intro: s.intro ?? s.cards.world.summary ?? '', tags: s.tags ?? [], entry_counts: ffCounts(s) }
}
const ffOut = (s: MFfSource) => { const b = ffBrief(s); return { ...b, cards: s.cards, warnings: s.warnings, refs: s.refs ?? [], books: b.used_by.map((id) => { const bk = db.books.find((x) => x.id === id)!; return { id, title: bk.title, direction: bk.fanfic?.direction ?? '', words: bk.stats?.words ?? 0 } }) } }
// v0.15 原著世界库（演示）：从设定卡派生条目
let ffEid = 1
function ffDerive(c: any): any[] {
  const out: any[] = []
  c.world.rules.forEach((r: string) => out.push({ cat: 'world', sub: /境界|等级|魂|修炼|品|阶/.test(r) ? '力量体系' : '世界规则', name: r.split(/[：:，,。；]/)[0].slice(0, 16), summary: r, detail: '', tags: [] }))
  c.world.locations.forEach((l: any) => out.push({ cat: 'world', sub: '地理地点', name: l.name, summary: l.desc, detail: '', tags: [] }))
  c.factions.forEach((f: any) => out.push({ cat: 'world', sub: '组织势力', name: f.name, summary: [f.stance, f.notes].filter(Boolean).join('；'), detail: f.members.length ? `成员：${f.members.join('、')}` : '', tags: f.members }))
  c.characters.forEach((ch: any) => {
    out.push({ cat: 'character', sub: ch.role?.includes('反派') ? '反派' : ch.role === '主角' ? '主角' : '主要配角', name: ch.name, summary: ch.personality, detail: [['说话方式', ch.speech_style], ['能力', ch.abilities.join('、')], ['上限', ch.limits.join('、')]].filter((x) => x[1]).map((x) => x.join('：')).join('\n'), tags: ch.aliases })
    ch.relations.forEach((r: any) => out.push({ cat: 'relation', sub: /宿敌|敌|仇/.test(r.relation) ? '宿敌' : /青梅|恋|爱/.test(r.relation) ? '伴侣' : '同伴', name: `${ch.name} — ${r.target}`, summary: r.relation, detail: '', tags: [ch.name, r.target] }))
  })
  c.timeline.forEach((t: any, i: number) => out.push({ cat: 'timeline', sub: '剧情时间线', name: t.event.slice(0, 40), summary: t.impact, detail: '', tags: t.characters, order: t.order ?? i + 1 }))
  c.scenes.forEach((sc: any) => out.push({ cat: 'timeline', sub: '名场面', name: sc.title, summary: sc.summary, detail: '', tags: sc.characters }))
  return out.map((e) => ({ order: 0, ...e, id: `e${ffEid++}` }))
}
const ffEnts = (s: MFfSource) => (s.entries ??= ffDerive(s.cards))
function ffCounts(s: MFfSource) { const o: Record<string, number> = { world: 0, character: 0, timeline: 0, relation: 0 }; ffEnts(s).forEach((e) => { o[e.cat]++ }); return o }
// v0.11.1 联网取材（演示）：按模板人物生成设定卡，来源链接为演示地址
const ffNorm = (x: string) => x.replace(/[\s·・:：]/g, '').toLowerCase()
const ffFindTpl = (id?: string | null, title?: string) => FF_TEMPLATES.find((t) => t.id === id)
  ?? (title ? FF_TEMPLATES.find((t) => [t.title, ...t.aliases].some((n) => ffNorm(n) === ffNorm(title))) : undefined)
const ffWebRounds = (depth: string, focus: string[], tpl?: FanficTemplate) => ({ quick: 2, standard: 4, deep: 6 }[depth] ?? 4) + (depth === 'deep' && tpl ? 1 : 0) + Math.min(6, focus.length)
function ffWebCards(work: string, focus: string[], tpl?: FanficTemplate) {
  const names = [...new Set([...focus, ...(tpl?.characters ?? [])])].slice(0, 6)
  if (!names.length) names.push(`${work}主角`)
  return {
    characters: names.map((n, k) => ({ name: n, aliases: [], role: k === 0 ? '主角' : '主要配角', personality: `${n}性格鲜明，有自己的坚持（演示，联网资料请核对）`, speech_style: k === 0 ? '话不多，关键时一句定调' : '语气随和',
      catchphrases: [], relations: k ? [{ target: names[0], relation: '同伴' }] : [], abilities: ['（按原著体系补充）'], limits: [], notes: '' })),
    world: { summary: tpl ? `${tpl.intro}（演示）` : `《${work}》的世界观概述（演示）`, rules: (tpl?.search_focus ?? ['力量体系等级']).slice(0, 3).map((x) => `${x}（演示，待核对）`), locations: [] },
    factions: [], timeline: [{ order: 1, event: `${names[0]}踏上主线旅程（演示）`, characters: names.slice(0, 2), impact: '故事展开' }],
    scenes: [],
  }
}
const ffDemoRefs = (tpl?: FanficTemplate, n = 3) => Array.from({ length: n }, (_, i) => `https://example.com/novelos-demo/${tpl?.id ?? 'work'}/${i + 1}`)
function ffMergeWeb(s: MFfSource, web: any) {
  const have = new Set(s.cards.characters.map((c: any) => c.name))
  const add = web.characters.filter((c: any) => !have.has(c.name)).map((c: any) => ({ ...c, notes: '（联网补充，可能有误，请核对）' }))
  s.cards.characters.push(...add)
  if (!s.cards.world.summary) s.cards.world.summary = web.world.summary
  s.cards.world.rules = [...new Set([...s.cards.world.rules, ...web.world.rules])].slice(0, 12)
  s.cards.timeline.push(...web.timeline.map((t: any, i: number) => ({ ...t, order: s.cards.timeline.length + i + 1 })))
  return `联网补充：角色 ${add.length}、时间线 ${web.timeline.length}（以原文为准，联网内容可能有误，请核对）`
}
const ffOf = (id: string | number) => must(ffSources.find((s) => s.id === +id), '原著资料')
ffSources.push({ id: 51, title: '示例原著·听风录', source: 'paste', chars: 48210, total_chars: 48210, depth: 'standard', focus: ['沈渡'], cards: ffCards([]), warnings: ['1 条名场面摘要和原文有连续 8 字相同，已删掉'], model: 'mock', created_at: ago(60 * 30), updated_at: ago(60 * 3) })
ffSources.push({ id: 52, title: '斗罗大陆', source: 'search', chars: 0, total_chars: 0, depth: 'standard', focus: ['唐三'], cards: ffWebCards('斗罗大陆', ['唐三'], FF_TEMPLATES[0]), warnings: ['资料来自联网检索（5 轮），可能有误或混入同人二设，请逐条核对（演示）'], model: 'mock', created_at: ago(60 * 10), updated_at: ago(60 * 2), refs: ffDemoRefs(FF_TEMPLATES[0], 4), template_id: 'douluo', web_rounds: 5 })

on('GET', '/fanfic/directions', () => FF_CATALOG)
on('GET', '/fanfic/templates', () => ({ templates: FF_TEMPLATES, categories: FF_TEMPLATE_CATEGORIES, search: { mode: 'mock', available: true, hint: '演示模式：未联网，返回演示资料' } }))
on('POST', '/fanfic/sources/:id/supplement', (m, b) => {
  const s = ffOf(m[1]); const depth = b?.depth ?? 'standard'
  if (!['quick', 'standard', 'deep'].includes(depth)) throw new HttpErr(422, 'depth 只能是 quick / standard / deep')
  const focus: string[] = Array.isArray(b?.focus) ? b.focus : s.focus
  const tpl = ffFindTpl(s.template_id, s.title); const rounds = ffWebRounds(depth, focus, tpl)
  return createJob('fanfic_supplement', null, 1800 + rounds * 400, [`联网检索《${s.title}》：共 ${rounds} 轮（演示）…`, '整理联网资料…', '以现有设定卡为准合并…'], () => {
    const w = ffMergeWeb(s, ffWebCards(s.title, focus, tpl))
    s.warnings = [...s.warnings, w]; s.refs = [...new Set([...(s.refs ?? []), ...ffDemoRefs(tpl)])]; s.web_rounds = (s.web_rounds ?? 0) + rounds
    s.template_id = s.template_id || tpl?.id || ''; s.updated_at = now()
    return { source: ffOut(s), source_id: s.id, added: { characters: 1 }, warnings: [w] }
  }, `fanfic_source:${s.id}`)
})
on('GET', '/fanfic/sources', () => [...ffSources].sort((a, b) => b.id - a.id).map(ffBrief))
on('GET', '/fanfic/sources/:id', (m) => ffOut(ffOf(m[1])))
on('POST', '/fanfic/sources', (_m, b) => {
  const isFile = '__file_text' in (b ?? {})
  const text = String(isFile ? b.__file_text : b?.text ?? '')
  const src = isFile ? 'txt' : b?.source
  const depth = b?.depth ?? 'standard'
  if (!['paste', 'txt', 'search'].includes(src)) throw new HttpErr(422, 'source 只能是 paste / txt / search')
  if (!['quick', 'standard', 'deep'].includes(depth)) throw new HttpErr(422, 'depth 只能是 quick / standard / deep')
  const work = String(b?.title ?? '').trim().slice(0, 60)
  const webOn = src !== 'search' && ['1', 'true', true].includes(b?.web_supplement)
  if ((src === 'search' || webOn) && !work) throw new HttpErr(422, src === 'search' ? '联网取材请填写作品名' : '联网补充需要填写原著名（作品名），用来检索')
  const tpl = ffFindTpl(b?.template_id, work)
  if (src === 'search') {
    const focus: string[] = Array.isArray(b?.focus) ? b.focus : []
    const rounds = ffWebRounds(depth, focus, tpl)
    const steps = [`联网检索《${work}》：共 ${rounds} 轮（演示）…`, '检索：概况与世界观、主要人物…', '整理联网资料成设定卡…']
    return createJob('fanfic_source', null, 1800 + rounds * 500, steps, () => {
      const s: MFfSource = { id: nid(), title: work, source: 'search', chars: 0, total_chars: 0, depth, focus, cards: ffWebCards(work, focus, tpl),
        warnings: [`资料来自联网检索（${rounds} 轮），可能有误或混入同人二设，请逐条核对；不确定的内容没有写入。纯联网资料没有原文指纹，无法做原著重合检查`],
        model: 'mock', created_at: now(), updated_at: now(), refs: ffDemoRefs(tpl, 4), template_id: tpl?.id ?? '', web_rounds: rounds }
      ffSources.push(s)
      return { source: ffOut(s), source_id: s.id }
    }, 'fanfic_source:search')
  }
  const n = text.replace(/\s/g, '').length
  if (n < 200) throw new HttpErr(400, `原文太短（${n} 字），至少 200 字`)
  const focus: string[] = Array.isArray(b?.focus) ? b.focus : []
  const title = String(b?.title || (isFile ? String(b.__file_name).replace(/\.txt$/i, '') : '') || `原著资料 #${ffSources.length + 1}`).slice(0, 60)
  const rounds = depth === 'quick' ? 1 : depth === 'deep' ? 4 : 2
  const steps = ['读取原文，按重点取段…', ...Array.from({ length: rounds }, (_, i) => `提炼第 ${i + 1}/${rounds} 轮：角色、世界观、时间线…`), '合并同名角色，去掉与原文重合的字段…']
  return createJob('fanfic_source', null, 1600 + rounds * 1100, steps, () => {
    const s: MFfSource = { id: nid(), title, source: src, chars: Math.min(n, 200000), total_chars: n, depth, focus, cards: ffCards(focus), warnings: n > 200000 ? [`原文 ${n} 字，只取了 20 万字（重点段落优先）`] : [], model: 'mock', created_at: now(), updated_at: now(), template_id: tpl?.id ?? '' }
    if (webOn) {
      const r = ffWebRounds(depth, focus, tpl)
      s.warnings.unshift(ffMergeWeb(s, ffWebCards(work, focus, tpl))); s.refs = ffDemoRefs(tpl); s.web_rounds = r
    }
    ffSources.push(s)
    return { source: ffOut(s), source_id: s.id }
  }, `fanfic_source:${src}`)
})
on('PUT', '/fanfic/sources/:id', (m, b) => {
  const s = ffOf(m[1]); const warnings: string[] = []
  if (b?.title !== undefined) s.title = String(b.title).slice(0, 60) || s.title
  if (b?.intro !== undefined) s.intro = String(b.intro).slice(0, 600)
  if (Array.isArray(b?.tags)) s.tags = b.tags.slice(0, 12)
  if (b?.cards) {
    const bad = Object.keys(b.cards).filter((k) => !['characters', 'world', 'factions', 'timeline', 'scenes'].includes(k))
    if (bad.length) throw new HttpErr(422, `cards 里有不认识的键：${bad.join('、')}`)
    Object.assign(s.cards, b.cards)
    const longText = JSON.stringify(b.cards)
    if (/原文|原著第/.test(longText)) warnings.push('有字段和原著原文有连续 8 字相同，请用自己的话改写（已保存，未删除）')
  }
  s.updated_at = now()
  return { source: ffOut(s), warnings }
})
on('DELETE', '/fanfic/sources/:id', (m, _b, u) => {
  const s = ffOf(m[1]); const used = ffBrief(s).used_by
  if (used.length && u.searchParams.get('force') !== 'true') throw new HttpErr(409, `有 ${used.length} 本同人书在用这份原著资料，加 force=true 才能删除`)
  ffSources.splice(ffSources.indexOf(s), 1); return { ok: true }
})
on('GET', '/fanfic/sources/:id/entries', (m, _b, u) => {
  const s = ffOf(m[1]); const sp = u.searchParams; const cat = sp.get('cat'); const sub = sp.get('sub'); const q = (sp.get('q') ?? '').toLowerCase()
  const size = Number(sp.get('size') || 36); const all = ffEnts(s); const inCat = all.filter((e) => !cat || e.cat === cat)
  const subs: Record<string, number> = {}; inCat.forEach((e) => { subs[e.sub] = (subs[e.sub] ?? 0) + 1 })
  const items = inCat.filter((e) => (!sub || e.sub === sub) && (!q || `${e.name}${e.summary}${e.detail}${e.tags.join(' ')}`.toLowerCase().includes(q)))
  if (cat === 'timeline') items.sort((a, b) => Number(a.sub === '名场面') - Number(b.sub === '名场面') || (a.order || 1e6) - (b.order || 1e6))
  const pages = Math.max(1, Math.ceil(items.length / size)); const page = Math.min(pages, Math.max(1, Number(sp.get('page') || 1)))
  return { items: items.slice((page - 1) * size, page * size), total: items.length, page, pages, cats: ffCounts(s), subs: Object.entries(subs).map(([k, v]) => ({ sub: k, count: v })), all: all.length }
})
on('POST', '/fanfic/sources/:id/entries', (m, b) => {
  const s = ffOf(m[1]); if (!b?.cat || !b?.name?.trim()) throw new HttpErr(422, '类别和名字必填')
  if (ffEnts(s).some((e) => e.cat === b.cat && e.name === b.name.trim())) throw new HttpErr(409, `已经有「${b.name}」这一条了`)
  const e = { id: `e${ffEid++}`, cat: b.cat, sub: b.sub || '其他设定', name: b.name.trim(), summary: b.summary ?? '', detail: b.detail ?? '', tags: b.tags ?? [], order: b.order ?? 0 }
  ffEnts(s).push(e); return e
})
routes.unshift(['PUT', /^\/fanfic\/sources\/(\d+)\/entries\/(\w+)$/, (m, b) => {
  const s = ffOf(m[1]); const e = must(ffEnts(s).find((x) => x.id === m[2]), '条目'); Object.assign(e, b); return e
}])
routes.unshift(['DELETE', /^\/fanfic\/sources\/(\d+)\/entries\/(\w+)$/, (m) => {
  const s = ffOf(m[1]); s.entries = ffEnts(s).filter((x) => x.id !== m[2]); return { ok: true }
}])
on('POST', '/fanfic/sources/:id/expand', (m, b) => {
  const s = ffOf(m[1]); const cat = b?.cat; const sub = b?.sub || ''; const n = Math.min(40, Math.max(5, b?.count ?? 20))
  return createJob('fanfic_expand', null, 2600, [`联网检索《${s.title}》（演示）…`, '整理条目…', '并入世界库…'], () => {
    const subs = cat === 'world' ? ['力量体系', '关键物品', '组织势力', '地理地点'] : cat === 'character' ? ['主要配角'] : cat === 'timeline' ? ['剧情时间线'] : ['同伴']
    const have = new Set(ffEnts(s).map((e) => e.name)); let added = 0
    for (let i = 0; i < n; i++) {
      const sb = sub || subs[i % subs.length]; const name = cat === 'relation' ? `角色${i + 1} — 角色${i + 2}（演示）` : `${sb}条目${ffEid}（演示）`
      if (have.has(name)) continue
      ffEnts(s).push({ id: `e${ffEid++}`, cat, sub: sb, name, summary: '演示条目：一句话要点', detail: '演示条目的展开说明：来历、规则与限制。', tags: [], order: 100 + i }); added++
    }
    return { source_id: s.id, added, cat }
  }, `fanfic_source:${s.id}`)
})
const ffValidate = (f: any, ack: any) => {
  if (ack !== true) throw new HttpErr(400, '建同人书前请先阅读并勾选版权声明')
  ffOf(f?.source_id ?? 0)
  if (f.fidelity && !FF_FIDELITY[f.fidelity]) throw new HttpErr(422, 'fidelity 只能是 strict / moderate / loose')
  if (f.direction && !FF_DIRS.some((d) => d[0] === f.direction)) throw new HttpErr(422, 'direction 不合法')
}
const ffSet = (book: any, f: any, keepAck = false) => {
  const s = ffOf(f.source_id)
  book.fanfic = { source_id: s.id, source_title: s.title, fidelity: f.fidelity ?? 'moderate', direction: f.direction ?? 'canon_fill', extra_source_ids: f.extra_source_ids ?? [], notes: f.notes ?? '',
    copyright_ack: true, copyright_ack_at: keepAck && book.fanfic ? book.fanfic.copyright_ack_at : now(), attached_at: now() }
}
const ffInfo = (book: any) => {
  const f = book.fanfic
  if (!f) return { book_id: book.id, fanfic: null }
  const s = ffSources.find((x) => x.id === f.source_id)
  return { book_id: book.id, fanfic: { ...f, direction_label: FF_DIRS.find((d) => d[0] === f.direction)?.[1] ?? f.direction, fidelity_label: FF_FIDELITY[f.fidelity]?.label ?? f.fidelity, source: s ? ffBrief(s) : null, source_missing: !s } }
}
// 覆盖 POST /books：同人建书（routes 先匹配先用，所以放到最前）
routes.unshift(['POST', /^\/books$/, (_m, b) => {
  if (b?.fanfic) ffValidate(b.fanfic, b.copyright_ack)
  const book: Book = { id: nid(), title: b.title || `未命名 · ${b.genre}`, genre: b.genre, gender: b.gender, tagline: b.premise ?? '', status: 'bible', target_words: b.target_words || 1_000_000, chapter_words: b.chapter_words || 2200, cover_url: null, created_at: now(), updated_at: now(), stats: { chapters: 0, words: 0, foreshadow_open: 0 }, approval_mode: 'review' }
  if (b?.premise) book.premise = b.premise
  if (b?.fanfic) ffSet(book, b.fanfic)
  db.books.push(book); return book
}])
on('GET', '/books/:id/fanfic', (m) => ffInfo(bookOf(m[1])))
on('POST', '/books/:id/fanfic', (m, b) => { const book = bookOf(m[1]); ffValidate(b, b?.copyright_ack); ffSet(book, b); return ffInfo(book) })
on('PATCH', '/books/:id/fanfic', (m, b) => {
  const book: any = bookOf(m[1])
  if (!book.fanfic) throw new HttpErr(400, '这本书不是同人书')
  if (b.fidelity && !FF_FIDELITY[b.fidelity]) throw new HttpErr(422, 'fidelity 不合法')
  for (const k of ['fidelity', 'direction', 'extra_source_ids', 'notes']) if (b[k] !== undefined && b[k] !== null) book.fanfic[k] = b[k]
  return ffInfo(book)
})
on('DELETE', '/books/:id/fanfic', (m) => { const book: any = bookOf(m[1]); book.fanfic = null; return { ok: true } })
on('GET', '/books/:id/fanfic/context', (m) => {
  const book: any = bookOf(m[1]); const f = book.fanfic
  if (!f) return { book_id: book.id, text: '', chars: 0 }
  const s = ffSources.find((x) => x.id === f.source_id)
  const lines = [`【同人创作·原著设定】（原著：${f.source_title}；方向：${FF_DIRS.find((d) => d[0] === f.direction)?.[1]}；遵循度：${FF_FIDELITY[f.fidelity]?.label}）`, `遵循规则：${FF_FIDELITY[f.fidelity]?.desc}`]
  if (f.notes) lines.push(`作者补充：${f.notes}`)
  if (!s) lines.push('（原著资料已删除，只按规则把握）')
  else {
    lines.push('原著角色：', ...s.cards.characters.map((c: any) => `- ${c.name}（${c.role}）：${c.personality} 说话：${c.speech_style}${c.catchphrases.length ? ` 口癖：${c.catchphrases.join(' / ')}` : ''}`))
    if (f.fidelity !== 'loose') lines.push(`世界观：${s.cards.world.summary}`)
    if (f.fidelity === 'strict') lines.push('时间线（已发生，不得改写）：', ...s.cards.timeline.map((t: any) => `${t.order}. ${t.event}`))
    if (f.fidelity === 'moderate') lines.push('主线节点（支线与结局可改）：', ...s.cards.timeline.map((t: any) => `${t.order}. ${t.event}`))
  }
  const text = lines.join('\n')
  return { book_id: book.id, text, chars: text.length }
})
on('POST', '/books/:id/fanfic/import-cards', (m, b) => {
  const book: any = bookOf(m[1])
  if (!book.fanfic) throw new HttpErr(400, '这本书不是同人书')
  const s = ffOf(book.fanfic.source_id); const parts: string[] = b?.parts?.length ? b.parts : ['characters']
  snapBible(book.id, `导入原著设定前：${s.title}`)
  const cards: Card[] = []; let skipped = 0
  const add = (type: Card['type'], name: string, summary: string, data: Record<string, any>) => {
    if (db.cards.some((c) => c.book_id === book.id && c.name === name)) { skipped++; return }
    const c = normCard({ id: nid(), book_id: book.id, type, name, summary, data: { ...data, from_fanfic_source: s.id }, known_by: [], updated_at: now(), status: 'active', ref_enabled: true, soul: type === 'character' ? emptySoul() : null })
    db.cards.push(c); cards.push(c)
  }
  const roleOf = (r: string) => (r === '主角' ? 'protagonist' : r === '反派' ? 'antagonist' : 'ally')
  if (parts.includes('characters')) s.cards.characters.forEach((c: any) => add('character', c.name, c.personality, { role: roleOf(c.role), canon_role: c.role, voice: c.speech_style, catchphrases: c.catchphrases, abilities: c.abilities, limits: c.limits, relations: c.relations, aliases: c.aliases }))
  if (parts.includes('factions')) s.cards.factions.forEach((f: any) => add('faction', f.name, f.stance, { members: f.members, notes: f.notes }))
  if (parts.includes('world') && s.cards.world.summary) add('world', '原著世界观', s.cards.world.summary, { rules: s.cards.world.rules })
  if (parts.includes('locations')) s.cards.world.locations.forEach((l: any) => add('location', l.name, l.desc, {}))
  return { cards, skipped }
})
function ffBookOfChapter(id: string) {
  const ch = must(db.chapters.find((c) => c.id === +id), '章节')
  const book: any = bookOf(String(ch.book_id))
  return { ch, book }
}
function ffOverlap(content: string) {
  const h = parseInt(mhash(content).slice(0, 4), 16)
  const bare = content.replace(/[\s\p{P}]/gu, '')
  const hits = h % 4 === 0 ? 0 : (h % 37) + 3
  const ratio = bare.length ? +(hits * 8 / bare.length).toFixed(4) : 0
  const longest = hits ? 8 + (h % 18) : 0
  const level = !hits ? 'ok' : ratio < 0.01 && longest < 20 ? 'info' : ratio < 0.05 ? 'warn' : 'high'
  const samples = hits ? content.split(/[。！？\n]/).map((x) => x.trim()).filter((x) => x.length >= 8).slice(0, 3).map((x) => x.slice(0, 60)) : []
  return { ngram: 8, hits, segments: hits ? Math.ceil(hits / 3) : 0, longest, ratio, level, warning: level === 'warn' || level === 'high' ? `本章有 ${(ratio * 100).toFixed(1)}% 的内容与原著重合，建议改写成自己的话` : '', samples, content_hash: mhash(content), checked_at: now() }
}
on('POST', '/chapters/:id/ooc-check', (m) => {
  const { ch, book } = ffBookOfChapter(m[1])
  if (!book.fanfic) throw new HttpErr(400, '这本书不是同人书')
  const s = ffSources.find((x) => x.id === book.fanfic.source_id)
  if (!s) throw new HttpErr(400, '原著资料已删除，无法做 OOC 检查')
  if (!ch.content) throw new HttpErr(400, '这一章还没有正文')
  return createJob('fanfic_ooc', book.id, 3600, ['读取原著角色卡…', '逐角色比对言行、口癖、关系…', '程序复核：口癖刷屏、能力越界…'], () => {
    const content = ch.content ?? ''
    const f = FF_FIDELITY[book.fanfic.fidelity]
    let chars = s.cards.characters.filter((c: any) => [c.name, ...c.aliases].some((n: string) => n && content.includes(n)))
    if (!chars.length) chars = s.cards.characters.slice(0, 2)
    const sents = content.split(/(?<=[。！？])/).map((x) => x.trim()).filter((x) => x.length >= 6)
    const characters = chars.map((c: any, i: number) => {
      const issues = i === 0 ? [] : [
        { type: 'speech', type_label: '言行', severity: i === 1 ? 'mid' : 'high', quote: sents[i * 3] ?? sents[0] ?? '', problem: `${c.name}在原著里${c.speech_style || '说话克制'}，这里显得过于外放`, suggestion: '改成更符合人设的短句或反问', source: 'model' },
        ...(i === 1 ? [{ type: 'catchphrase', type_label: '口癖', severity: 'low', quote: sents[i * 3 + 1] ?? sents[0] ?? '', problem: `口癖「${c.catchphrases[0] ?? '…'}」本章出现过多`, suggestion: '保留一次即可', source: 'program' }] : []),
      ].filter((x) => x.quote)
      const score = Math.max(30, 92 - i * 14 - issues.length * 4)
      const level = score >= f.pass && !issues.some((x: any) => x.severity === 'high') ? 'pass' : score >= f.pass - 15 ? 'warn' : 'fail'
      return { name: c.name, score, model_score: score + 2, level, verdict: level === 'pass' ? '言行与原著一致' : '有偏离原著人设的地方', issues }
    })
    const overall = Math.round(characters.reduce((n: number, c: any) => n + c.score, 0) / Math.max(1, characters.length))
    const rank = { pass: 0, warn: 1, fail: 2 } as Record<string, number>
    const verdict = characters.reduce((v: string, c: any) => (rank[c.level] > rank[v] ? c.level : v), 'pass')
    const ooc = { fidelity: book.fanfic.fidelity, fidelity_label: f.label, pass_score: f.pass, overall, verdict, characters, summary: verdict === 'pass' ? '本章角色整体贴合原著。' : '个别角色说话方式偏离原著，按建议改写对应句子。', ignored_issues: book.fanfic.fidelity === 'strict' ? 0 : 1, content_hash: mhash(content), checked_at: now(), model: 'mock' }
    const overlap = ffOverlap(content)
    ffChapterMeta.set(ch.id, { ooc, overlap })
    return { chapter_id: ch.id, ooc, overlap }
  }, `chapter:${ch.id}`)
})
on('GET', '/chapters/:id/ooc', (m) => {
  const ch = must(db.chapters.find((c) => c.id === +m[1]), '章节')
  const meta = ffChapterMeta.get(ch.id) ?? {}
  const h = mhash(ch.content ?? '')
  return { chapter_id: ch.id, ooc: meta.ooc ? { ...meta.ooc, stale: meta.ooc.content_hash !== h } : null, overlap: meta.overlap ? { ...meta.overlap, stale: meta.overlap.content_hash !== h } : null }
})
on('POST', '/chapters/:id/fanfic-overlap', (m) => {
  const { ch, book } = ffBookOfChapter(m[1])
  if (!book.fanfic) throw new HttpErr(400, '这本书不是同人书')
  const overlap = ffOverlap(ch.content ?? '')
  ffChapterMeta.set(ch.id, { ...(ffChapterMeta.get(ch.id) ?? {}), overlap })
  return { chapter_id: ch.id, overlap }
})

// ---------------- v0.9.4：提交前修中等问题 / 数值一致性 / 补丁后重审 / 断点续跑（追加） ----------------
Object.assign(db.writing, { fix_mid_before_commit: true, auto_rereview: true })
const bookWritingOv = new Map<number, { fix_mid_before_commit: boolean | null; auto_rereview: boolean | null }>()
function bookWritingOut(bookId: number) {
  const g = { fix_mid_before_commit: (db.writing as any).fix_mid_before_commit !== false, auto_rereview: (db.writing as any).auto_rereview !== false }
  const ov = bookWritingOv.get(bookId) ?? { fix_mid_before_commit: null, auto_rereview: null }
  return { book_id: bookId, overrides: ov, global: g, effective: { fix_mid_before_commit: ov.fix_mid_before_commit ?? g.fix_mid_before_commit, auto_rereview: ov.auto_rereview ?? g.auto_rereview } }
}
on('GET', '/books/:id/writing-settings', (m) => bookWritingOut(bookOf(m[1]).id))
on('PUT', '/books/:id/writing-settings', (m, b) => {
  const id = bookOf(m[1]).id
  const ov = { ...(bookWritingOv.get(id) ?? { fix_mid_before_commit: null, auto_rereview: null }) }
  for (const k of ['fix_mid_before_commit', 'auto_rereview'] as const) {
    if (k in (b ?? {})) {
      if (b[k] !== null && typeof b[k] !== 'boolean') throw new HttpErr(422, `${k} 只能是 true / false / null`)
      ov[k] = b[k]
    }
  }
  bookWritingOv.set(id, ov)
  return bookWritingOut(id)
})

// 演示数据：第 2 章 数值冲突 + 复审通过 + 提交前定点修；第 3 章 复审仍有严重问题被标记
;(() => {
  const chs = db.chapters.filter((c) => c.book_id === 1).sort((a, b) => a.number - b.number)
  const firstPara = (c: Chapter, k = 0) => (c.content ?? '').split('\n').map((l) => l.trim()).filter(Boolean)[k] ?? ''
  const c2 = chs[1]
  if (c2?.review) {
    const q = firstPara(c2, 3) || firstPara(c2)
    const numeric = [
      { severity: 'mid' as const, dimension: 'continuity', quote: q, comment: '林野的年龄前后不一致：前面写「十七岁」，这里写「十八岁」，统一成一个数',
        position: { offset: Math.max(0, (c2.content ?? '').indexOf(q)), paragraph: 3, match: '十八岁' }, source: 'lint:numeric', object: '林野', kind: 'age',
        related: { quote: firstPara(c2, 1), offset: Math.max(0, (c2.content ?? '').indexOf(firstPara(c2, 1))), paragraph: 1 } },
      { severity: 'mid' as const, dimension: 'continuity', quote: firstPara(c2, 5) || q, comment: '林野的境界和事实账本对不上：账本记的是「炼气五层」，这里写成「炼气七层」，本章也没写突破',
        position: { offset: 0, paragraph: 5, match: '炼气七层' }, source: 'lint:numeric', object: '林野', kind: 'realm',
        related: { source: 'ledger', label: '事实账本·境界（第1章起）', value: '炼气五层' } },
    ]
    c2.review = {
      ...c2.review, issues: [...c2.review.issues, ...numeric],
      rereview: { round: 1, at: ago(30), before_overall: c2.review.scores.overall - 6, after_overall: c2.review.scores.overall, passed: true, high_left: 0, dropped_issues: 2 },
      flagged: false, flag_reason: '',
      pre_commit_fix: { issues: [1, c2.review.issues.length], patches_applied: [0], patches_skipped: [{ index: 2, reason: '原句在正文里找不到了' }], rewritten: 1, changed: true, at: ago(20) },
    }
    if (c2.lint) c2.lint = { ...c2.lint, numeric_conflicts: numeric, lint_tier: 'fanqie', warnings: [...c2.lint.warnings, ...numeric.map((n) => `数值不一致：${n.comment}`)] }
    ;(chHist[c2.id] ??= []).push({ content: c2.content ?? '', title: c2.title, label: '提交前修中等问题前' })
    Object.assign(c2, { history: chHist[c2.id].length, last_history_label: '提交前修中等问题前' })
  }
  const c3 = chs[2]
  if (c3?.review) {
    const q = firstPara(c3, 2)
    c3.review = {
      ...c3.review, passed: false, flagged: true, flag_reason: '补丁后复审仍有 1 条严重问题（节奏：一句话跳过好几天），章节未自动提交，请人工处理',
      rereview: { round: 1, at: ago(15), before_overall: c3.review.scores.overall - 2, after_overall: c3.review.scores.overall, passed: false, high_left: 1, dropped_issues: 1 },
      pre_commit_fix: null,
      patches: [
        { index: 0, original: q, improved: `${q.slice(0, 12)}……（上一轮建议）`, reason: '上一轮审稿的补丁', issue_ref: null, severity: 'mid', applied: true, round: 0 },
        { index: 1, original: firstPara(c3, 4), improved: '（上一轮建议，正文已变）', reason: '上一轮审稿的补丁', issue_ref: null, severity: 'low', applied: false, round: 0, stale: true },
        { index: 2, original: firstPara(c3, 6), improved: `${firstPara(c3, 6).slice(0, 10)}——他把账本合上，没再说话。`, reason: '复审：收尾留钩子', issue_ref: 0, severity: 'high', applied: false, round: 1 },
      ],
    }
  }
})()

// 一条服务重启后中断、可续跑的写章任务
;(() => {
  const ch = db.chapters.filter((c) => c.book_id === 1).sort((a, b) => b.number - a.number)[0]
  const steps = ['从断点继续：跳过已写好的场景…', '写作剩余场景…', '一致性检查…', '证据式审稿…']
  db.jobs.push({
    id: nid(), kind: 'chapter_write_next', status: 'interrupted', progress: 42, message: '服务重启，任务已中断（可续跑）', result: null, error: null, book_id: 1, ref: '',
    created_at: ago(40), updated_at: ago(35), resumable: true,
    checkpoint: { stage: 'scene:1:2/4', resumes: 0, updated_at: ago(35), chapter_id: null, number: (ch?.number ?? 0) + 1, scenes_total: 4, scenes_done: 2, variants_done: 0 },
    _start: 0, _dur: 6000, _steps: steps, _done: true, _fin: () => ({ chapter_id: writeOne(1, 1).id }),
  })
  // 一条不可续跑的（批量写章不存断点）
  db.jobs.push({
    id: nid(), kind: 'chapter_write_batch', status: 'failed', progress: 30, message: '服务重启，任务中断', result: null, error: '服务重启，批量写章暂不支持续跑', book_id: 1, ref: '',
    created_at: ago(90), updated_at: ago(88), resumable: false, checkpoint: null, _start: 0, _dur: 1, _steps: [], _done: true,
  })
})()
on('POST', '/jobs/:id/resume', (m) => {
  const j = must(db.jobs.find((x) => x.id === +m[1]), '任务')
  if (!(j.status === 'interrupted' || j.status === 'failed')) throw new HttpErr(409, `任务状态为 ${j.status}，不能续跑`)
  if (j.kind !== 'chapter_write_next' && !WANBEN_RESUMABLE.includes(j.kind)) throw new HttpErr(409, '这类任务暂不支持续跑')
  if (!j.checkpoint) throw new HttpErr(409, '没有断点，无法续跑')
  const stage = j.checkpoint.stage
  Object.assign(j, {
    status: 'queued', progress: j.progress, error: null, message: `从「${stage}」之后继续`, resumable: false, updated_at: now(),
    checkpoint: { ...j.checkpoint, resumes: j.checkpoint.resumes + 1, updated_at: now() },
    _start: Date.now(), _done: false,
  })
  return pub(j)
})

// ---------------- v0.11 完本模式 / 质检（mock，见 ./wanben.ts） ----------------
registerWanbenMocks({ on, db: db as any, createJob, HttpErr, must, bookOf, nid, now, ago, writeOne, mkReview, mkLint, countWords, chHist, recalc })
registerAutoMocks({ on, createJob, bookOf: bookOf as any, now, ago, HttpErr })


// ---------------- v0.12 生成档案 / 预算（mock） ----------------
type MGen = { id: number; book_id: number | null; job_id: number | null; kind: string; kind_label: string; task: string; route: string; model: string; status: 'ok' | 'empty' | 'failed'; error: string; output_words: number; target_words: number; short: boolean; in_tokens: number; out_tokens: number; cost_cny: number; ms: number; starred: boolean; parent_id: number | null; note: string; created_at: string; preview: string; prompt: string; output: string }
const GEN_LABEL: Record<string, string> = { chapter_write: '写章', chapter_review: '审稿', bible_generate: '生成设定', outline_generate: '生成大纲', humanize: '去 AI 味', image: '生图', generation_followup: '追问' }
const gens: MGen[] = []
const budget = { daily_cny: 0, book_cny: 0 }
;(() => {
  const sample = '雨落在青石板上，林川把剑往背后一收，抬头看了眼山门。'
  const kinds = ['chapter_write', 'chapter_review', 'bible_generate', 'outline_generate', 'humanize', 'image']
  for (let i = 0; i < 14; i++) {
    const k = kinds[i % kinds.length]; const failed = i === 3; const short = i === 6
    const out = failed ? '' : k === 'image' ? '（1 张图）' : sample.repeat(short ? 6 : 30)
    gens.push({ id: 9000 + i, book_id: 1, job_id: null, kind: k, kind_label: GEN_LABEL[k] ?? k, task: k, route: k === 'chapter_write' ? 'writer' : 'planner', model: 'DeepSeek/deepseek-chat',
      status: failed ? 'failed' : 'ok', error: failed ? '所有渠道均失败：DeepSeek/deepseek-chat：HTTP 429: rate limit' : '', output_words: countWords(out), target_words: k === 'chapter_write' ? 2200 : 0,
      short: false, in_tokens: 4200 + i * 300, out_tokens: failed ? 0 : 1800 + i * 90, cost_cny: failed ? 0 : +(0.004 + i * 0.0011).toFixed(4), ms: 22000 + i * 900,
      starred: i === 1, parent_id: null, note: '', created_at: ago(i * 47), preview: out.slice(0, 160), prompt: '按章纲写第 12 章：主角初入外门，被管事刁难。', output: out })
    const g = gens[gens.length - 1]; g.short = !!(g.target_words && g.status === 'ok' && g.output_words < g.target_words * 0.7)
  }
})()
const genPub = (g: MGen, full = false): Record<string, unknown> => { const { prompt, output, ...rest } = g; return full ? { ...rest, prompt, output, children: gens.filter((x) => x.parent_id === g.id).map((x) => genPub(x)) } : rest }
on('GET', '/generations', (_m, _b, u) => {
  const p = u.searchParams; const q = p.get('q') ?? ''
  let list = gens.filter((g) => (!p.get('book_id') || g.book_id === +p.get('book_id')!) && (!p.get('kind') || g.kind === p.get('kind')) && (!p.get('status') || g.status === p.get('status'))
    && (p.get('starred') !== 'true' || g.starred) && (!q || g.output.includes(q) || g.prompt.includes(q)))
  list = list.sort((a, b) => b.id - a.id)
  const off = +(p.get('offset') ?? 0); const lim = +(p.get('limit') ?? 50)
  const kinds = [...new Set(gens.map((g) => g.kind))].map((k) => ({ kind: k, label: GEN_LABEL[k] ?? k, count: gens.filter((g) => g.kind === k).length }))
  return { items: list.slice(off, off + lim).map((g) => genPub(g)), total: list.length, cost_cny: +list.reduce((n, g) => n + g.cost_cny, 0).toFixed(4), kinds }
})
on('GET', '/generations/:id', (m) => genPub(must(gens.find((g) => g.id === +m[1]), '记录'), true))
on('PATCH', '/generations/:id', (m, b) => { const g = must(gens.find((x) => x.id === +m[1]), '记录'); if (b?.starred !== undefined) g.starred = !!b.starred; return genPub(g) })
on('DELETE', '/generations/:id', (m) => { const i = gens.findIndex((g) => g.id === +m[1]); if (i >= 0) gens.splice(i, 1); return { ok: true } })
on('POST', '/generations/:id/followup', (m, b) => {
  const g = must(gens.find((x) => x.id === +m[1]), '记录')
  return createJob('generation_followup', g.book_id, 1500, ['按要求重新生成…'], () => {
    const out = `${g.output}\n\n（已按要求修改：${String(b?.instruction ?? '').slice(0, 60)}）`
    const n: MGen = { ...g, id: nid(), kind: 'generation_followup', kind_label: '追问', parent_id: g.id, note: String(b?.instruction ?? ''), starred: false, created_at: now(), output: out, preview: out.slice(0, 160), output_words: countWords(out), short: false }
    gens.push(n)
    return { parent_id: g.id, id: n.id, output: out }
  })
})
on('GET', '/settings/budget', (_m, _b, u) => {
  const bid = u.searchParams.get('book_id')
  const today = +gens.reduce((n, g) => n + g.cost_cny, 0).toFixed(4)
  return { ...budget, today_cny: today, ...(bid ? { book_spent_cny: +gens.filter((g) => g.book_id === +bid).reduce((n, g) => n + g.cost_cny, 0).toFixed(4) } : {}) }
})
on('PUT', '/settings/budget', (_m, b) => { budget.daily_cny = +b?.daily_cny || 0; budget.book_cny = +b?.book_cny || 0; return { ...budget, today_cny: +gens.reduce((n, g) => n + g.cost_cny, 0).toFixed(4) } })

// ---------------- v0.12 导入已有作品 / 接管（mock） ----------------
const importCache = new Map<string, { title: string; chapters: { index: number; raw_title: string; title: string; volume: string; words: number; flags: string[]; content: string }[] }>()
on('POST', '/books/import', (_m, b) => {
  const text = String(b?.__file_text ?? b?.text ?? '')
  if (!text.trim()) throw new HttpErr(400, '没有可用的正文')
  const lines = text.split(/\r?\n/)
  const chs: { index: number; raw_title: string; title: string; volume: string; words: number; flags: string[]; content: string }[] = []
  let vol = ''
  for (const l of lines) {
    if (/^\s*第[一二三四五六七八九十百千零\d]+[卷部]/.test(l)) { vol = l.trim(); continue }
    if (/^\s*第[一二三四五六七八九十百千零\d]+[章节回]/.test(l)) { chs.push({ index: chs.length + 1, raw_title: l.trim(), title: l.trim().replace(/^第\S+?[章节回]\s*/, '') || l.trim(), volume: vol, words: 0, flags: [], content: '' }); continue }
    const cur = chs[chs.length - 1]
    if (cur && l.trim()) { cur.content += (cur.content ? '\n\n' : '') + l.trim(); cur.words = countWords(cur.content) }
  }
  if (!chs.length) chs.push({ index: 1, raw_title: '第1章', title: '第1章', volume: '', words: countWords(text), flags: [], content: text.trim() })
  chs.forEach((c) => { if (!c.words) c.flags.push('空章'); else if (c.words < 300) c.flags.push('过短') })
  const id = Math.random().toString(16).slice(2, 14)
  const title = String(b?.__file_name || '').replace(/\.(txt|md|docx)$/i, '') || '导入的作品'
  importCache.set(id, { title, chapters: chs })
  const nFlag = chs.filter((c) => c.flags.length).length
  return { import_id: id, title, encoding: 'utf-8', total_words: chs.reduce((n, c) => n + c.words, 0), volumes: [...new Set(chs.map((c) => c.volume).filter(Boolean))],
    warnings: nFlag ? [`${nFlag} 章有疑点，导入前看一下`] : [], chapters: chs.map(({ content, ...c }) => ({ ...c, preview: content.slice(0, 80) })) }
})
on('POST', '/books/import/commit', (_m, b) => {
  const got = importCache.get(String(b?.import_id)); if (!got) throw new HttpErr(404, '导入预览已过期，重新上传一次')
  const skip = new Set<number>(b?.skip ?? [])
  const chs = got.chapters.filter((c) => !skip.has(c.index) && c.content.trim())
  if (!chs.length) throw new HttpErr(400, '没有可导入的章节')
  const book: Book = { id: nid(), title: b?.title || got.title, genre: b?.genre ?? '', gender: b?.gender ?? 'male', tagline: '', status: 'writing', target_words: 1_000_000, chapter_words: 2200, cover_url: null, created_at: now(), updated_at: now(), stats: { chapters: 0, words: 0, foreshadow_open: 0 }, approval_mode: 'review' }
  db.books.push(book)
  chs.forEach((c, i) => db.chapters.push({ id: nid(), book_id: book.id, number: i + 1, title: c.title, content: c.content, words: c.words, status: 'committed', review: null, lint: null, updated_at: now() } as unknown as Chapter))
  recalc(book.id); importCache.delete(String(b?.import_id))
  return { book_id: book.id, chapters: chs.length, words: chs.reduce((n, c) => n + c.words, 0) }
})
on('POST', '/books/:id/adopt', (m) => {
  const book = bookOf(m[1])
  return createJob('book_adopt', book.id, 3000, ['补摘要…', '从摘要反推设定和伏笔…', '写入设定卡和账本…', '按章节生成大纲…'], () => {
    if (!db.cards.some((c) => c.book_id === book.id && c.name === '林川')) db.cards.push(normCard({ id: nid(), book_id: book.id, type: 'character', name: '林川', summary: '主角，外门弟子，话少，记仇也记恩。', data: { role: 'protagonist' }, known_by: [], updated_at: now(), status: 'active', ref_enabled: true, soul: null }))
    return { summaries: db.chapters.filter((c) => c.book_id === book.id).length, cards: 1, facts: 1, foreshadows: 1, outline_nodes: 0, skipped_cards: [] }
  })
})
on('GET', '/books/:id/adopt', (m) => { const book = bookOf(m[1]); const n = db.chapters.filter((c) => c.book_id === book.id).length; return { chapters: n, summaries: n, cards: db.cards.filter((c) => c.book_id === book.id).length, foreshadows: 0, outline_linked: 0 } })


// ---------------- v0.13 章节工具 / 笔记 / 抽卡立项 / 上下文（mock） ----------------
on('POST', '/chapters/:id/titles', (m) => {
  const ch = must(db.chapters.find((c) => c.id === +m[1]), '章节')
  return createJob('chapter_titles', ch.book_id, 1200, ['起章名…'], () => ({ chapter_id: ch.id, number: ch.number, current: ch.title,
    titles: ['账本上的血手印', '一拳砸穿演武台', `第${ch.number}个跪下的人`, '管事的脸色变了', '风云再起', '三息之内', '他把门槛踩碎了']
      .map((t, i) => ({ title: t, reason: '有画面，有冲突', score: t === '风云再起' ? 35 : 92 - i * 4, notes: t === '风云再起' ? ['套话'] : [] })).sort((a, b) => b.score - a.score) }), `chapter:${ch.id}`)
})
on('POST', '/books/:id/sparks', (m, b) => {
  const book = bookOf(m[1])
  const ideas = [['拍卖会上反向竞价', '主角故意抬价，让反派花光家底买下假货。', '反派当众吃哑巴亏', '下一章'], ['师姐的赌约', '师姐押上全部资源赌主角输，主角赢了反手把赌注还她一半。', '打脸 + 收人心', '本卷高潮'],
    ['残卷认主', '残卷突然发热，指向宗门禁地。', '揭秘新能力', '支线'], ['外门大比的黑箱', '主角发现大比名单被调包，当场点破。', '众人震惊', '下一章'], ['老对手求和', '被打服的管事带着情报上门。', '势力反转', '支线']]
  return createJob('sparks', book.id, 1200, ['抽脑洞…'], () => ({ book_id: book.id, sparks: ideas.slice(0, b?.n ?? 5).map(([title, beat, payoff, fit]) => ({ title, beat, payoff, fit })) }))
})
on('POST', '/chapters/:id/reader-comments', (m) => {
  const ch = must(db.chapters.find((c) => c.id === +m[1]), '章节')
  const sents = (ch.content ?? '').split(/(?<=[。！？])/).map((x) => x.trim()).filter((x) => x.length >= 6)
  const pick = (k: number) => sents[k % Math.max(1, sents.length)] ?? ''
  const ps = ['老书虫', '通勤党', '爽点猎人', '段子手']
  const texts = ['这里有点意思', '主角终于支棱起来了！', '催更催更', '这个反派活不过三章', '前面有点拖，跳了']
  const moods = ['猜', '爽', '急', '笑', '烦']
  return createJob('reader_comments', ch.book_id, 1500, ['四位读者在刷…'], () => {
    const comments = ps.flatMap((p, i) => [0, 1].map((j) => { const q = pick(i * 3 + j); const off = (ch.content ?? '').indexOf(q); return { persona: p, quote: q, text: texts[(i + j) % 5], mood: moods[(i + j) % 5], offset: off, paragraph: 0 } })).filter((c) => c.offset >= 0).sort((a, b) => a.offset - b.offset)
    const drop = pick(5)
    return { chapter_id: ch.id, number: ch.number, comments, dropped: 1, continue_rate: 0.75,
      verdicts: ps.map((p, i) => ({ persona: p, will_continue: i !== 1, drop: i === 1 ? drop : '', drop_offset: i === 1 ? (ch.content ?? '').indexOf(drop) : null, why: i === 1 ? '这段太慢' : '' })),
      instruction: `按读者段评修改：\n- 「${drop.slice(0, 40)}」这里通勤党想划走：这段太慢` }
  }, `chapter:${ch.id}`)
})
const mockFreq = (text: string, names: string[]) => {
  const cnt = new Map<string, number>()
  for (const run of text.match(/[\u4e00-\u9fff]{2,}/g) ?? []) for (let n = 2; n <= 3; n++) for (let i = 0; i + n <= run.length; i++) { const g = run.slice(i, i + n); if (/^[的了是在我你他她这那就也]|[的了是在我你他她这那就也]$/.test(g) || names.some((x) => x.includes(g) || g.includes(x))) continue; cnt.set(g, (cnt.get(g) ?? 0) + 1) }
  const total = Math.max(1, text.length)
  return [...cnt.entries()].filter(([, c]) => c >= 3).sort((a, b) => b[1] - a[1]).slice(0, 40).map(([word, count]) => ({ word, count, per_10k: Math.round(count * 100000 / total) / 10 }))
}
on('GET', '/chapters/:id/freq', (m) => { const ch = must(db.chapters.find((c) => c.id === +m[1]), '章节'); return { chapter_id: ch.id, items: mockFreq(ch.content ?? '', db.cards.filter((c) => c.book_id === ch.book_id).map((c) => c.name)) } })
on('GET', '/books/:id/freq', (m, _b, u) => {
  const book = bookOf(m[1]); const a = +(u.searchParams.get('start') ?? 0), z = +(u.searchParams.get('end') ?? 0)
  const chs = db.chapters.filter((c) => c.book_id === book.id && (!a || c.number >= a) && (!z || c.number <= z))
  return { book_id: book.id, chapters: chs.length, items: mockFreq(chs.map((c) => c.content ?? '').join('\n'), db.cards.filter((c) => c.book_id === book.id).map((c) => c.name)) }
})
on('POST', '/format', (_m, b) => {
  const t = String(b?.text ?? '')
  const out = t.replace(/\r\n/g, '\n').split('\n').map((p) => p.trim().replace(/\.{3,}|。{3,}/g, '……')).filter(Boolean).join('\n\n')
  return { text: out, changed: out !== t, notes: out !== t ? ['段落间距已统一'] : [] }
})
const notes: { id: number; book_id: number; folder: string; title: string; content: string; tags: string[]; pinned: boolean; source: any; created_at: string; updated_at: string }[] = [
  { id: 8801, book_id: 1, folder: '人物', title: '林野的底线', content: '不碰毒品，不卖人。被逼到绝路也不改。', tags: ['人设'], pinned: true, source: null, created_at: ago(300), updated_at: ago(300) },
  { id: 8802, book_id: 1, folder: '伏笔', title: '冷库里的第二把钥匙', content: '第 3 章出现，第 12 章揭晓是前任店长留下的。', tags: [], pinned: false, source: null, created_at: ago(200), updated_at: ago(120) },
]
on('GET', '/books/:id/notes', (m, _b, u) => { const q = (u.searchParams.get('q') ?? '').toLowerCase(); return notes.filter((n) => n.book_id === +m[1] && (!q || (n.title + n.content).toLowerCase().includes(q))).sort((a, b) => +b.pinned - +a.pinned || b.updated_at.localeCompare(a.updated_at)) })
on('POST', '/books/:id/notes/import', (m, b) => {
  const parts = String(b?.text ?? '').split(/^###?\s+/m).filter((x) => x.trim())
  parts.forEach((p) => { const [t, ...rest] = p.split('\n'); notes.push({ id: nid(), book_id: +m[1], folder: b?.folder ?? '', title: t.trim().slice(0, 80), content: rest.join('\n').trim(), tags: [], pinned: false, source: null, created_at: now(), updated_at: now() }) })
  return { created: parts.length }
})
on('POST', '/books/:id/notes/from-spark', (m, b) => { const n = { id: nid(), book_id: +m[1], folder: '脑洞', title: b?.title ?? '脑洞', content: `${b?.beat ?? ''}\n\n爽点：${b?.payoff ?? ''}`, tags: [], pinned: false, source: { kind: 'spark' }, created_at: now(), updated_at: now() }; notes.push(n); return n })
on('POST', '/books/:id/notes', (m, b) => { const n = { id: nid(), book_id: +m[1], folder: b?.folder ?? '', title: b?.title || '未命名笔记', content: b?.content ?? '', tags: b?.tags ?? [], pinned: !!b?.pinned, source: b?.source ?? null, created_at: now(), updated_at: now() }; notes.push(n); return n })
on('PUT', '/books/:id/notes/:nid', (m, b) => { const n = must(notes.find((x) => x.id === +m[2] && x.book_id === +m[1]), '笔记'); Object.assign(n, b ?? {}, { updated_at: now() }); return n })
on('DELETE', '/books/:id/notes/:nid', (m) => { const i = notes.findIndex((x) => x.id === +m[2]); if (i >= 0) notes.splice(i, 1); return { ok: true } })
on('GET', '/books/:id/search', (m, _b, u) => {
  const book = bookOf(m[1]); const q = u.searchParams.get('q') ?? ''; const regex = u.searchParams.get('regex') === 'true'
  const scopes = (u.searchParams.get('scope') ?? 'chapters').split(',')
  let re: RegExp
  try { re = new RegExp(regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g') } catch { throw new HttpErr(422, '正则写得不对') }
  const hits: any[] = []; const by: Record<string, number> = {}
  const scan = (scope: string, id: number, field: string, label: string, text: string, locked = false) => { for (const mm of text.matchAll(re)) { if (!mm[0]) continue; by[scope] = (by[scope] ?? 0) + 1; hits.push({ scope, id, field, label, offset: mm.index ?? 0, before: text.slice(Math.max(0, (mm.index ?? 0) - 24), mm.index), match: mm[0], after: text.slice((mm.index ?? 0) + mm[0].length, (mm.index ?? 0) + mm[0].length + 24), locked, chapter_id: scope === 'chapters' ? id : null }) } }
  if (scopes.includes('chapters')) db.chapters.filter((c) => c.book_id === book.id).forEach((c) => { scan('chapters', c.id, 'title', `第${c.number}章 章名`, c.title); scan('chapters', c.id, 'content', `第${c.number}章 ${c.title}`, c.content ?? '') })
  if (scopes.includes('cards')) db.cards.filter((c) => c.book_id === book.id).forEach((c) => scan('cards', c.id, 'summary', `设定·${c.name}`, c.summary, !!(c as any).locked))
  if (scopes.includes('outline')) db.outline.filter((o) => o.book_id === book.id).forEach((o) => scan('outline', o.id, 'summary', `大纲·${o.title}`, o.summary ?? '', !!(o as any).locked))
  if (scopes.includes('notes')) notes.filter((n) => n.book_id === book.id).forEach((n) => scan('notes', n.id, 'content', `笔记·${n.title}`, n.content))
  return { q, regex, total: hits.length, by_scope: by, hits: hits.slice(0, 500), truncated: hits.length > 500 }
})
on('POST', '/books/:id/replace', (m, b) => {
  const book = bookOf(m[1]); const q = String(b?.q ?? ''); const rep = String(b?.replacement ?? '')
  const re = new RegExp(b?.regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')
  let n = 0; const changed: Record<string, number> = {}
  const sub = (scope: string, t: string) => { const out = t.replace(re, () => { n++; return rep }); if (out !== t) changed[scope] = (changed[scope] ?? 0) + 1; return out }
  if ((b?.scopes ?? ['chapters']).includes('chapters')) db.chapters.filter((c) => c.book_id === book.id).forEach((c) => { c.content = sub('chapters', c.content ?? ''); c.title = sub('chapters', c.title) })
  if ((b?.scopes ?? []).includes('cards')) db.cards.filter((c) => c.book_id === book.id && !(c as any).locked).forEach((c) => { c.summary = sub('cards', c.summary) })
  if ((b?.scopes ?? []).includes('notes')) notes.filter((x) => x.book_id === book.id).forEach((x) => { x.content = sub('notes', x.content) })
  return { replaced: n, changed, skipped_locked: [] }
})
const ctxExclude = new Map<number, string[]>()
on('GET', '/books/:id/context-preview', (m) => {
  const book = bookOf(m[1]); const ex = ctxExclude.get(book.id) ?? []
  const blocks = [['本章相关设定', 1800], ['人物当前状态', 600], ['相关旧章回读', 1200], ['最近章节摘要', 1500], ['上一章结尾原文', 600], ['未回收伏笔', 400], ['本章写作任务', 900], ['后两章章纲', 500]] as [string, number][]
  const out = blocks.map(([label, chars]) => ({ label, chars, excluded: ex.includes(label), pinned: label === '本章写作任务' }))
  return { chapter: 7, fixed_chars: 4200, blocks: out, total_chars: 4200 + out.filter((x) => !x.excluded).reduce((a, x) => a + x.chars, 0), exclude: ex }
})
on('PUT', '/books/:id/context-exclude', (m, b) => { const blocks = (b?.blocks ?? []).filter((x: string) => x !== '本章写作任务'); ctxExclude.set(bookOf(m[1]).id, blocks); return { blocks } })
on('GET', '/chapters/:id/aigc/report', () => '<html></html>')
on('POST', '/books/:id/fanfic/oc/generate', (m) => {
  const book = bookOf(m[1])
  return createJob('fanfic_oc', book.id, 1500, ['设计原创主角…'], () => {
    const name = (book.fanfic as any)?.protagonist?.name || '沈渡'
    if (!db.cards.some((c) => c.book_id === book.id && c.name === name)) db.cards.push(normCard({ id: nid(), book_id: book.id, type: 'character', name, summary: '从现代穿来的外卖骑手，熟读原著，嘴硬手快。', data: { role: 'protagonist', origin: 'oc' }, known_by: [name], updated_at: now(), status: 'active', ref_enabled: true, soul: null }))
    return { card_id: 0, name, summary: '从现代穿来的外卖骑手，熟读原著，嘴硬手快。', data: {}, ai_filled: ['identity', 'growth'] }
  })
})
// 抽卡立项
const sparkSessions: any[] = []
const SPARK_POOL: Record<string, string[]> = {
  world: ['灵气复苏的末法城市', '被天道标价的修仙界', '九州共用一本账簿的王朝', '每天重置一次的宗门', '以寿命为货币的江湖', '妖族统治的人间', '神明打工的天庭', '考试决定一切的武道世界', '海底城邦的修真文明', '被封印的上古战场'],
  hero: ['被退婚的外门杂役', '天生废脉的世家庶子', '替人坐牢十年的狱卒', '装傻的皇子', '穷到吃土的符师', '送葬队的抬棺人', '失忆的前任剑尊', '被逐出师门的丹童', '背锅的宗门账房', '镇守荒村的老兵之子'],
  cheat: ['能看见别人功法破绽的残卷', '每杀一敌返还一次修为', '可以抽取仇人气运的铜钱', '能和死人对话的灯', '复制他人一招的玉简', '把伤害转成经验的体质', '每天签到送一件法宝', '预知三息后战局的眼睛', '能收服妖兽的笛子', '一页会自己续写的功法'],
}
on('GET', '/spark/tracks', (_m, _b, u) => {
  const g = u.searchParams.get('gender') === 'female' ? 'female' : 'male'
  const list = g === 'male' ? [['玄幻', ['高武', '东方玄幻', '异世大陆']], ['都市', ['都市高武', '神医', '异能']], ['仙侠', ['修真', '洪荒']], ['历史', ['架空', '争霸']], ['科幻', ['末世', '星际']], ['悬疑', ['灵异', '规则怪谈']]]
    : [['古言', ['宫斗', '宅斗', '种田']], ['现言', ['豪门', '甜宠']], ['玄幻言情', ['修仙', '快穿']], ['年代', ['七零', '八零']]]
  return { gender: g, tracks: (list as [string, string[]][]).map(([track, subs], i) => ({ track, heat: Math.round((92 - i * 9) * 10) / 10, rising: 5 - i, subs, sample_titles: i < 2 ? ['开局签到荒古圣体', '我在末世开超市'] : [], from_rank: i < 3 })),
    tag_groups: g === 'male' ? ['系统', '重生', '无敌', '扮猪吃虎', '打脸', '签到', '热血', '种田'] : ['甜宠', '大女主', '双强', '穿书', '重生', '团宠', '马甲', '追妻'] }
})
on('GET', '/spark/sessions', () => sparkSessions.map((x) => ({ id: x.id, track: x.track, gender: x.gender, idea_id: x.idea_id, title: x.proposal?.title ?? null, updated_at: now() })))
on('POST', '/spark/sessions', (_m, b) => {
  if (!b?.track) throw new HttpErr(422, '请选择赛道')
  const x = { id: nid(), idea_id: null, gender: b.gender ?? 'male', track: b.track, sub: b.sub ?? '', tags: b.tags ?? [], inspiration: b.inspiration ?? {}, cards: { world: [], hero: [], cheat: [] }, keep: { world: [], hero: [], cheat: [] }, picks: {}, rounds: { world: 0, hero: 0, cheat: 0 }, proposal: null }
  sparkSessions.push(x); return x
})
on('GET', '/spark/sessions/:id', (m) => must(sparkSessions.find((x) => x.id === +m[1]), '抽卡会话'))
on('POST', '/spark/sessions/:id/draw', (m, b) => {
  const x = must(sparkSessions.find((y) => y.id === +m[1]), '抽卡会话'); const axis = b?.axis as 'world' | 'hero' | 'cheat'
  return createJob('spark_draw', null, 1400, ['抽卡…'], () => {
    const kept = (x.cards[axis] ?? []).filter((c: any) => (b?.keep ?? []).includes(c.id))
    const pool = SPARK_POOL[axis].filter((t) => !kept.some((k: any) => k.title === t))
    const off = (x.rounds[axis] * 3) % pool.length
    const fresh = [...pool.slice(off), ...pool.slice(0, off)].slice(0, 9 - kept.length).map((t, i) => ({ id: Math.random().toString(16).slice(2, 10), title: t, desc: `${x.track}向：${t}，开局就有冲突，后期能撑起长线。`, tags: [x.track, '爽文'], heat: 88.5, similarity: (i * 13) % 55, similar_to: i % 4 === 3 ? '开局签到荒古圣体' : '', trope_hits: i === 5 ? ['退婚流'] : [] }))
    x.cards[axis] = [...kept, ...fresh]; x.keep[axis] = kept.map((k: any) => k.id); x.rounds[axis] += 1
    return x
  }, `spark:${x.id}`)
})
on('POST', '/spark/sessions/:id/pick', (m, b) => {
  const x = must(sparkSessions.find((y) => y.id === +m[1]), '抽卡会话')
  x.picks[b.axis] = b?.custom?.title ? { id: 'custom', title: b.custom.title, desc: b.custom.desc ?? '', tags: [], heat: null, similarity: 0, similar_to: '', trope_hits: [] } : (x.cards[b.axis] ?? []).find((c: any) => c.id === b.card_id) ?? null
  return x
})
on('POST', '/spark/sessions/:id/proposal', (m) => {
  const x = must(sparkSessions.find((y) => y.id === +m[1]), '抽卡会话')
  if (!x.picks.world || !x.picks.hero || !x.picks.cheat) throw new HttpErr(409, '世界观、主角、金手指都要选')
  return createJob('spark_proposal', null, 1800, ['写立项书…'], () => {
    const titles = ['退婚当天，我觉醒了万倍返还', '开局签到十年修为', '我在宗门当账房，全宗都欠我钱', '废脉少年一拳破天', '三息之后，你已经输了', '被逐出师门后我成了丹神', '杂役？我是来收债的', '残卷一出，天下无敌', '全城都在等我出手'].map((t, i) => ({ title: t, score: 100 - i * 8 }))
    x.proposal = { title: titles[0].title, titles, tagline: `${x.picks.hero.title}得到${x.picks.cheat.title}，在${x.picks.world.title}里一路打穿。`, logline: '一句话梗概', hook: '第一章当众打脸退婚的世家', endgame: '登顶九州', style: '短句快节奏，每章一个爽点', conflict: '世家与宗门联手打压主角',
      selling_points: ['开局打脸', '金手指有成长线', '反派层层升级'], expectations: ['揭开残卷来历'], arc: ['外门崛起', '内门争锋', '九州大比', '上界清算'], power: { name: '九境', levels: ['淬体', '通脉', '凝元', '化神', '合道'] },
      seed_cards: [{ type: 'world', name: x.picks.world.title.slice(0, 12), summary: x.picks.world.title, data: {} }, { type: 'cheat', name: x.picks.cheat.title.slice(0, 12), summary: x.picks.cheat.title, data: { input: '盯住对手', limit: '一天三次', growth: '境界越高看得越深' } }, { type: 'character', name: '林川', summary: x.picks.hero.title, data: { role: 'protagonist' } }], completeness: 100 }
    return x
  }, `spark:${x.id}`)
})
on('PATCH', '/spark/sessions/:id/proposal', (m, b) => { const x = must(sparkSessions.find((y) => y.id === +m[1]), '抽卡会话'); x.proposal = { ...x.proposal, ...(b ?? {}) }; return x })
on('POST', '/spark/sessions/:id/adopt', (m) => {
  const x = must(sparkSessions.find((y) => y.id === +m[1]), '抽卡会话')
  if (x.idea_id) return { idea_id: x.idea_id }
  const idea: any = { id: nid(), book_id: null, title: x.proposal.title, logline: x.proposal.logline, selling_points: x.proposal.selling_points, hook: x.proposal.hook, genre: x.track, gender: x.gender, scores: null, chosen: false, source: { kind: 'spark', seed_cards: x.proposal.seed_cards } }
  db.ideas.unshift(idea); x.idea_id = idea.id
  return { idea_id: idea.id }
})

// v0.20 技能库 & 外部 Agent 动态 mock
const mockSkills: any[] = [
  { id: 9101, slug: 'builtin-rule-writing', name: '正文写作核心规则', description: 'NovelOS 内置「正文写作」核心规则包，可自由修改或重置。', stage: 'writing', source: 'builtin', source_url: 'builtin/rules/writing.md', license: 'Apache-2.0', enabled: true, is_default: true, body: '# 正文写作规则\n短段快节奏，三百字内见冲突，章末留钩子。', references: [], chars: 32, ref_count: 0, created_at: ago(300), updated_at: ago(300) },
  { id: 9102, slug: 'curated-golden-opening', name: '黄金三章开篇技法', description: '前三行入局、主角当场行动、金手指露苗头与首次小胜结算。', stage: 'writing', source: 'builtin', source_url: 'curated/webnovel-golden-opening', license: 'MIT', enabled: true, is_default: false, body: '# 黄金三章开篇技法\n第 1 章前三行入局，第 3 章完成首次收益结算。', references: [], chars: 36, ref_count: 0, created_at: ago(300), updated_at: ago(300) },
]
const mockBookSkills = new Map<number, { custom: boolean; ids: number[] }>()
const mockSkillStages = [
  { key: 'writing', label: '正文写作' }, { key: 'outline', label: '大纲规划' }, { key: 'chapter_plan', label: '章细纲' },
  { key: 'bible', label: '设定库' }, { key: 'ideation', label: '选题立项' }, { key: 'review', label: '审稿把关' },
  { key: 'humanize', label: '去 AI 味' }, { key: 'teardown', label: '拆书分析' }, { key: 'package', label: '包装简介' },
  { key: 'trend_report', label: '风向标' }, { key: 'general', label: '通用方法' },
]
on('GET', '/skills', (_m, _b, u) => {
  const st = u.searchParams.get('stage')
  const q = (u.searchParams.get('q') ?? '').toLowerCase()
  const items = mockSkills.filter((x) => (!st || x.stage === st) && (!q || `${x.name} ${x.description} ${x.body}`.toLowerCase().includes(q)))
  return { stages: mockSkillStages, items }
})
on('GET', '/skills/:id', (m) => must(mockSkills.find((x) => x.id === +m[1]), '技能'))
on('POST', '/skills', (_m, b) => {
  const sk = { id: nid(), slug: `custom-${Date.now()}`, name: b?.name || '新建技能', description: b?.description || '', stage: b?.stage || 'writing', source: 'custom', source_url: '', license: 'custom', enabled: b?.enabled ?? true, is_default: !!b?.is_default, body: b?.body || '', references: b?.references || [], chars: (b?.body || '').length, ref_count: 0, created_at: now(), updated_at: now() }
  mockSkills.push(sk); return sk
})
on('PUT', '/skills/:id', (m, b) => {
  const sk = must(mockSkills.find((x) => x.id === +m[1]), '技能')
  Object.assign(sk, b ?? {}, { updated_at: now() }); sk.chars = (sk.body || '').length; return sk
})
on('POST', '/skills/:id/duplicate', (m) => {
  const src = must(mockSkills.find((x) => x.id === +m[1]), '技能')
  const copy = { ...src, id: nid(), slug: `${src.slug}-copy`, name: `${src.name} (副本)`, source: 'custom', is_default: false, created_at: now(), updated_at: now() }
  mockSkills.push(copy); return copy
})
on('POST', '/skills/:id/reset', (m) => must(mockSkills.find((x) => x.id === +m[1]), '技能'))
on('DELETE', '/skills/:id', (m) => {
  const i = mockSkills.findIndex((x) => x.id === +m[1]); if (i >= 0) mockSkills.splice(i, 1); return { ok: true }
})
on('POST', '/skills/import-github', (_m, b) => {
  const sk = { id: nid(), slug: `gh-${Date.now()}`, name: 'GitHub 导入技能', description: '模拟导入', stage: b?.stage || 'writing', source: 'github', source_url: b?.url || '', license: 'MIT', enabled: true, is_default: false, body: '# 导入的技能\n示例正文', references: [], chars: 14, ref_count: 0, created_at: now(), updated_at: now() }
  mockSkills.push(sk); return sk
})
on('GET', '/books/:id/skills', (m) => {
  const bid = bookOf(m[1]).id
  const rec = mockBookSkills.get(bid)
  const ids = rec ? rec.ids : mockSkills.filter((x) => x.enabled && x.is_default).map((x) => x.id)
  const active = mockSkills.filter((x) => ids.includes(x.id) && x.enabled && (x.stage === 'writing' || x.stage === 'general'))
  return { book_id: bid, customized: !!rec?.custom, selected_ids: ids, writing_chars: active.reduce((a, x) => a + x.chars, 0), items: mockSkills }
})
on('PUT', '/books/:id/skills', (m, b) => {
  const bid = bookOf(m[1]).id
  const ids: number[] = Array.isArray(b?.skill_ids) ? b.skill_ids : []
  mockBookSkills.set(bid, { custom: true, ids })
  const active = mockSkills.filter((x) => ids.includes(x.id) && x.enabled && (x.stage === 'writing' || x.stage === 'general'))
  return { book_id: bid, customized: true, selected_ids: ids, writing_chars: active.reduce((a, x) => a + x.chars, 0), items: mockSkills }
})
on('GET', '/books/:id/agent-activity', (m) => [
  { id: 1, book_id: +m[1], tool: 'save_chapter', summary: '保存第 6 章（含摘要与状态入账）', ok: true, duration_ms: 42, created_at: ago(8) },
  { id: 2, book_id: +m[1], tool: 'chapter_brief', summary: '读取第 7 章写作简报', ok: true, duration_ms: 19, created_at: ago(2) },
])
on('POST', '/books/:id/chapters/write-stream', (m) => {
  const bid = bookOf(m[1]).id
  const chs = db.chapters.filter((c) => c.book_id === bid)
  const num = (chs.reduce((mx, c) => Math.max(mx, c.number), 0) || 0) + 1
  const title = `第${num}章 模拟流式新章`
  const content = buildChapterText(num - 1)
  const id = nid()
  const ch: Chapter = {
    id, book_id: bid, number: num, title, content, words: countWords(content),
    status: 'committed', review: null, lint: mkLint(content), updated_at: now(),
  }
  db.chapters.push(ch)
  recalc(bid)
  const enc = new TextEncoder()
  const stream = new ReadableStream({
    start(ctrl) {
      const send = (ev: string, data: any) => ctrl.enqueue(enc.encode(`event: ${ev}\ndata: ${JSON.stringify({ type: ev, ...data })}\n\n`))
      send('start', { number: num, title, target_words: 2200 })
      const step = 40
      for (let i = 0; i < content.length; i += step) send('delta', { text: content.slice(i, i + step) })
      send('done', { chapter_id: id, number: num, title, words: ch.words, committed: true, status: 'committed' })
      ctrl.close()
    },
  })
  return new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
})
