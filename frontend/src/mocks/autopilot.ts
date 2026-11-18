/** v0.16 一键成书 mock：演示一本写到第 2 卷末、等作者选第 3 卷走向的书。 */
import type { AutoDecision, AutoOverview, AutoRun, AutoSettings, Job } from '@/lib/types'

type Ctx = {
  on: (method: string, path: string, h: (m: RegExpMatchArray, body: any, url: URL) => any) => void
  createJob: (kind: string, bookId: number | null, dur: number, steps: string[], fin: () => Record<string, any> | null, ref?: string) => Job
  bookOf: (id: string) => { id: number; title: string; fanfic?: any }
  now: () => string
  ago: (mins: number) => string
  HttpErr: new (status: number, detail: string) => any
}

const DEF: AutoSettings = { level: 'guided', stop_on: ['opening', 'volume'], target_words: 1_200_000, chapter_words: 2000, batch_size: 10, golden_chapters: 10, max_cost_cny: 300 }

export function registerAutoMocks({ on, createJob, bookOf, now, ago, HttpErr }: Ctx) {
  const runs = new Map<number, AutoRun>()
  const decisions = new Map<number, AutoDecision[]>()
  const settings = new Map<number, AutoSettings>()
  const backup: Record<string, string[]> = { writer: [] }

  const seed = (bookId: number) => {
    if (runs.has(bookId) || bookId !== 1) return
    runs.set(bookId, {
      id: 1, status: 'waiting', stage: 'write', stop_reason: 'decision', message: '等你拍板：第2卷写完了，选第3卷走向', job_id: null,
      settings: DEF, stats: { healed: 7, forced: 2, retries: 3, llm_failures: 3, volumes_reviewed: 2 },
      events: [
        { at: ago(2), kind: 'decision', text: '等你拍板：第2卷写完了，选第3卷走向' },
        { at: ago(3), kind: 'review', text: '第2卷复盘完成，发现 1 个问题' },
        { at: ago(9), kind: 'forced', text: '第118章重写后仍没过审，先放行，已记进待看清单' },
        { at: ago(15), kind: 'heal', text: '第117章按审稿问题整章重写，读者分 5 → 7' },
        { at: ago(40), kind: 'retry', text: '连写：渠道出错，1 分钟后重试（HTTP 429: rate limit）' },
        { at: ago(120), kind: 'batch', text: '第111–120章：本批第111–120章写完' },
        { at: ago(600), kind: 'decision', text: '第2卷走向：名动一城（自动按推荐）' },
        { at: ago(1440), kind: 'setup', text: '切到完本模式：120 万字，每章约 2000 字' },
      ],
      flags: [
        { chapter_id: 101, number: 118, title: '夜探城主府', reason: '主角在第 112 章已经知道密道位置，这里又写成第一次发现', at: ago(9), resolved: false, blocking: true },
        { chapter_id: 102, number: 96, title: '擂台第三场', reason: '审稿没过（读者分偏低）', at: ago(300), resolved: false },
      ],
      flags_total: 3,
      guidance: [{ text: '女主第 15 章前登场，感情线慢热', from_chapter: 11, to_chapter: null, source: '开篇确认', at: ago(1300) }],
      started_at: ago(1440), finished_at: null,
    })
    decisions.set(bookId, [
      { id: 3, kind: 'volume', volume: 2, title: '第2卷写完了，选第3卷走向', status: 'pending', choice: null, custom: '', recommended: 0, created_at: ago(2), answered_at: null,
        context: '第2卷前情：林川在青州城一战成名，扳倒城主府，拿到了玉简残篇；和沈家彻底撕破脸，和城主千金苏晚结下交情。\n问题：本卷后半段连续三章都是打脸型爽点，下一卷换换花样',
        options: [
          { title: '第3卷 秘境夺宝', summary: '青云秘境开启，各方天骄云集，林川要抢在沈家之前拿到上古传承', crisis: '沈家联手魔宗堵在秘境出口', closure: '拿到传承杀出重围，秘境深处的旧秘密露出一角', turns: ['大反转：领路的前辈是幕后黑手的人', '金手指升级：玉简能推演两条路'], why: '打怪升级节奏快，换掉连续打脸的节奏' },
          { title: '第3卷 宗门大比', summary: '林川报名宗门大比，一路打上擂台', crisis: '大比被人做了手脚，对手全是硬茬', closure: '大比夺魁，被长老收为亲传', turns: ['感情线定调：苏晚站到林川一边'], why: '擂台打脸，读者熟悉的爽点' },
          { title: '第3卷 北境烽烟', summary: '妖族南下，林川随军北上，在战场上崛起', crisis: '前线被出卖，孤军被围', closure: '守住雁门关，封为校尉，朝堂势力注意到他', turns: ['新的主要角色：女将军登场', '身份揭穿：林川的父亲曾是北境统帅'], why: '换地图换玩法，格局一下打开' },
        ] },
      { id: 2, kind: 'volume', volume: 1, title: '第1卷写完了，选第2卷走向', status: 'auto', choice: 0, custom: '', recommended: 0, created_at: ago(600), answered_at: ago(600), context: '',
        options: [{ title: '第2卷 名动一城', summary: '', turns: [] }] },
      { id: 1, kind: 'opening', volume: 0, title: '开篇 10 章写完了，确认方向', status: 'answered', choice: 0, custom: '女主第 15 章前登场，感情线慢热', recommended: 0, created_at: ago(1300), answered_at: ago(1300), context: '',
        options: [{ title: '开篇没问题，接着写', summary: '', turns: [] }] },
    ])
  }

  const overview = (bookId: number): AutoOverview => {
    seed(bookId)
    const r = runs.get(bookId) ?? null
    const st = settings.get(bookId) ?? r?.settings ?? { ...DEF, level: 'full' }
    const words = r ? 241_380 : 0
    return {
      book_id: bookId, settings: st, run: r, decisions: decisions.get(bookId) ?? [], cost: r ? 86.4 : 0, running: r?.status === 'running', fanfic: !!bookOf(String(bookId)).fanfic,
      progress: r ? {
        book_id: bookId, mode: 'wanben', words, pending_words: 0, target_words: st.target_words, ratio: words / st.target_words,
        chapters_committed: 120, chapters_written: 120, chapters_total: 600, chapters_remaining: 480,
        current_volume: { order: 3, title: '待定', start: 121, end: 180, node_id: 3 }, planned: true, paused: false, running_batch_id: null, last_batch: null,
      } as any : null,
      recaps: r ? [
        { order: 1, title: '杂役翻身', text: '林川从外门杂役一路打进内门，拿到会推演的残破玉简，结下沈家这门仇。', state: ['林川：炼气七层，内门弟子', '玉简：已认主，每天能推演一次'], problems: [] },
        { order: 2, title: '名动一城', text: '林川在青州城一战成名，扳倒城主府，拿到了玉简残篇；和沈家彻底撕破脸，和城主千金苏晚结下交情。', state: ['林川：筑基初期', '苏晚：欠林川一条命'], problems: ['本卷后半段连续三章都是打脸型爽点'] },
      ] : [],
    }
  }

  on('GET', '/books/:id/autopilot', (m) => overview(bookOf(m[1]).id))
  on('PUT', '/books/:id/autopilot/settings', (m, b) => { const id = bookOf(m[1]).id; const s = { ...overview(id).settings, ...b }; settings.set(id, s); return s })
  on('POST', '/books/:id/autopilot/start', (m, b) => {
    const id = bookOf(m[1]).id
    const s = { ...overview(id).settings, ...(b || {}) }
    settings.set(id, s)
    const r = runs.get(id) ?? { id: id * 10, status: 'running', stage: 'setup', stop_reason: '', message: '', job_id: null, settings: s, stats: {}, events: [], flags: [], flags_total: 0, guidance: [], started_at: now(), finished_at: null } as AutoRun
    if ((decisions.get(id) ?? []).some((d) => d.status === 'pending')) throw new HttpErr(409, '还有待拍板的决策点，先选一个走向')
    Object.assign(r, { status: 'running', message: '', settings: s, events: [{ at: now(), kind: 'start', text: '开始一键成书' }, ...r.events] })
    runs.set(id, r)
    const job = createJob('autopilot', id, 4000, ['准备设定', '规划卷纲', '连写'], () => { r.status = 'paused'; r.stage = 'write'; r.message = '演示：写了一批停下'; return { status: 'paused' } }, `autopilot:${id}`)
    r.job_id = job.id
    return { run_id: r.id, job }
  })
  on('POST', '/books/:id/autopilot/pause', (m) => { const r = runs.get(bookOf(m[1]).id); if (r && r.status === 'running') { r.status = 'paused'; r.message = '已暂停' } return { ok: true, running: false } })
  on('POST', '/books/:id/autopilot/decisions/:did', (m, b) => {
    const id = bookOf(m[1]).id
    const d = (decisions.get(id) ?? []).find((x) => x.id === +m[2])
    if (!d) throw new HttpErr(404, '决策点不存在')
    Object.assign(d, { status: 'answered', choice: b.choice, custom: b.custom || '', answered_at: now() })
    const r = runs.get(id)!
    if (b.custom) r.guidance = [...r.guidance, { text: b.custom, from_chapter: 121, to_chapter: 180, source: '第3卷', at: now() }]
    Object.assign(r, { status: 'running', message: '' })
    const job = createJob('autopilot', id, 4000, ['连写'], () => { r.status = 'paused'; r.message = '演示：写了一批停下'; return { status: 'paused' } }, `autopilot:${id}`)
    return { run_id: r.id, job_id: job.id }
  })
  on('POST', '/books/:id/autopilot/flags/:cid/resolve', (m) => { const r = runs.get(bookOf(m[1]).id); if (r) r.flags = r.flags.filter((f) => f.chapter_id !== +m[2]); return { ok: true } })
  on('POST', '/books/:id/autopilot/flags/:cid/accept', (m) => {
    const id = bookOf(m[1]).id
    return createJob('autopilot_accept', id, 800, ['提交入账'], () => { const r = runs.get(id); if (r) r.flags = r.flags.filter((f) => f.chapter_id !== +m[2]); return { ok: true, chapter_id: +m[2] } })
  })
  on('POST', '/books/:id/autopilot/flags/:cid/replan', (m) => {
    const id = bookOf(m[1]).id
    return createJob('autopilot_replan', id, 1500, ['章纲衔接校正', '整章重写'], () => { const r = runs.get(id); if (r) r.flags = r.flags.filter((f) => f.chapter_id !== +m[2]); return { result: 'committed' } })
  })
  on('GET', '/settings/routing/backup', () => backup)
  on('PUT', '/settings/routing/backup', (_m, b) => Object.assign(backup, b))
  on('POST', '/fanfic/idea/rewrite', (_m, b) => ({
    text: `主角以原创身份切入原著开篇，带着一个只有他知道的秘密混进主角团。\n\n他不抢原著主角的风头，而是在几场关键战斗里换了打法，把原本输掉的局一点点扳回来，人物关系也跟着重新洗牌。\n\n长线目标是查清原著里没说透的一桩旧案，对手是藏在幕后的那位大人物；每一卷都有一次明面上的胜利，暗线一步步逼近真相。${b?.instruction ? `\n\n（按要求：${b.instruction}）` : ''}`,
  }))
}
