/**
 * v0.11 完本模式 / 整书体检 / 可改编度 / 短剧自查 / 同质化 的前端 mock（VITE_USE_MOCK=1）。
 * 由 mocks/index.ts 在注册完基础路由后调用 registerWanbenMocks(ctx)，复用它的内存库与任务模拟。
 */
import type { Book, Chapter, Job, Lint, RankItem, Review } from '@/lib/types'

type H = (m: RegExpMatchArray, body: any, url: URL) => any
type MJob = Job & { _start: number; _dur: number; _steps: string[]; _fin?: () => Record<string, any> | null; _done?: boolean }
export interface MockCtx {
  on: (method: string, path: string, h: H) => void
  db: { books: Book[]; chapters: Chapter[]; outline: any[]; foreshadows: any[]; items: RankItem[]; ideas: any[]; jobs: MJob[]; cards: any[] }
  createJob: (kind: string, bookId: number | null, dur: number, steps: string[], fin: () => Record<string, any> | null, ref?: string) => Job
  HttpErr: new (status: number, detail: string) => any
  must: <T>(v: T | undefined, what?: string) => T
  bookOf: (id: string) => Book
  nid: () => number
  now: () => string
  ago: (min: number) => string
  writeOne: (bookId: number, variants: number) => Chapter
  mkReview: (seed: number, content: string) => Review
  mkLint: (content: string) => Lint
  countWords: (s: string) => number
  chHist: Record<number, { content: string; title: string; label: string }[]>
  recalc: (bookId: number) => void
}

const READER_PASS = 6
const DEFAULTS = { target_words: 200_000, chapter_words: 2000, batch_size: 10, refine_scope: 'first_n', golden_chapters: 10, refine_ranges: [] as [number, number][], pause_on_unapproved_refine: true, auto_continue: false }

function normRanges(raw: any[]): [number, number][] {
  const items: [number, number][] = []
  for (const it of raw ?? []) {
    let a: number | undefined, b: number | undefined
    if (Array.isArray(it) && it.length) { a = +it[0]; b = +it[it.length - 1] } else if (typeof it === 'number') { a = b = it } else if (typeof it === 'string') {
      const m = /^\s*(\d+)\s*(?:[-–~～至到]\s*(\d+))?\s*$/.exec(it); if (m) { a = +m[1]; b = +(m[2] ?? m[1]) }
    }
    if (!a || !b || isNaN(a) || isNaN(b)) continue
    if (a > b) [a, b] = [b, a]
    items.push([Math.max(1, a), b])
  }
  items.sort((x, y) => x[0] - y[0])
  const out: [number, number][] = []
  for (const [a, b] of items) { const l = out[out.length - 1]; if (l && a <= l[1] + 1) l[1] = Math.max(l[1], b); else out.push([a, b]) }
  return out
}

export function registerWanbenMocks(c: MockCtx) {
  const { on, db, createJob, HttpErr, must, bookOf, nid, now, ago } = c
  const st = new Map<number, typeof DEFAULTS & { mode: 'serial' | 'wanben' }>()
  const plans = new Map<number, { planned_at: string; total: number; ending: string; volumes: any[] }>()
  const batches: any[] = []
  const iterations: any[] = []
  const paused = new Map<number, boolean>()
  const iterStop = new Map<number, boolean>()
  const readerScore = new Map<number, number>() // chapter id → 读者分

  const S = (bookId: number) => {
    if (!st.has(bookId)) st.set(bookId, { ...DEFAULTS, refine_ranges: [], mode: 'serial' })
    return st.get(bookId)!
  }
  const chs = (bookId: number) => db.chapters.filter((x) => x.book_id === bookId).sort((a, b) => a.number - b.number)
  const totalOf = (bookId: number) => {
    const s = S(bookId)
    const t = Math.max(1, Math.ceil(s.target_words / Math.max(1, s.chapter_words)))
    return Math.max(t, plans.get(bookId)?.total ?? 0)
  }
  const writtenMax = (bookId: number) => chs(bookId).reduce((m, x) => Math.max(m, x.number), 0)
  const refineNums = (bookId: number) => {
    const s = S(bookId)
    const upto = Math.max(totalOf(bookId), writtenMax(bookId))
    if (s.refine_scope === 'none') return []
    if (s.refine_scope === 'all') return Array.from({ length: upto }, (_, i) => i + 1)
    if (s.refine_scope === 'custom') return [...new Set(normRanges(s.refine_ranges).flatMap(([a, b]) => Array.from({ length: b - a + 1 }, (_, k) => a + k)))].sort((a, b) => a - b)
    return Array.from({ length: Math.max(0, s.golden_chapters) }, (_, i) => i + 1)
  }
  const reader = (ch: Chapter) => {
    if (!readerScore.has(ch.id)) readerScore.set(ch.id, [7, 5, 8, 6, 7, 4, 8, 7, 6, 5][ch.number % 10])
    return readerScore.get(ch.id)!
  }
  const planSummary = (bookId: number) => {
    const p = plans.get(bookId)
    return { planned: !!p, total_chapters: p?.total ?? null, ending: p?.ending ?? '', planned_at: p?.planned_at ?? null, volumes: p?.volumes ?? [] }
  }
  const settingsOut = (bookId: number) => {
    const s = S(bookId)
    const nums = refineNums(bookId)
    return { book_id: bookId, ...s, refine_ranges: normRanges(s.refine_ranges), presets: [150_000, 200_000, 300_000], total_chapters: Math.max(1, Math.ceil(s.target_words / Math.max(1, s.chapter_words))),
      refine_numbers: nums, refine_count: nums.length, reader_threshold: READER_PASS, plan: planSummary(bookId) }
  }
  const mkVolumes = (bookId: number, total: number) => {
    const n = Math.min(12, Math.max(2, Math.ceil(total / 60)))
    const titles = ['开门营业', '东区风云', '冰原之下', '雪线以北', '零点之城', '最后一盏灯']
    const crises = ['摩托帮盯上了超市，金牙要立规矩', '三方势力争夺东区补给线，苏晚的弟弟被抓', '冰层下的东西醒了，系统开始失控', '北方来的车队带着真相', '系统要求林野交出超市', '冰封的源头就在超市地下']
    return Array.from({ length: n }, (_, i) => {
      const start = Math.round((total * i) / n) + 1, end = Math.round((total * (i + 1)) / n)
      const v: any = { node_id: 9000 + bookId * 20 + i, order: i + 1, title: `第${i + 1}卷 · ${titles[i % titles.length]}`, summary: '', start, end, crisis: crises[i % crises.length],
        climax_chapter: Math.max(start, end - Math.max(1, Math.floor((end - start + 1) / 10))), closure: i === n - 1 ? '冰封解除，超市成为新城的第一盏灯' : '卷末解决本卷危机，留一个通往下一卷的钩子' }
      if (i === n - 1) v.finale = { resolution: '林野关掉系统，用超市里最后一批物资换来全城人的生路', payoffs: ['父亲的老猎枪', '冰层下的闷响', '苏晚弟弟的编号纹身'], endings: ['苏晚带着弟弟去南方开诊所', '金牙成了东区的守夜人'], last_chapter_beat: `第${end}章：春天第一场雨，林野重新挂出「只换不卖」的牌子`, last_chapter: end }
      return v
    })
  }
  const doPlan = (bookId: number) => {
    const s = S(bookId)
    const old = plans.get(bookId)
    const total = Math.max(Math.ceil(s.target_words / Math.max(1, s.chapter_words)), writtenMax(bookId))
    const vols = mkVolumes(bookId, total)
    const before = new Map((old?.volumes ?? []).map((v: any) => [v.order, v]))
    const diff = vols.map((v) => {
      const b = before.get(v.order)
      if (!b) return { order: v.order, node_id: v.node_id, action: 'added', after: v }
      const changed = ['start', 'end', 'crisis', 'climax_chapter', 'closure', 'finale', 'title'].filter((k) => JSON.stringify(b[k]) !== JSON.stringify(v[k]))
      return { order: v.order, node_id: v.node_id, action: changed.length ? 'updated' : 'unchanged', before: b, after: v, changed }
    })
    for (const [o, b] of before) if (!vols.some((v) => v.order === o)) diff.push({ order: o, node_id: (b as any).node_id, action: 'removed', before: b } as any)
    plans.set(bookId, { planned_at: now(), total, ending: '冰封解除，林野用超市换来全城的春天', volumes: vols })
    const warnings = total > Math.ceil(s.target_words / Math.max(1, s.chapter_words)) ? [`按目标字数算出的章数少于已写章数，总章数按 ${total} 章算`] : []
    return { total_chapters: { before: old?.total ?? null, after: total }, volumes: vols, diff, warnings, chapter_words: s.chapter_words, target_words: s.target_words }
  }

  // ---------- 批次抽检 ----------
  const check = (bookId: number, ch: Chapter, refine: Set<number>) => {
    const s = S(bookId)
    const content = ch.content ?? ''
    const head = content.replace(/\s+/g, '').slice(0, 100)
    const hits = [...new Set(head.match(/突然|猛地|一把|冷笑|血|死|拦|抢|债|威胁|开门/g) ?? [])]
    const paras = content.split('\n').filter((p) => p.trim())
    let pi = -1, pv = 0
    paras.forEach((p, i) => { const v = (p.match(/[！!]|轰|跪|震|惊|全场/g) ?? []).length; if (v > pv) { pv = v; pi = i } })
    const lo = Math.round(s.chapter_words * 0.7), hi = Math.round(s.chapter_words * 1.5)
    const rs = reader(ch)
    const tail = content.replace(/\s+/g, '').slice(-80)
    const hookOk = ch.number % 4 !== 3
    const cons = ch.number % 3 === 2 ? [{ kind: 'number', severity: 'mid', quote: paras[2]?.slice(0, 30) ?? '', comment: '子弹数量前后对不上：上一章说剩 12 发，这里成了 15 发' }] : []
    const failed: string[] = []
    if (!(ch.words >= lo && ch.words <= hi)) failed.push(`字数 ${ch.words} 偏离每章目标 ${s.chapter_words}（${lo}–${hi}）`)
    if (!hits.length) failed.push('开头前 100 字没有切进冲突')
    if (!hookOk) failed.push('章末钩子落空')
    if (rs < READER_PASS) failed.push(`读者分 ${rs} 低于阈值 ${READER_PASS}`)
    if (ch.review && !ch.review.passed) failed.push('审稿未通过')
    return {
      number: ch.number, chapter_id: ch.id, title: ch.title, status: ch.status, in_refine: refine.has(ch.number),
      words: ch.words, words_target: s.chapter_words, words_ok: ch.words >= lo && ch.words <= hi,
      opening: { head, conflict: hits.length > 0, hits },
      climax: { planned: '主角当众亮出底牌，对方当场跪下', type: '打脸', found: pv > 0, position: pi >= 0 ? Math.round(((pi + 1) / paras.length) * 100) / 100 : null, quote: pi >= 0 ? paras[pi].slice(0, 60) : '' },
      hook: { planned: '门外传来第二声闷响', type: '悬念', tail, ok: hookOk, comment: hookOk ? '' : '章末把事情交代完了，没有留下让人想翻下一章的问题' },
      consistency: cons, review_overall: ch.review?.scores?.overall ?? null, review_passed: !!ch.review?.passed,
      reader_score: rs, reader_below_threshold: rs < READER_PASS, failed, passed: !failed.length,
    }
  }
  const report = (bookId: number, ids: number[]) => {
    const refine = new Set(refineNums(bookId))
    const items = ids.map((id) => db.chapters.find((x) => x.id === id)).filter(Boolean).map((ch) => check(bookId, ch!, refine))
    const scores = items.map((x) => x.reader_score).filter((x): x is number => x != null)
    return { chapters: items, summary: {
      count: items.length, words: items.reduce((n, x) => n + x.words, 0), passed: items.filter((x) => x.passed).length, failed: items.filter((x) => !x.passed).length,
      committed: items.filter((x) => x.status === 'committed').length, awaiting_approval: items.filter((x) => x.in_refine && x.status !== 'committed').map((x) => x.number),
      reader_avg: scores.length ? Math.round((scores.reduce((a, b) => a + b, 0) / scores.length) * 100) / 100 : null,
      reader_below_threshold: items.filter((x) => x.reader_below_threshold).map((x) => x.number), consistency_issues: items.reduce((n, x) => n + x.consistency.length, 0),
    }, reader_threshold: READER_PASS, generated_at: now() }
  }
  const batchOut = (b: any, withReport = true) => ({ ...b, summary: b.report?.summary ?? null, report: withReport ? b.report ?? null : undefined })
  const finish = (b: any, status: string, reason: string, message: string) => { Object.assign(b, { status, stop_reason: reason, message, finished_at: now() }); b.report = report(b.book_id, b.chapter_ids) }

  const runBatch = (bookId: number, force: boolean) => {
    const s = S(bookId)
    if (s.mode !== 'wanben') throw new HttpErr(409, '本书是连载模式，请先在完本设置里把模式切换为完本（mode=wanben）')
    const active = db.jobs.find((j) => j.kind === 'wanben_batch' && j.book_id === bookId && !j._done)
    if (active) return { ...active }
    paused.set(bookId, false)
    const start = writtenMax(bookId) + 1
    const n = Math.max(1, Math.min(s.batch_size, totalOf(bookId) - start + 1))
    const refine0 = refineNums(bookId)
    const blocked0 = chs(bookId).some((x) => x.status !== 'committed' && (!refine0.includes(x.number) || (s.pause_on_unapproved_refine && !force))) || start > totalOf(bookId)
    const dur = blocked0 ? 700 : 1400 + n * 700
    let batch: any = null
    const job = createJob('wanben_batch', bookId, dur, Array.from({ length: n }, (_, i) => `[${i + 1}/${n}] 写第 ${start + i} 章：组装上下文、写作、审稿…`), () => {
      if (!plans.has(bookId)) doPlan(bookId)
      const refine = new Set(refineNums(bookId))
      const pendRefine = chs(bookId).filter((x) => x.status !== 'committed' && refine.has(x.number)).map((x) => x.number)
      const other = chs(bookId).filter((x) => x.status !== 'committed' && !refine.has(x.number)).map((x) => x.number)
      const pause = s.pause_on_unapproved_refine && !force
      const prog = () => progress(bookId)
      const drop = () => { if (batch && batches.includes(batch)) batches.splice(batches.indexOf(batch), 1); batch = null }
      if (other.length) { drop(); return { stopped: true, reason: 'pending_chapter', message: `第${other[0]}章还没提交（审稿未过或等待选版本），处理后再继续连写`, batches: [], progress: prog() } }
      if (pendRefine.length && pause) { drop(); return { stopped: true, reason: 'refine_pending', message: `精修范围内第${pendRefine.join('、')}章待审批；审批后继续，或「先不审，继续写」/ 关闭「精修待审批时暂停」`, batches: [], progress: prog() } }
      if (start > totalOf(bookId)) { drop(); return { stopped: true, reason: 'target_reached', message: `已写满目标 ${totalOf(bookId)} 章`, batches: [], progress: prog() } }
      if (!batch) batch = { id: nid(), book_id: bookId, job_id: job.id, seq: batches.filter((x) => x.book_id === bookId).length + 1, start_no: start, end_no: start + n - 1, status: 'running', stop_reason: '', message: '', chapter_ids: [], created_at: now(), finished_at: null, report: null }
      if (!batches.includes(batch)) batches.unshift(batch)
      batch.status = 'running'
      for (let i = 0; i < n; i++) {
        if (paused.get(bookId) && i > 0) { finish(batch, 'paused', 'paused', `已暂停（写到第${writtenMax(bookId)}章）`); return { stopped: true, reason: 'paused', message: '作者暂停', batches: [batchOut(batch, false)], progress: prog() } }
        const ch = c.writeOne(bookId, 1)
        ch.title = `第${ch.number}章 ${['雪夜来客', '十二发子弹', '冰下回声', '东区规矩', '第一批货', '谁在敲门', '换命', '守夜人'][ch.number % 8]}`
        batch.chapter_ids.push(ch.id)
        if (refine.has(ch.number)) {
          ch.status = 'reviewing'
          if (pause) { finish(batch, 'stopped', 'refine_pending', `第${ch.number}章在精修范围内，已写好等待审批；审批后继续连写`); return { stopped: true, reason: 'refine_pending', message: batch.message, batches: [batchOut(batch, false)], progress: prog() } }
        } else ch.status = 'committed'
      }
      c.recalc(bookId)
      finish(batch, 'done', '', `本批第${start}–${start + n - 1}章写完`)
      return { stopped: false, reason: '', message: batch.message, batches: [batchOut(batch, false)], progress: prog() }
    }, `wanben:${bookId}`)
    // 跑的过程中就能看到「连写中」的批次
    batch = { id: nid(), book_id: bookId, job_id: job.id, seq: batches.filter((x) => x.book_id === bookId).length + 1, start_no: start, end_no: start + n - 1, status: 'running', stop_reason: '', message: '', chapter_ids: [], created_at: now(), finished_at: null, report: null }
    if (!blocked0) batches.unshift(batch); else batch = null
    return job
  }
  const progress = (bookId: number) => {
    const s = S(bookId)
    const all = chs(bookId)
    const total = totalOf(bookId)
    const wm = writtenMax(bookId)
    const committed = all.filter((x) => x.status === 'committed')
    const words = committed.reduce((n, x) => n + x.words, 0)
    const p = plans.get(bookId)
    const cur = Math.min(wm + 1, total)
    const vol = p?.volumes.find((v: any) => v.start <= cur && cur <= v.end)
    const last = batches.find((b) => b.book_id === bookId)
    const running = batches.find((b) => b.book_id === bookId && b.status === 'running')
    return { book_id: bookId, mode: s.mode, words, pending_words: all.filter((x) => x.status !== 'committed').reduce((n, x) => n + x.words, 0), target_words: s.target_words,
      ratio: Math.min(1, words / s.target_words), chapters_committed: committed.length, chapters_written: wm, chapters_total: total, chapters_remaining: Math.max(0, total - wm),
      current_volume: vol ? { order: vol.order, title: vol.title, start: vol.start, end: vol.end, node_id: vol.node_id } : null,
      planned: !!p, paused: !!paused.get(bookId), running_batch_id: running?.id ?? null, last_batch: last ? batchOut(last, false) : null }
  }
  const refineSummary = (bookId: number) => {
    const s = S(bookId)
    const nums = refineNums(bookId)
    const byNo = new Map(chs(bookId).map((x) => [x.number, x]))
    const rows = nums.map((n) => {
      const ch = byNo.get(n)
      const pend = iterations.filter((it) => it.book_id === bookId && it.number === n && it.status === 'pending').length
      if (!ch) return { number: n, chapter_id: null, title: '', status: 'unwritten', approved: false, words: 0, review_overall: null, review_passed: null, reader_score: null, reader_below_threshold: false, iterations_pending: pend }
      const rs = reader(ch)
      return { number: n, chapter_id: ch.id, title: ch.title, status: ch.status, approved: ch.status === 'committed', words: ch.words, review_overall: ch.review?.scores?.overall ?? null,
        review_passed: ch.review ? !!ch.review.passed : null, reader_score: rs, reader_below_threshold: rs < READER_PASS, iterations_pending: pend }
    })
    return { book_id: bookId, refine_scope: s.refine_scope, golden_chapters: s.golden_chapters, refine_ranges: normRanges(s.refine_ranges), pause_on_unapproved_refine: s.pause_on_unapproved_refine,
      numbers: nums, total: nums.length, written: rows.filter((r) => r.status !== 'unwritten').length, approved: rows.filter((r) => r.approved).length,
      pending: rows.filter((r) => r.status !== 'unwritten' && r.status !== 'committed').map((r) => r.number), unwritten: rows.filter((r) => r.status === 'unwritten').length,
      reader_below_threshold: rows.filter((r) => r.reader_below_threshold).map((r) => r.number), all_approved: rows.every((r) => r.approved), reader_threshold: READER_PASS, chapters: rows }
  }

  // ---------- 章节迭代 ----------
  const tweak = (text: string, round: number, method: string) => {
    const ps = text.split('\n')
    return ps.map((p, i) => {
      if (!p.trim()) return p
      if (i === 0) return `“开门。”门外的人第${round === 1 ? '一' : round === 2 ? '二' : '三'}次敲响卷帘门，声音压得很低。${p}`
      if (method === 'rewrite' && i % 3 === 1) return p.replace(/。/, '，指节在柜台上敲了两下。')
      if (i % 5 === 2) return p.replace(/了/, '').replace(/。$/, '——他没再往下说。')
      return p
    }).join('\n')
  }
  const scoreOf = (ch: Chapter) => ({ overall: ch.review?.scores?.overall ?? 70, reader: reader(ch), passed: ch.review ? !!ch.review.passed : null, issues: (ch.review?.issues ?? []).filter((x) => x.severity !== 'low').length })
  const itOut = (it: any, withContent: boolean) => {
    const ch = db.chapters.find((x) => x.id === it.chapter_id)
    const { content, base_content, review, lint, ...rest } = it
    return { ...rest, stale: (ch?.content ?? '') !== base_content, ...(withContent ? { content, base_content, review, lint } : {}) }
  }
  const selectChs = (bookId: number, b: any) => {
    const nums = new Set<number>()
    for (const n of b.numbers ?? []) nums.add(+n)
    if (b.start || b.end) { const a = +(b.start || b.end), e = +(b.end || a); for (let i = Math.min(a, e); i <= Math.max(a, e); i++) nums.add(i) }
    for (const [a, e] of normRanges(b.ranges ?? [])) for (let i = a; i <= e; i++) nums.add(i)
    if (!nums.size) throw new HttpErr(422, '请指定章号：start/end、numbers 或 ranges')
    return chs(bookId).filter((x) => nums.has(x.number) && (x.content ?? '').trim())
  }

  // ---------- 路由：完本 ----------
  on('GET', '/books/:id/wanben', (m) => settingsOut(bookOf(m[1]).id))
  on('PUT', '/books/:id/wanben', (m, b) => {
    const book = bookOf(m[1]); const s = S(book.id)
    for (const k of Object.keys(DEFAULTS) as (keyof typeof DEFAULTS)[]) if (b?.[k] !== undefined && b[k] !== null) (s as any)[k] = k === 'refine_ranges' ? normRanges(b[k]) : b[k]
    if (b?.mode) { if (!['serial', 'wanben'].includes(b.mode)) throw new HttpErr(422, 'mode 只能是 serial 或 wanben'); s.mode = b.mode; (book as any).mode = b.mode }
    if (s.mode === 'wanben') { book.target_words = s.target_words; book.chapter_words = s.chapter_words }
    return settingsOut(book.id)
  })
  on('POST', '/books/:id/wanben/plan', (m) => {
    const id = bookOf(m[1]).id
    if (S(id).mode !== 'wanben') throw new HttpErr(409, '本书是连载模式，请先在完本设置里把模式切换为完本（mode=wanben）')
    return createJob('wanben_plan', id, 3200, ['读取大纲与已写章节…', '按字数目标倒推总章数…', '分卷：定危机、高潮章与收束…', '末卷写入完整结局…', '写入卷纲'], () => doPlan(id), `wanben:${id}`)
  })
  on('GET', '/books/:id/wanben/plan', (m) => planSummary(bookOf(m[1]).id))
  on('POST', '/books/:id/wanben/batch', (m, b) => runBatch(bookOf(m[1]).id, !!b?.force))
  on('POST', '/books/:id/wanben/batch/pause', (m) => {
    const id = bookOf(m[1]).id
    paused.set(id, true)
    const active = db.jobs.find((j) => j.kind === 'wanben_batch' && j.book_id === id && !j._done)
    return { ok: true, paused: true, running_batch_id: batches.find((x) => x.book_id === id && x.status === 'running')?.id ?? null, job_id: active?.id ?? null, message: active ? '当前章写完后暂停' : '没有正在跑的批次；下次发起连写会自动清除暂停' }
  })
  on('GET', '/books/:id/wanben/batches', (m) => batches.filter((x) => x.book_id === +m[1]).map((x) => batchOut(x, false)))
  on('GET', '/books/:id/wanben/batches/:bid', (m) => batchOut(must(batches.find((x) => x.book_id === +m[1] && x.id === +m[2]), '批次')))
  on('GET', '/books/:id/wanben/refine', (m) => refineSummary(bookOf(m[1]).id))
  on('GET', '/books/:id/wanben/golden', (m) => refineSummary(bookOf(m[1]).id))
  on('POST', '/books/:id/wanben/refine', (m, b) => {
    const id = bookOf(m[1]).id; const s = S(id)
    const cur = new Set(refineNums(id))
    const given = normRanges(b?.ranges ?? []).flatMap(([a, e]) => Array.from({ length: e - a + 1 }, (_, k) => a + k))
    if (b?.action === 'remove') given.forEach((n) => cur.delete(n)); else if (b?.action === 'set') { cur.clear(); given.forEach((n) => cur.add(n)) } else given.forEach((n) => cur.add(n))
    s.refine_scope = 'custom'; s.refine_ranges = normRanges([...cur].map((n) => [n, n]))
    return refineSummary(id)
  })
  on('POST', '/books/:id/wanben/iterate', (m, b) => {
    const id = bookOf(m[1]).id
    const targets = selectChs(id, b ?? {})
    if (!targets.length) throw new HttpErr(409, '所选范围内没有已写正文的章节')
    iterStop.set(id, false)
    const rounds = Math.max(1, Math.min(5, +(b?.rounds ?? 1)))
    const steps = targets.flatMap((ch) => Array.from({ length: rounds }, (_, r) => `第${ch.number}章 第${r + 1}/${rounds}轮：${b?.method === 'patch' ? '定点修' : '整章重写'}…`))
    return createJob('wanben_iterate', id, 900 + steps.length * 900, steps, () => {
      const rows: any[] = []
      for (const ch of targets) {
        const prevs = iterations.filter((x) => x.chapter_id === ch.id).sort((x, y) => y.round - x.round)
        let base = ch.content ?? ''
        let sb: any = scoreOf(ch)
        for (let r = 0; r < rounds; r++) {
          if (iterStop.get(id)) return { iterations: rows, chapters: targets.length, rounds, stopped: true }
          const method = b?.method === 'auto' || !b?.method ? (b?.instruction?.trim() || sb.reader < READER_PASS ? 'rewrite' : 'patch') : b.method
          const round = prevs.length + r + 1
          const content = tweak(base, round, method)
          const sa = { overall: Math.min(96, (sb.overall ?? 70) + 2 + ((ch.number + round) % 4)), reader: Math.min(10, (sb.reader ?? 6) + (round % 2)), passed: true, issues: Math.max(0, (sb.issues ?? 2) - 1) }
          const it = { id: nid(), book_id: id, chapter_id: ch.id, number: ch.number, job_id: null, round, method, instruction: b?.instruction?.trim() || '按下列审稿与读者审读问题修改本章，保留情节与人名设定：\n- [high/节奏] 一句话跳过好几天\n- 读者：开头慢，第三段才进冲突',
            base_content: base, content, words: c.countWords(content), review: c.mkReview(ch.number + round, content), lint: c.mkLint(content),
            scores: { before: sb, after: sa, delta: { overall: sa.overall - (sb.overall ?? 0), reader: sa.reader - (sb.reader ?? 0) } }, status: 'pending', created_at: now() }
          iterations.push(it); rows.push(itOut(it, false))
          base = content; sb = sa
        }
      }
      iterStop.set(id, false)
      return { iterations: rows, chapters: targets.length, rounds, stopped: false }
    }, `wanben:${id}`)
  })
  on('POST', '/books/:id/wanben/iterate/stop', (m) => { iterStop.set(bookOf(m[1]).id, true); return { ok: true, message: '当前这一轮结束后停止' } })
  on('GET', '/books/:id/wanben/iterations', (m, _b, u) => {
    const id = bookOf(m[1]).id
    const n = u.searchParams.get('number'), cid = u.searchParams.get('chapter_id'), s = u.searchParams.get('status')
    return iterations.filter((x) => x.book_id === id && (!n || x.number === +n) && (!cid || x.chapter_id === +cid) && (!s || x.status === s)).sort((a, b) => a.number - b.number || a.id - b.id).map((x) => itOut(x, false))
  })
  on('GET', '/books/:id/wanben/iterations/:iid', (m) => itOut(must(iterations.find((x) => x.book_id === +m[1] && x.id === +m[2]), '迭代版本'), true))
  on('POST', '/books/:id/wanben/iterations/:iid/adopt', (m) => {
    const it = must(iterations.find((x) => x.book_id === +m[1] && x.id === +m[2]), '迭代版本')
    if (it.status === 'adopted') throw new HttpErr(409, '这个版本已经采纳过了')
    const ch = must(db.chapters.find((x) => x.id === it.chapter_id), '章节')
    ;(c.chHist[ch.id] ??= []).push({ content: ch.content ?? '', title: ch.title, label: `完本迭代第${it.round}轮采纳前` })
    Object.assign(ch, { content: it.content, words: it.words, review: it.review, lint: it.lint, history: c.chHist[ch.id].length, last_history_label: `完本迭代第${it.round}轮采纳前`, updated_at: now() })
    readerScore.set(ch.id, it.scores.after.reader)
    it.status = 'adopted'
    c.recalc(ch.book_id)
    return { iteration: itOut(it, false), chapter_id: ch.id, chapter_status: ch.status, words: ch.words }
  })
  on('POST', '/books/:id/wanben/iterations/:iid/discard', (m) => {
    const it = must(iterations.find((x) => x.book_id === +m[1] && x.id === +m[2]), '迭代版本')
    if (it.status === 'adopted') throw new HttpErr(409, '已采纳的版本不能丢弃；要回到旧稿请用章节撤回')
    it.status = 'discarded'
    return itOut(it, false)
  })
  on('GET', '/books/:id/wanben/progress', (m) => progress(bookOf(m[1]).id))
  on('GET', '/books/:id/wanben/export.txt', (m) => {
    const book = bookOf(m[1])
    const text = `${book.title}\n\n` + chs(book.id).filter((x) => x.status === 'committed').map((x) => `${x.title}\n\n${x.content ?? ''}`).join('\n\n\n')
    return new Response(text, { status: 200, headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Content-Disposition': `attachment; filename="novelos_${book.id}.txt"; filename*=UTF-8''${encodeURIComponent(book.title + '.txt')}` } })
  })

  // ---------- 路由：风格档 / 短剧自查 ----------
  on('GET', '/platform-styles', () => ({ items: [{ id: 'fanqie', label: '番茄', optional: false }, { id: 'qidian', label: '起点', optional: false }, { id: 'generic', label: '通用', optional: false }, { id: 'duanju', label: '短剧分镜', optional: true }] }))
  on('POST', '/chapters/:id/duanju-check', (m) => {
    const ch = must(db.chapters.find((x) => x.id === +m[1]), '章节')
    const text = ch.content ?? ''
    const opening = text.trim().slice(0, 100)
    const hasQ = /[“「"]/.test(opening), hasA = /推开|一脚|抓住|冲|拔|砸|踹|敲/.test(opening)
    const paras = text.split('\n').filter((p) => p.trim())
    const words = Math.max(1, c.countWords(text))
    const mono = paras.filter((p) => !/[“「"]/.test(p) && /心想|心里|暗自|想起|脑海/.test(p)).reduce((n, p) => n + c.countWords(p), 0) / words
    const scen = paras.filter((p) => !/[“「"]/.test(p) && (p.match(/雪|风|天空|月光|冰|云/g) ?? []).length >= 2).reduce((n, p) => n + c.countWords(p), 0) / words
    const dlg = (text.match(/“[^”]*”/g) ?? []).join('').length / words
    const tail = text.trim().slice(-200)
    const cliff = /突然|下一刻|就在这时|闷响|？$|……$|——$/.test(tail)
    const issues: any[] = []
    if (!(hasQ || hasA)) issues.push({ type: 'opening_slow', severity: 'mid', evidence: opening.slice(0, 60) + '…', suggestion: '前 100 字直接切一个正在发生的动作或一句强对白，天气、来历、心理放到后面' })
    if (mono > 0.12) issues.push({ type: 'monologue', severity: mono > 0.2 ? 'mid' : 'low', evidence: `心理独白段约占 ${Math.round(mono * 100)}%`, suggestion: '大段心理独白压成一两句，立刻转成台词、动作或微表情' })
    if (scen > 0.08) issues.push({ type: 'scenery', severity: scen > 0.15 ? 'mid' : 'low', evidence: (paras.find((p) => (p.match(/雪|风|天空|月光|冰|云/g) ?? []).length >= 2) ?? '').slice(0, 50), suggestion: '景物描写只留一句布景提示，其余删掉' })
    if (!cliff) issues.push({ type: 'ending_flat', severity: 'mid', evidence: tail.slice(-50), suggestion: '章末停在危机落下或真相揭开的前一刻：最后一句是动作或半句台词，不写结果' })
    return { chapter_id: ch.id, number: ch.number, opening_ok: hasQ || hasA, opening_has_dialogue: hasQ, opening_has_action: hasA, monologue_ratio: +mono.toFixed(3), scenery_ratio: +scen.toFixed(3), ending_cliff: cliff, dialogue_ratio: +Math.min(0.9, dlg).toFixed(3), issues }
  })

  // ---------- 路由：整书体检 ----------
  const TL: Record<string, string> = { short_chapter: '单章过短', similar_chapter: '近似章', watering: '水化', repetitive_phrases: '全书重复句式', numeric: '数值不一致', foreshadow_open: '伏笔未回收', title_mismatch: '标题章号不符', ending_open: '末章未收束', character_state: '人物状态矛盾', timeline: '时间线矛盾', mainline_drift: '主线跑偏' }
  const bookCheck = (bookId: number, llm: boolean) => {
    const list = chs(bookId).filter((x) => (x.content ?? '').trim())
    if (!list.length) throw new Error('这本书还没有写好的章节，写完再来体检')
    const iss: any[] = []
    const add = (type: string, severity: string, ch: Chapter | null, evidence: string, suggestion: string, fix: any = null, extra: any = {}) =>
      iss.push({ type, type_label: TL[type] ?? type, severity, layer: 'rule', chapter: ch?.number ?? null, chapter_id: ch?.id ?? null, related_chapters: [], evidence, suggestion, fixable: !!fix, fix, ...extra })
    const last = list[list.length - 1]
    add('ending_open', 'high', last, (last.content ?? '').slice(-60), '末章停在悬念上：把主线矛盾在这一章正面解决，最后写一段主角的落点', { action: 'rewrite', method: 'POST', endpoint: `/api/chapters/${last.id}/rewrite`, body: { instruction: '把末章改成收束结局：主线矛盾正面解决，结尾写主角的落点，不留悬念式钩子', scope: 'all' } })
    db.foreshadows.filter((f) => f.book_id === bookId && (f.status === 'planted' || f.status === 'advancing')).forEach((f, i) => {
      const ch = list.find((x) => x.number === f.planted_ch) ?? null
      add('foreshadow_open', i === 0 ? 'high' : 'mid', ch, `第${f.planted_ch}章埋下：${f.desc}`, '在结局前补一场回收戏，让这条伏笔有交代；确实不要了就在伏笔面板标记为放弃')
    })
    if (list[2]) add('similar_chapter', 'mid', list[2], `与第1章重合约 27%：${(list[0].content ?? '').slice(0, 40)}`, `第${list[2].number}章与第1章情节/句子高度相似，换场景、换冲突或合并两章`, { action: 'rewrite', method: 'POST', endpoint: `/api/chapters/${list[2].id}/rewrite`, body: { instruction: '换一个场景和冲突，避免与第1章重复', scope: 'all' } }, { related_chapters: [1] })
    if (list[1]) add('watering', 'mid', list[1], '套话 6 处、概述式叙述 3 段：「于是接下来的几天里……」', '把概述的过程写成场面，删掉套话', { action: 'humanize', method: 'POST', endpoint: `/api/chapters/${list[1].id}/humanize`, body: {} })
    if (list[1]) add('numeric', 'mid', list[1], '林野的年龄：第1章「十七岁」，这里「十八岁」', '统一成一个数，或补一句时间流逝')
    if (list[3]) add('title_mismatch', 'low', list[3], `标题「${list[3].title}」缺少章号`, `标题改成「第${list[3].number}章 ${list[3].title.replace(/^第\d+章\s*/, '')}」`, { action: 'set_title', method: 'PUT', endpoint: `/api/chapters/${list[3].id}`, body: { title: `第${list[3].number}章 ${list[3].title.replace(/^第\d+章\s*/, '')}` } })
    if (list[4]) add('short_chapter', 'mid', list[4], `第${list[4].number}章字数偏少，过程多为概述`, '补到 1000 字以上：把概述的过程写成场面', { action: 'thicken', method: 'POST', endpoint: `/api/chapters/${list[4].id}/thicken`, body: {} })
    add('repetitive_phrases', 'low', null, '「冷冰冰的」×5章、「没说话」×5章', '这些说法几乎每章都出现：逐章换成当场的具体动作或细节')
    if (llm) {
      if (list[3]) iss.push({ type: 'character_state', type_label: TL.character_state, severity: 'mid', layer: 'llm', chapter: list[3].number, chapter_id: list[3].id, related_chapters: [2], evidence: (list[3].content ?? '').split('\n')[2]?.slice(0, 50) ?? '', suggestion: '苏晚第2章已经知道超市系统，这里又表现得毫不知情：补一句她在试探林野', fixable: true, fix: { action: 'rewrite', method: 'POST', endpoint: `/api/chapters/${list[3].id}/rewrite`, body: { instruction: '让苏晚的反应与她已知系统的设定一致：改成她在试探林野', scope: 'all' } }, verified: true })
      if (list[4]) iss.push({ type: 'timeline', type_label: TL.timeline, severity: 'low', layer: 'llm', chapter: list[4].number, chapter_id: list[4].id, related_chapters: [], evidence: '“三天后，补给车终于到了”', suggestion: '前文说补给车一周一趟，这里三天就到了：改成“一周后”或交代提前的原因', fixable: false, fix: null, verified: false })
      iss.push({ type: 'mainline_drift', type_label: TL.mainline_drift, severity: 'mid', layer: 'llm', chapter: null, chapter_id: null, related_chapters: [], evidence: '第4–5章大段写苏晚的过去', suggestion: '主线跑偏：压缩回忆，把主角目标拉回守住超市', fixable: false, fix: null, verified: true })
    }
    const order: Record<string, number> = { high: 0, mid: 1, low: 2 }
    iss.sort((a, b) => order[a.severity] - order[b.severity] || (a.chapter ?? 1e9) - (b.chapter ?? 1e9))
    iss.forEach((x, i) => (x.id = i + 1))
    const pen: Record<string, number> = { high: 10, mid: 4, low: 1 }
    const byType: Record<string, number> = {}
    iss.forEach((x) => (byType[x.type] = Math.min(20, (byType[x.type] ?? 0) + pen[x.severity])))
    const score = Math.max(0, 100 - Object.values(byType).reduce((a, b) => a + b, 0))
    const highs = iss.filter((x) => x.severity === 'high').length
    const verdict = score < 60 || highs >= 5 ? 'not_ready' : highs >= 1 || score < 80 ? 'fix_first' : 'ready'
    const words = list.map((x) => x.words)
    const total = words.reduce((a, b) => a + b, 0)
    const cnt = (s: string) => iss.filter((x) => x.severity === s).length
    const typeCnt: Record<string, number> = {}
    iss.forEach((x) => (typeCnt[x.type] = (typeCnt[x.type] ?? 0) + 1))
    return {
      book_id: bookId, kind: 'book_check', verdict, verdict_label: { ready: '可以收尾', fix_first: '先修再收尾', not_ready: '还需大修' }[verdict], score, issues: iss,
      stats: { chapters: list.length, empty_chapters: 0, committed_chapters: list.filter((x) => x.status === 'committed').length, total_words: total, avg_words: Math.round(total / list.length),
        min_words: Math.min(...words), max_words: Math.max(...words), short_chapters: words.filter((w) => w < 1000).length,
        word_tier: { total_words: total, tier: total < 150000 ? 'below_15w' : total < 300000 ? '15w_30w' : 'above_30w', label: `字数参考档位：${total < 150000 ? '不足 15 万字' : total < 300000 ? '15 万–30 万字' : '30 万字以上'}`, reference: [150000, 300000], to_next: total < 150000 ? 150000 - total : total < 300000 ? 300000 - total : 0 },
        duplicate_pairs: list[2] ? [{ chapters: [1, list[2].number], ratio: 0.27, longest: 64 }] : [], top_phrases: [{ text: '冷冰冰的', chapters: 5 }, { text: '没说话', chapters: 5 }],
        open_foreshadows: db.foreshadows.filter((f) => f.book_id === bookId && (f.status === 'planted' || f.status === 'advancing')).length,
        ending: { closed: false, cliff: true, last_chapter: last.number, tail: (last.content ?? '').slice(-60) }, watering_chapters: 2, numeric_conflicts: 1, avg_dialogue_ratio: 0.31,
        issues_total: iss.length, issues_truncated: 0, by_severity: { high: cnt('high'), mid: cnt('mid'), low: cnt('low') }, by_type: typeCnt, fixable: iss.filter((x) => x.fixable).length },
      foreshadows_open: db.foreshadows.filter((f) => f.book_id === bookId && (f.status === 'planted' || f.status === 'advancing')).map((f) => ({ id: f.id, desc: f.desc, status: f.status, planted_ch: f.planted_ch, last_ch: f.last_ch })),
      llm: llm ? { used: true, ending: { rushed: false, score: 5.5, comment: '末章停在「闷响」上，主线还没有了结：如果这是全书最后一章，需要补正面对决和人物去向。', evidence: (last.content ?? '').slice(-40) },
        mainline: { drift: true, score: 6.5, comment: '第4–5章回忆偏长，主角守店的目标被冲淡。', evidence: '' }, summary: '开篇抓人、交易爽点清晰；结局还没收住，伏笔回收和末章是收尾前最该补的两块。', segments: 1, sent_chars: 5200 } : { used: false },
      platform: 'fanqie',
    }
  }
  const jobsOf = (bookId: number, kind: string) => db.jobs.filter((j) => j.book_id === bookId && j.kind === kind && (j._done || j.status === 'succeeded') && j.status === 'succeeded').sort((a, b) => b.id - a.id)
  on('POST', '/books/:id/book-check', (m, b) => {
    const id = bookOf(m[1]).id
    const llm = b?.llm !== false
    const active = db.jobs.find((j) => j.kind === 'book_check' && j.book_id === id && !j._done)
    if (active) return { ...active }
    return createJob('book_check', id, llm ? 5200 : 2600, ['读取章节', '逐章查水化与数值一致性…', '查重复章与重复句式', ...(llm ? ['连续性检查：人物状态、战力、时间线…', '判断结局与主线'] : []), '汇总'], () => bookCheck(id, llm), `book:${id}`)
  })
  on('GET', '/books/:id/book-check', (m, _b, u) => {
    const id = bookOf(m[1]).id
    const jid = u.searchParams.get('job_id')
    const j = jobsOf(id, 'book_check').find((x) => !jid || x.id === +jid)
    return { report: j ? { ...j.result, job_id: j.id, checked_at: j.updated_at } : null }
  })
  on('GET', '/books/:id/book-check/history', (m) => ({ items: jobsOf(bookOf(m[1]).id, 'book_check').map((j) => ({ job_id: j.id, created_at: j.created_at, updated_at: j.updated_at, verdict: j.result?.verdict, score: j.result?.score, by_severity: j.result?.stats?.by_severity, chapters: j.result?.stats?.chapters, total_words: j.result?.stats?.total_words, llm_used: !!j.result?.llm?.used })) }))

  // ---------- 路由：可改编度 ----------
  const adapt = (bookId: number, a?: number, e?: number, llm = true) => {
    let list = chs(bookId).filter((x) => (x.content ?? '').trim())
    if (a) list = list.filter((x) => x.number >= a)
    if (e) list = list.filter((x) => x.number <= e)
    if (!list.length) throw new Error('指定范围内没有写好的章节')
    const ms = list.map((ch) => {
      const t = ch.content ?? ''
      const w = Math.max(1, c.countWords(t))
      const dl = (t.match(/“[^”]*”/g) ?? []).join('').length / w
      const scenes = Math.max(1, Math.min(8, 1 + (t.match(/第二天|当晚|另一边|片刻后/g) ?? []).length + (ch.number % 3)))
      const conflict = Math.round(((t.match(/抢|逼|冷笑|威胁|枪|债|拦/g) ?? []).length * 1000 / w) * 100) / 100
      const eps = Math.round(Math.max(0.5, Math.min(4, (w / 700 + scenes) / 2 * (conflict < 1 ? 0.7 : 1))) * 10) / 10
      return { chapter: ch.number, chapter_id: ch.id, words: w, dialogue_ratio: Math.round(dl * 1000) / 1000, conflict_per_k: conflict, reversal_per_k: Math.round(((ch.number * 7) % 10) / 10 * 100) / 100 + 0.4,
        scenes, episodes: eps, opening_ok: ch.number % 3 !== 2, ending_cliff: ch.number % 4 !== 3, monologue_ratio: 0.06, scenery_ratio: 0.05 }
    })
    const L: Record<string, string> = { persona: '人设极致度', conflict: '冲突密度', reversal: '反转速度', shootability: '场景数与可拍性', dialogue: '对白占比', episodes: '每章可切集数' }
    const base: Record<string, number> = { persona: 7, conflict: 6.4, reversal: 4.8, shootability: 7.6, dialogue: 6.1, episodes: 6.8 }
    const comments: Record<string, string> = { persona: '林野「只换不卖」的规矩够极致，反派金牙的标签还不够鲜明', conflict: '交易场面里冲突密集，独处段落偏松', reversal: '反转主要靠外部来人，缺少身份揭露类的翻转', shootability: '场景集中在超市内外，好拍、成本低', dialogue: '对白推进为主，个别段落叙述代替了交锋', episodes: '每章戏量约 2 集，节奏适合竖屏' }
    const dims: any = {}
    for (const d of Object.keys(L)) { const lv = llm ? Math.round((base[d] + 0.6) * 10) / 10 : null; dims[d] = { label: L[d], score: lv != null ? Math.round(((base[d] + lv) / 2) * 10) / 10 : base[d], rule_score: base[d], llm_score: lv, comment: llm ? comments[d] : '' } }
    const W: Record<string, number> = { persona: 0.2, conflict: 0.2, reversal: 0.15, shootability: 0.15, dialogue: 0.15, episodes: 0.15 }
    const score = Math.round(Object.keys(W).reduce((n, d) => n + dims[d].score * W[d], 0) * 10) / 10
    const epsAvg = Math.round((ms.reduce((n, x) => n + x.episodes, 0) / ms.length) * 10) / 10
    const slow = ms.filter((x) => !x.opening_ok).map((x) => x.chapter), flat = ms.filter((x) => !x.ending_cliff).map((x) => x.chapter)
    return { book_id: bookId, kind: 'adaptability', range: { start: ms[0].chapter, end: ms[ms.length - 1].chapter, chapters: ms.length }, score, dimensions: dims, episodes_per_chapter: epsAvg,
      episodes_total: Math.round(ms.reduce((n, x) => n + x.episodes, 0) * 10) / 10, persona_tags: ['林野：狠、护短', '金牙：毒舌'],
      suggestions: [...(llm ? ['把苏晚弟弟的编号纹身提前到第 3 章揭开一半，做第一次身份反转', '金牙每次出场都给一个具体的狠招，强化反派记忆点'] : []), ...(slow.length ? [`第${slow.join('、')}章开场 100 字没有动作或强对白，改成直接切进冲突`] : []), ...(flat.length ? [`第${flat.join('、')}章章末没有停在危机/揭露前一刻，砍掉结果和反应，停在半句台词或动作上`] : []), '反转偏慢：每 500–800 字安排一次身份揭露、立场翻转或局势逆转'],
      chapter_notes: llm ? ms.slice(0, 3).map((x) => ({ chapter: x.chapter, episodes: x.episodes, note: x.chapter === 1 ? '零点补货可以做成第一集的钩子画面' : '交易场面可以拆成两集，中间卡在对方掏枪' })) : [],
      chapters: ms, llm_used: llm }
  }
  on('POST', '/books/:id/adaptability', (m, b) => {
    const id = bookOf(m[1]).id
    if (b?.start && b?.end && b.start > b.end) throw new HttpErr(422, '起始章号不能大于结束章号')
    return createJob('adaptability', id, 3600, ['统计冲突、反转、场景与对白', '审读可改编度…', '汇总'], () => adapt(id, b?.start, b?.end, b?.llm !== false), `book:${id}`)
  })
  on('GET', '/books/:id/adaptability', (m, _b, u) => {
    const id = bookOf(m[1]).id; const jid = u.searchParams.get('job_id')
    const j = jobsOf(id, 'adaptability').find((x) => !jid || x.id === +jid)
    return { report: j ? { ...j.result, job_id: j.id, checked_at: j.updated_at } : null }
  })
  on('GET', '/books/:id/adaptability/history', (m) => ({ items: jobsOf(bookOf(m[1]).id, 'adaptability').map((j) => ({ job_id: j.id, created_at: j.created_at, updated_at: j.updated_at, score: j.result?.score, range: j.result?.range, episodes_per_chapter: j.result?.episodes_per_chapter, llm_used: !!j.result?.llm_used })) }))

  // ---------- 路由：同质化 ----------
  const homo = (target: 'book' | 'idea', id: number, llm: boolean) => {
    const title = target === 'book' ? bookOf(String(id)).title : must(db.ideas.find((x) => x.id === id), '灵感').title
    const items = db.items.filter((x) => x.rank <= 50).slice(0, 60)
    const pick = items.filter((_, i) => i % 7 === 1).slice(0, 5)
    const tropes = [['系统', '囤货', '末世'], ['末世', '经营'], ['系统', '重生'], ['囤货'], ['都市']]
    const similar = pick.map((it, i) => {
      const score = [71, 54, 41, 28, 18][i] ?? 15
      const shared = tropes[i] ?? []
      const overlaps = [...(i === 0 ? [`书名重合：「${it.title.slice(0, 2)}」`] : []), ...(i < 3 ? ['简介用词相近（12%）'] : []), `共同套路：${shared.join('、')}`, ...(shared.includes('系统') ? ['金手指同类：系统'] : []), ...(i < 2 ? [`同题材：${it.category}`] : [])]
      return { rank_item_id: it.id, book_id_ext: it.book_id_ext, title: it.title, author: it.author, category: it.category, rank: it.rank, board: 'read', gender: it.gender, read_count: it.read_count,
        score, overlaps, shared_tropes: shared, title_overlap: i === 0 ? [it.title.slice(0, 2)] : [], abstract: it.abstract.slice(0, 120), ...(llm ? { llm_note: ['都靠系统囤货开局，读者会觉得是同一本书换皮', '经营线相同，但对方没有末世背景', '', '', ''][i] ?? '' } : {}) }
    }).filter((x) => x.score >= 15)
    const mx = similar[0]?.score ?? 0
    return { target: { type: target, id, title }, kind: 'homogeneity', snapshot: { id: 1, taken_at: ago(300), items_compared: items.length, top_n: 50 }, similar, max_score: mx,
      level: mx >= 60 ? 'high' : mx >= 35 ? 'mid' : 'low',
      suggestions: ['「系统」在榜单前列 2 本相似书里都有：保留也行，但要给它加一个别人没有的限制、代价或使用场景', '书名和榜单书有连续重合的字：换掉重合部分，突出本书独有的身份或金手指'],
      llm: llm ? { overall: '撞车主要在「系统 + 囤货」开局；「只换不卖」的规矩和冰封末世的冷感是你独有的，建议在书名和第一章就亮出来。', suggestions: ['书名突出「只换不卖」或「零点补货」，避开「系统」二字', '第一章让规矩先于系统出场：先拒绝一笔大买卖，再揭示补货', '给系统加代价：每次补货都会让超市外的冰层更厚'] } : null }
  }
  const homoRoute = (target: 'book' | 'idea') => (m: RegExpMatchArray, b: any) => {
    const id = +m[1]
    if (b?.llm) return { mode: 'job', job: createJob('homogeneity', target === 'book' ? id : null, 2600, ['比对榜单前列…', '生成差异化建议…'], () => homo(target, id, true), `${target}:${id}`) }
    return { mode: 'sync', report: homo(target, id, false) }
  }
  on('POST', '/books/:id/homogeneity', homoRoute('book'))
  on('POST', '/ideas/:id/homogeneity', homoRoute('idea'))

  // ---------- 演示数据：第 1 本书已开启完本，规划好卷纲，跑过一批；第 2 章有两轮迭代待采纳；做过一次体检和可改编度 ----------
  const s1 = S(1)
  Object.assign(s1, { mode: 'wanben', target_words: 200_000, chapter_words: 2200, batch_size: 6, refine_scope: 'first_n', golden_chapters: 10 })
  const b1 = db.books.find((x) => x.id === 1)
  if (b1) { (b1 as any).mode = 'wanben'; b1.target_words = 200_000; b1.chapter_words = 2200 }
  doPlan(1)
  plans.get(1)!.planned_at = ago(60 * 26)
  const ch1 = chs(1)
  const seedBatch = { id: nid(), book_id: 1, job_id: null, seq: 1, start_no: 1, end_no: 6, status: 'stopped', stop_reason: 'refine_pending', message: '精修范围内第5、6章待审批；审批后继续连写', chapter_ids: ch1.slice(0, 6).map((x) => x.id), created_at: ago(60 * 25), finished_at: ago(60 * 24), report: null as any }
  seedBatch.report = report(1, seedBatch.chapter_ids)
  batches.unshift(seedBatch)
  const c2 = ch1[1]
  if (c2) {
    let base = c2.content ?? ''
    let sb: any = scoreOf(c2)
    for (let r = 1; r <= 2; r++) {
      const content = tweak(base, r, r === 1 ? 'patch' : 'rewrite')
      const sa = { overall: (sb.overall ?? 70) + (r === 1 ? 4 : 2), reader: (sb.reader ?? 5) + (r === 1 ? 1 : 0), passed: true, issues: Math.max(0, (sb.issues ?? 3) - r) }
      iterations.push({ id: nid(), book_id: 1, chapter_id: c2.id, number: c2.number, job_id: null, round: r, method: r === 1 ? 'patch' : 'rewrite', instruction: r === 1 ? '' : '开头再狠一点，第一句就让冲突落地', base_content: base, content, words: c.countWords(content),
        review: c.mkReview(c2.number + r, content), lint: c.mkLint(content), scores: { before: sb, after: sa, delta: { overall: sa.overall - (sb.overall ?? 0), reader: sa.reader - (sb.reader ?? 0) } }, status: 'pending', created_at: ago(90 - r * 20) })
      base = content; sb = sa
    }
  }
  const seedJob = (kind: string, result: any, minsAgo: number) => db.jobs.push({ id: nid(), kind, status: 'succeeded', progress: 100, message: '已完成', result, error: null, book_id: 1, ref: 'book:1', created_at: ago(minsAgo + 2), updated_at: ago(minsAgo), _start: 0, _dur: 0, _steps: [], _done: true } as MJob)
  seedJob('book_check', bookCheck(1, false), 60 * 30)
  seedJob('book_check', bookCheck(1, true), 60 * 3)
  seedJob('adaptability', adapt(1, 1, 6, true), 60 * 2)
}

/** 续跑支持的任务类型（mock） */
export const WANBEN_RESUMABLE = ['wanben_batch', 'wanben_iterate']
