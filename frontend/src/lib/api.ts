import type {
  AutoOverview, AutoSettings, RoutingBackup,
  AgentMessage, AgentProposal, AgentSession, AgentSessionDetail, AgentToolInfo,
  BibleOp, BibleSnapshot, BookInfo, ForeshadowOverview, ForeshadowPlanItem, Impact, Trope,
  Book, Card, CardType, CardVersion, Channel, ChannelInput, Chapter, Fact, Foreshadow, Gender, Idea, IdeaField, Job,
  OutlineNode, Package, RadarConfig, RadarSnapshot, RankBoard, RankItem, Routing, Teardown, Style, TrendTopic, WritingSettings,
  BookTest, BookTestField, BookTestVariant, PlatformStyle, TrendReport, RadarAiKind, RadarBookDetail, ZhuqueSettings, ZhuqueSettingsInput,
  IdeaSeed, FusionRef, ImitateExtract, RadarReportConfig,
  Completeness, OnboardingState, OnboardingKey, FieldAiMode, RefEntry, Estimate, EstimateKind, BookUsage, TeardownRecord, TeardownListItem, TeardownSourceType, TeardownBiblePart, ApprovalMode,
  Budget, Generation, GenerationList, ImportPreview, AdoptStatus,
  BatchInput, Spark, FreqItem, SearchResult, SearchScope, Note, ContextPreview,
  SparkTrack, SparkSessionData, SparkAxis, SparkProposal,
} from './types'

export interface ApiKey { id: string; name: string; preview: string; created_at: number; last_used_at: number | null }
export interface AuthStatus { enabled: boolean; authenticated: boolean; username: string; managed_by_env: boolean; min_password_len: number }

/** 502/504/524：通常是 Cloudflare / Nginx 等反向代理等不及后端（模型生成慢）先断开了，后端任务可能还在跑 */
export const PROXY_TIMEOUT_MSG = '服务器等待模型超时（可能被 Cloudflare 等代理截断），任务可能仍在后台运行'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function qs(params: Record<string, string | number | boolean | undefined | null>) {
  const s = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') s.set(k, String(v))
  const str = s.toString()
  return str ? `?${str}` : ''
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  let res: Response
  const form = typeof FormData !== 'undefined' && body instanceof FormData
  try {
    res = await fetch(`/api${url}`, {
      method,
      credentials: 'same-origin',
      headers: body !== undefined && !form ? { 'Content-Type': 'application/json' } : undefined,
      body: body === undefined ? undefined : form ? (body as FormData) : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(0, '无法连接到后端服务，请确认 NovelOS 后端已启动')
  }
  if (!res.ok) {
    let msg = `请求失败（${res.status}）`
    try {
      const j = await res.json()
      if (j?.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch { /* ignore */ }
    if (res.status === 502 || res.status === 504 || res.status === 524) msg = PROXY_TIMEOUT_MSG
    if (res.status === 401 && !url.startsWith('/auth/')) window.dispatchEvent(new Event('novelos:unauthorized'))
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

/** 后端返回的相对资源路径（如 /api/radar/cover/x）转成可直接用的地址；与 request 同源同 /api 前缀，cookie 鉴权自动带上 */
export function assetUrl(path?: string | null): string | null {
  if (!path) return null
  if (/^(https?:|data:|blob:)/.test(path)) return path
  if (path.startsWith('/api/')) return path
  return `/api${path.startsWith('/') ? '' : '/'}${path}`
}

const get = <T,>(u: string) => request<T>('GET', u)
const post = <T,>(u: string, b?: unknown) => request<T>('POST', u, b ?? {})
const put = <T,>(u: string, b: unknown) => request<T>('PUT', u, b)
const patch = <T,>(u: string, b: unknown) => request<T>('PATCH', u, b)
const del = <T,>(u: string) => request<T>('DELETE', u)
/** v0.9.1 部分接口只返回 {job_id}：取一次 Job，好交给 useJobs().start 轮询 */
async function viaJobId(p: Promise<{ job_id: number } | Job>): Promise<Job> {
  const r = await p as any
  if (r && typeof r.status === 'string' && typeof r.id === 'number') return r as Job
  const id = Number(r?.job_id ?? r?.id)
  if (!id) throw new ApiError(500, '后端没有返回任务编号')
  return get<Job>(`/jobs/${id}`)
}

export const api = {
  health: () => get<{ status: string; version: string }>('/health'),

  authStatus: () => get<AuthStatus>('/auth/status'),
  login: (password: string, remember: boolean) => post<{ ok: boolean }>('/auth/login', { password, remember }),
  logout: () => post<{ ok: boolean }>('/auth/logout'),
  changePassword: (current: string, next: string) => post<{ ok: boolean }>('/auth/password', { current, new: next }),
  apiKeys: () => get<{ keys: ApiKey[]; env_key_enabled: boolean }>('/auth/keys'),
  createApiKey: (name: string) => post<ApiKey & { token: string }>('/auth/keys', { name }),
  revokeApiKey: (id: string) => del<{ ok: boolean }>(`/auth/keys/${id}`),

  jobs: (bookId?: number) => get<Job[]>(`/jobs${qs({ book_id: bookId })}`),
  job: (id: number) => get<Job>(`/jobs/${id}`),

  status: () => get<{ mock_mode: boolean }>('/settings/status'),
  channels: () => get<Channel[]>('/settings/channels'),
  createChannel: (b: ChannelInput) => post<Channel>('/settings/channels', b),
  updateChannel: (id: number, b: Partial<ChannelInput>) => put<Channel>(`/settings/channels/${id}`, b),
  deleteChannel: (id: number) => del<void>(`/settings/channels/${id}`),
  fetchModels: (b: { base_url: string; api_key?: string; channel_id?: number; api_format?: string }) => post<{ models: string[] }>('/settings/models/fetch', b),
  testChannel: (id: number) => post<{ ok: boolean; latency_ms: number; error?: string }>(`/settings/channels/${id}/test`),
  routing: () => get<Routing>('/settings/routing'),
  saveRouting: (b: Routing) => put<Routing>('/settings/routing', b),
  routingBackup: () => get<RoutingBackup>('/settings/routing/backup'),
  saveRoutingBackup: (b: RoutingBackup) => put<RoutingBackup>('/settings/routing/backup', b),

  /** 合约增补“默认设置可选自动采纳最高分”的落点（后端已实现 /settings/writing） */
  writingSettings: () => get<WritingSettings>('/settings/writing'),
  saveWritingSettings: (b: Partial<WritingSettings>) => put<WritingSettings>('/settings/writing', b),

  radarRefresh: () => post<Job>('/radar/refresh'),
  radarSnapshots: () => get<RadarSnapshot[]>('/radar/snapshots'),
  radarLatest: (p: { gender?: Gender; category?: string; board?: RankBoard }) =>
    get<{ snapshot: RadarSnapshot | null; items: RankItem[]; boards?: RankBoard[] }>(`/radar/latest${qs(p)}`),
  /** board 不传时两类榜合并统计 */
  radarTrends: (gender?: Gender, board?: RankBoard) => get<TrendTopic[]>(`/radar/trends${qs({ gender, board })}`),
  // v0.9：风向标日报（生成走 Job，kind=radar_report）
  /** v0.9.2：GET /radar/report/latest?scope=；后端还没这个路由（FastAPI 默认 404 Not Found）时退回 v0.9 的 /radar/report */
  radarReport: async (scope = 'overall') => {
    try {
      return await get<TrendReport>(`/radar/report/latest${qs({ scope })}`)
    } catch (e) {
      if (e instanceof ApiError && (e.status === 405 || (e.status === 404 && /^(Not Found|请求失败)/.test(e.message)))) return get<TrendReport>(`/radar/report${qs({ scope })}`)
      throw e
    }
  },
  radarReports: (p: { limit?: number; scope?: string; full?: boolean } = {}) => get<TrendReport[]>(`/radar/reports${qs(p)}`),
  generateRadarReport: (b: { scope?: string; top_n?: number } = {}) => post<Job & { job_id?: number }>('/radar/report', b),
  radarConfig: () => get<RadarConfig>('/radar/config'),
  /** v0.9.2：风向标读取本数与自动生成范围（独立接口，局部更新） */
  radarReportConfig: () => get<RadarReportConfig>('/radar/report/config'),
  saveRadarReportConfig: (b: Partial<RadarReportConfig>) => put<RadarReportConfig>('/radar/report/config', b),
  saveRadarConfig: (b: RadarConfig) => put<RadarConfig>('/radar/config', b),
  // v0.7：榜单仿写（同步接口）
  teardown: (itemId: number) => get<Teardown>(`/radar/items/${itemId}/teardown`),
  /** v0.7.1 起以下三个都是任务接口：立即返回 Job，结果在 Job.result（拆解为 Teardown，换皮为 ReskinResult） */
  runTeardown: (itemId: number, refresh = false) => post<Job>(`/radar/items/${itemId}/teardown${qs({ refresh: refresh || undefined })}`),
  deepTeardown: (itemId: number, text: string) => post<Job>(`/radar/items/${itemId}/deep`, { text }),
  reskin: (itemId: number) => post<Job>(`/radar/items/${itemId}/reskin`),
  // v0.9.1：书架卡片详情 + 书名/封面词/简介候选（任务）
  radarBookDetail: (ext: string) => get<RadarBookDetail>(`/radar/books/${encodeURIComponent(ext)}/detail`),
  radarBookAi: (ext: string, kind: RadarAiKind, n?: number) => viaJobId(post(`/radar/books/${encodeURIComponent(ext)}/ai`, { kind, ...(n ? { n } : {}) })),
  // v0.9.1：腾讯朱雀 AIGC 检测。设置是独立接口；检测都是任务：/detect/aigc 的 result = Aigc，章节检测的 result = {chapter_id, aigc}
  zhuqueSettings: () => get<ZhuqueSettings>('/settings/zhuque'),
  saveZhuqueSettings: (b: ZhuqueSettingsInput) => put<ZhuqueSettings>('/settings/zhuque', b),
  detectAigc: (text: string, is_merge?: boolean) => viaJobId(post('/detect/aigc', { text, ...(is_merge !== undefined ? { is_merge } : {}) })),
  chapterAigc: (bookId: number, chapterId: number) => viaJobId(post(`/books/${bookId}/chapters/${chapterId}/aigc`)),
  /** v0.9.1：语感重塑（任务） */
  polishVoice: (bookId: number, chapterId: number) => viaJobId(post(`/books/${bookId}/chapters/${chapterId}/polish-voice`)),
  /** 这本书的仿写任务（新的在前），面板重新打开时用来找回进行中的任务和上次的结果 */
  itemJobs: (itemId: number) => get<Job[]>(`/radar/items/${itemId}/jobs`),

  books: () => get<Book[]>('/books'),
  book: (id: number) => get<Book>(`/books/${id}`),
  createBook: (b: { title?: string; genre: string; gender: Gender; premise?: string; platform_style?: PlatformStyle }) => post<Book>('/books', b),
  updateBook: (id: number, b: Partial<Book>) => patch<Book>(`/books/${id}`, b),
  deleteBook: (id: number) => del<void>(`/books/${id}`),

  // v0.9.2 立项向导
  /** expand=false：同步存为选题，返回 {idea} */
  ideaFromSeed: (b: IdeaSeed) => post<{ idea: Idea }>('/ideas/from-seed', { ...b, expand: false }),
  /** expand=true：后台补全再存，Job.result = {idea} */
  ideaFromSeedJob: (b: IdeaSeed) => viaJobId(post('/ideas/from-seed', { ...b, expand: true })),
  organizeIdea: (b: { text: string; genre?: string; gender?: Gender }) => viaJobId(post('/ideas/organize', b)),
  /** Job.result = {ideas, dropped, warnings} */
  fusionIdeas: (b: { refs: FusionRef[]; notes?: string; n?: number }) => viaJobId(post('/ideas/fusion', b)),
  /** 上传 TXT（multipart file）或 {text}：识别章节 */
  imitateExtract: (src: File | string) => {
    if (typeof src === 'string') return post<ImitateExtract>('/radar/imitate/extract', { text: src })
    const fd = new FormData(); fd.append('file', src)
    return request<ImitateExtract>('POST', '/radar/imitate/extract', fd)
  },
  /** v0.12 导入已有作品：上传 TXT/MD/DOCX 或粘贴 → 预览；commit 建书；adopt 接管（Job） */
  importPreview: (src: File | string) => {
    if (typeof src === 'string') return post<ImportPreview>('/books/import', { text: src })
    const fd = new FormData(); fd.append('file', src)
    return request<ImportPreview>('POST', '/books/import', fd)
  },
  importCommit: (b: { import_id: string; title: string; genre?: string; gender?: Gender; tagline?: string; skip?: number[] }) =>
    post<{ book_id: number; chapters: number; words: number }>('/books/import/commit', b),
  adoptBook: (bookId: number, steps?: string[]) => post<Job>(`/books/${bookId}/adopt`, steps ? { steps } : {}),
  adoptStatus: (bookId: number) => get<AdoptStatus>(`/books/${bookId}/adopt`),
  generateIdeas: (b: { genre?: string; gender?: Gender; from_trends: boolean; count: number }) => post<Job>('/ideas/generate', b),
  ideas: () => get<Idea[]>('/ideas'),
  deleteIdea: (id: number) => del<{ ok: boolean }>(`/ideas/${id}`),
  clearIdeas: () => post<{ deleted: number }>('/ideas/clear'),
  adoptIdea: (id: number) => post<Book>(`/ideas/${id}/adopt`),
  reviseIdea: (id: number, b: { instruction: string; route?: string | null }) => post<Job>(`/ideas/${id}/revise`, b),
  undoIdea: (id: number) => post<Idea>(`/ideas/${id}/undo`),
  idea: (id: number) => get<Idea>(`/ideas/${id}`),
  updateIdea: (id: number, b: Partial<Record<IdeaField, string | string[]>>) => patch<Idea>(`/ideas/${id}`, b),
  suggestIdeaField: (id: number, b: { field: IdeaField; instruction: string; route?: string | null; draft?: Record<string, unknown> }) => post<Job>(`/ideas/${id}/suggest`, b),
  rescoreAllIdeas: () => post<Job>('/ideas/rescore'),
  rescoreIdea: (id: number) => post<Job>(`/ideas/${id}/rescore`),

  generateBible: (bookId: number) => post<Job>(`/books/${bookId}/bible/generate`),
  cards: (bookId: number, type?: CardType) => get<Card[]>(`/books/${bookId}/cards${qs({ type })}`),
  createCard: (bookId: number, b: Partial<Card>) => post<Card>(`/books/${bookId}/cards`, b),
  updateCard: (id: number, b: Partial<Card>) => put<Card>(`/cards/${id}`, b),
  deleteChapter: (id: number) => del<{ ok: boolean }>(`/chapters/${id}`),
  deleteCard: (id: number) => del<void>(`/cards/${id}`),
  cardVersions: (id: number) => get<CardVersion[]>(`/cards/${id}/versions`),
  restoreCardVersion: (id: number, n: number) => post<Card>(`/cards/${id}/versions/${n}/restore`),
  facts: (bookId: number) => get<Fact[]>(`/books/${bookId}/facts`),

  generateOutline: (bookId: number) => post<Job>(`/books/${bookId}/outline/generate`),
  expandOutline: (nodeId: number) => post<Job>(`/outline/${nodeId}/expand`),
  outline: (bookId: number) => get<OutlineNode[]>(`/books/${bookId}/outline`),
  deleteOutline: (nodeId: number) => del<{ deleted: number }>(`/outline/${nodeId}`),
  updateOutline: (nodeId: number, b: Partial<OutlineNode> & { instruction?: string }) => put<OutlineNode>(`/outline/${nodeId}`, b),

  chapters: (bookId: number) => get<Chapter[]>(`/books/${bookId}/chapters`),
  chapter: (id: number) => get<Chapter>(`/chapters/${id}`),
  saveChapter: (id: number, b: { title: string; content: string }) => put<Chapter>(`/chapters/${id}`, b),
  writeNext: (bookId: number, variants: 1 | 2 | 3 = 1) => post<Job>(`/books/${bookId}/chapters/write-next`, { variants }),
  writeBatch: (bookId: number, count: number) => post<Job>(`/books/${bookId}/chapters/write-batch`, { count }),
  reviewChapter: (id: number) => post<Job>(`/chapters/${id}/review`),
  humanizeChapter: (id: number) => post<Job>(`/chapters/${id}/humanize`),
  thickenChapter: (id: number) => post<Job>(`/chapters/${id}/thicken`),
  adoptVariant: (id: number, variantId: number) => post<Chapter>(`/chapters/${id}/adopt-variant`, { variant_id: variantId }),
  /** v0.9：按下标应用审稿补丁（同步，不调模型；旧正文进历史可 undo） */
  applyReviewPatches: (id: number, indices: number[]) =>
    post<{ chapter: Chapter; applied: { index: number; original: string; improved: string }[]; skipped: { index: number; reason: string }[] }>(`/chapters/${id}/review/patches/apply`, { indices }),
  /** v0.7.1 起是任务接口（要调模型生成摘要），result = { chapter_id, number, chapter } */
  commitChapter: (id: number) => post<Job>(`/chapters/${id}/commit`),

  style: (bookId: number) => get<Style>(`/books/${bookId}/style`),
  saveStyle: (bookId: number, b: Partial<Style>) => put<Style>(`/books/${bookId}/style`, b),
  extractStyle: (bookId: number) => post<Job>(`/books/${bookId}/style/extract`),

  foreshadows: (bookId: number) => get<Foreshadow[]>(`/books/${bookId}/foreshadows`),
  foreshadowOverview: (bookId: number) => get<ForeshadowOverview>(`/books/${bookId}/foreshadows/overview`),
  createForeshadow: (bookId: number, b: Partial<Foreshadow>) => post<Foreshadow>(`/books/${bookId}/foreshadows`, b),
  updateForeshadow: (id: number, b: Partial<Foreshadow>) => put<Foreshadow>(`/foreshadows/${id}`, b),
  deleteForeshadow: (id: number) => del<{ ok: boolean }>(`/foreshadows/${id}`),
  planForeshadows: (bookId: number, b: { instruction: string; route?: string | null; count?: number }) => post<Job>(`/books/${bookId}/foreshadows/plan`, b),
  addForeshadows: (bookId: number, b: { items: (ForeshadowPlanItem & { source?: string })[]; attach: boolean }) => post<{ created: number; attached: number }>(`/books/${bookId}/foreshadows/batch`, b),

  // v0.4：按要求让 AI 改
  reviseBook: (bookId: number, b: { instruction: string; route?: string | null }) => post<Job>(`/books/${bookId}/revise`, b),
  applyBookInfo: (bookId: number, b: Partial<BookInfo> & { instruction: string }) => post<Book>(`/books/${bookId}/info`, b),
  undoBook: (bookId: number) => post<Book>(`/books/${bookId}/undo`),
  bookImpact: (bookId: number, terms: string[]) => post<Impact>(`/books/${bookId}/impact`, { terms }),
  syncBook: (bookId: number, b: { instruction: string; terms: string[]; replacements: Record<string, string>; targets?: ('bible' | 'outline')[]; route?: string | null }) => post<Job>(`/books/${bookId}/sync`, b),
  proposeBible: (bookId: number, b: { mode: 'rewrite' | 'add' | 'optimize'; instruction: string; route?: string | null }) => post<Job>(`/books/${bookId}/bible/propose`, b),
  applyBible: (bookId: number, b: { mode: string; instruction: string; ops: BibleOp[]; facts?: any[] }) => post<{ created: number; updated: number; deleted: number; snapshot_id: number }>(`/books/${bookId}/bible/apply`, b),
  bibleSnapshots: (bookId: number) => get<BibleSnapshot[]>(`/books/${bookId}/bible/snapshots`),
  restoreBible: (bookId: number, sid: number) => post<{ restored: number; snapshot_id: number }>(`/books/${bookId}/bible/snapshots/${sid}/restore`),
  suggestOutline: (nodeId: number, b: { instruction: string; route?: string | null }) => post<Job>(`/outline/${nodeId}/suggest`, b),
  undoOutline: (nodeId: number) => post<OutlineNode>(`/outline/${nodeId}/undo`),
  applyOutline: (bookId: number, b: { instruction: string; items: { node_id: number; title?: string; summary?: string; beats?: Record<string, any> }[] }) => post<{ updated: number }>(`/books/${bookId}/outline/apply`, b),
  rewriteChapter: (id: number, b: { instruction: string; route?: string | null; scope: 'all' | 'selection'; start?: number; end?: number }) => post<Job>(`/chapters/${id}/rewrite`, b),
  applyRewrite: (id: number, b: { content: string; label?: string }) => post<Chapter>(`/chapters/${id}/apply-rewrite`, b),
  undoChapter: (id: number) => post<Chapter>(`/chapters/${id}/undo`),
  detropeIdea: (id: number, b: { route?: string | null }) => post<Job>(`/ideas/${id}/detrope`, b),
  tropes: () => get<{ banned: Trope[]; defaults: Trope[] }>('/settings/tropes'),
  saveTropes: (banned: Trope[]) => put<{ banned: Trope[]; defaults: Trope[] }>('/settings/tropes', { banned }),

  // v0.9：书测（生成走 Job，kind=book_test）
  bookTest: (bookId: number) => get<BookTest>(`/books/${bookId}/book-test`),
  generateBookTest: (bookId: number) => post<Job>(`/books/${bookId}/book-test`),
  adoptBookTest: (bookId: number, b: { index: number; fields?: BookTestField[] }) =>
    post<{ book: Book; package: Package; adopted: { index: number; variant: BookTestVariant; applied: BookTestField[]; before: Record<string, any>; after: Record<string, any> } }>(`/books/${bookId}/book-test/adopt`, b),

  generatePackage: (bookId: number) => post<Job>(`/books/${bookId}/package/generate`),
  reviseCoverPrompt: (bookId: number, b: { instruction: string; current?: string; route?: string | null }) => post<Job>(`/books/${bookId}/covers/prompt`, b),
  deleteCover: (bookId: number, url: string) => post<Package>(`/books/${bookId}/covers/delete`, { url }),
  suggestCard: (bookId: number, b: { card_id: number | null; field: string | null; instruction: string; route?: string | null; draft: Record<string, any> }) => post<Job>(`/books/${bookId}/cards/suggest`, b),
  generateCovers: (bookId: number, b: { prompt?: string; n?: number; title_mode?: 'model' | 'overlay' }) => post<Job>(`/books/${bookId}/covers/generate`, b),
  package: (bookId: number) => get<Package>(`/books/${bookId}/package`),
  savePackage: (bookId: number, b: Partial<Package>) => put<Package>(`/books/${bookId}/package`, b),

  // v0.5：每本书的专属 Agent
  agentTools: () => get<{ tools: AgentToolInfo[]; max_steps: number; examples: string[] }>('/agent/tools'),
  agentSettings: (bookId: number) => get<{ auto_apply: boolean }>(`/books/${bookId}/agent/settings`),
  saveAgentSettings: (bookId: number, auto_apply: boolean) => put<{ auto_apply: boolean; book: Book }>(`/books/${bookId}/agent/settings`, { auto_apply }),
  agentSessions: (bookId: number) => get<AgentSession[]>(`/books/${bookId}/agent/sessions`),
  createAgentSession: (bookId: number, title?: string) => post<AgentSession>(`/books/${bookId}/agent/sessions`, { title }),
  agentSession: (sid: number) => get<AgentSessionDetail>(`/agent/sessions/${sid}`),
  renameAgentSession: (sid: number, title: string) => patch<AgentSession>(`/agent/sessions/${sid}`, { title }),
  clearAgentSession: (sid: number) => post<AgentSession>(`/agent/sessions/${sid}/clear`),
  deleteAgentSession: (sid: number) => del<{ ok: boolean }>(`/agent/sessions/${sid}`),
  sendAgent: (sid: number, b: { content: string; route?: string | null }) => post<{ message: AgentMessage; job: Job }>(`/agent/sessions/${sid}/messages`, b),
  stopAgent: (sid: number) => post<AgentSession>(`/agent/sessions/${sid}/stop`),
  applyProposal: (pid: number, b?: { edited?: Record<string, any>; ops?: BibleOp[] }) => post<{ proposal: AgentProposal; job: Job | null }>(`/agent/proposals/${pid}/apply`, b ?? {}),
  rejectProposal: (pid: number) => post<AgentProposal>(`/agent/proposals/${pid}/reject`),
  revertProposal: (pid: number) => post<AgentProposal>(`/agent/proposals/${pid}/revert`),

  // ---------- v0.9.3 ----------
  completeness: (bookId: number) => get<Completeness>(`/books/${bookId}/completeness`),
  /** 完整度 / 待办里 action.type=job 的 target（形如 /api/books/1/bible/generate）：空 body POST，返回 Job */
  postJobPath: (target: string) => viaJobId(post(target.replace(/^\/api(?=\/)/, ''))),
  onboarding: () => get<OnboardingState>('/onboarding'),
  saveOnboarding: (b: { steps?: Partial<Record<OnboardingKey, boolean>>; dismissed?: boolean }) => put<OnboardingState>('/onboarding', b),
  /** 设定库管理页带上已弃用条目 */
  allCards: (bookId: number) => get<Card[]>(`/books/${bookId}/cards${qs({ include_deprecated: true })}`),
  /** 字段级 AI：只给建议值，Job.result = FieldAiResult */
  fieldAi: (bookId: number, entryId: number, b: { field: string; mode: FieldAiMode; instruction?: string; route?: string | null }) =>
    viaJobId(post(`/books/${bookId}/bible/${entryId}/field-ai`, b)),
  applyFieldAi: (bookId: number, entryId: number, b: { field: string; value: unknown }) => post<Card>(`/books/${bookId}/bible/${entryId}/field-ai/apply`, b),
  refs: (bookId: number, q: string, limit = 20) => get<RefEntry[]>(`/books/${bookId}/refs${qs({ q, limit })}`),
  /** 人物灵魂五维：Job.result = SoulResult（不写库，采纳走 PUT /cards/{id} {soul}） */
  soulAi: (bookId: number, entryId: number, b: { mode?: 'fill' | 'rewrite'; instruction?: string; route?: string | null } = {}) =>
    viaJobId(post(`/books/${bookId}/characters/${entryId}/soul`, b)),
  setApprovalMode: (bookId: number, mode: ApprovalMode) => patch<Book>(`/books/${bookId}`, { approval_mode: mode }),
  estimate: (b: { kind: EstimateKind; book_id?: number; chapter_id?: number; words?: number }) => post<Estimate>('/estimate', b),
  usage: (bookId: number) => get<BookUsage>(`/books/${bookId}/usage`),
  /** v0.12 生成档案 */
  generations: (p: { book_id?: number; kind?: string; status?: string; q?: string; starred?: boolean; days?: number; limit?: number; offset?: number } = {}) =>
    get<GenerationList>(`/generations${qs({ ...p, starred: p.starred || undefined })}`),
  generation: (id: number) => get<Generation>(`/generations/${id}`),
  patchGeneration: (id: number, b: { starred?: boolean }) => patch<Generation>(`/generations/${id}`, b),
  deleteGeneration: (id: number) => del<{ ok: boolean }>(`/generations/${id}`),
  followupGeneration: (id: number, b: { instruction: string; route?: string | null }) => post<Job>(`/generations/${id}/followup`, b),
  budget: (bookId?: number) => get<Budget>(`/settings/budget${qs({ book_id: bookId })}`),
  saveBudget: (b: { daily_cny: number; book_cny: number }) => put<Budget>('/settings/budget', b),
  teardowns: () => get<TeardownListItem[]>('/teardowns'),
  teardownDetail: (id: number) => get<TeardownRecord>(`/teardowns/${id}`),
  /** Job.result = {teardown, teardown_id} */
  createTeardown: (b: { source: TeardownSourceType; book_id_ext?: string; text?: string; title?: string }) => viaJobId(post('/teardowns', b)),
  deleteTeardown: (id: number) => del<{ ok: boolean }>(`/teardowns/${id}`),
  /** expand=true：Job（idea_seed），result = {idea, idea_id} */
  teardownToIdeaJob: (id: number, notes?: string) => viaJobId(post(`/teardowns/${id}/to-idea`, { expand: true, ...(notes ? { notes } : {}) })),
  teardownToIdea: (id: number, notes?: string) => post<{ idea: Idea }>(`/teardowns/${id}/to-idea`, { expand: false, ...(notes ? { notes } : {}) }),
  teardownToBible: (id: number, b: { book_id: number; parts: TeardownBiblePart[] }) => post<{ cards: Card[]; warnings: string[]; skipped: number }>(`/teardowns/${id}/to-bible`, b),

  /** 以 Blob 方式下载发布包（兼容 mock 与真实后端） */
  async exportBook(bookId: number, filename: string) {
    let res: Response
    try {
      res = await fetch(`/api/books/${bookId}/export`, { credentials: 'same-origin' })
    } catch {
      throw new ApiError(0, '无法连接到后端服务')
    }
    if (!res.ok) {
      let msg = `导出失败（${res.status}）`
      try { const j = await res.json(); if (j?.detail) msg = j.detail } catch { /* ignore */ }
      throw new ApiError(res.status, msg)
    }
    const cd = res.headers.get('Content-Disposition') || ''
    const m = /filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i.exec(cd)
    const name = m ? decodeURIComponent(m[1] || m[2]) : filename
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  },
}

export const qk = {
  auth: ['auth'] as const,
  apiKeys: ['auth', 'keys'] as const,
  status: ['status'] as const,
  channels: ['channels'] as const,
  routing: ['routing'] as const,
  writing: ['writing-settings'] as const,
  jobs: (bookId?: number) => ['jobs', bookId ?? 'all'] as const,
  job: (id: number) => ['job', id] as const,
  radarLatest: (gender?: string, category?: string, board?: string) => ['radar', 'latest', gender ?? '', category ?? '', board ?? ''] as const,
  radarTrends: (gender?: string, board?: string) => ['radar', 'trends', gender ?? '', board ?? ''] as const,
  radarReport: (scope: string) => ['radar', 'report', scope] as const,
  radarReports: ['radar', 'reports'] as const,
  bookTest: (bookId: number) => ['book-test', bookId] as const,
  radarSnapshots: ['radar', 'snapshots'] as const,
  radarConfig: ['radar', 'config'] as const,
  radarReportConfig: ['radar', 'report-config'] as const,
  teardown: (itemId: number) => ['radar', 'teardown', itemId] as const,
  radarBookDetail: (ext: string) => ['radar', 'book-detail', ext] as const,
  zhuque: ['settings', 'zhuque'] as const,
  itemJobs: (itemId: number) => ['radar', 'jobs', itemId] as const,
  books: ['books'] as const,
  book: (id: number) => ['book', id] as const,
  ideas: ['ideas'] as const,
  idea: (id: number) => ['ideas', id] as const,
  cards: (bookId: number) => ['cards', bookId] as const,
  facts: (bookId: number) => ['facts', bookId] as const,
  outline: (bookId: number) => ['outline', bookId] as const,
  chapters: (bookId: number) => ['chapters', bookId] as const,
  chapter: (id: number) => ['chapter', id] as const,
  foreshadows: (bookId: number) => ['foreshadows', bookId] as const,
  package: (bookId: number) => ['package', bookId] as const,
  style: (bookId: number) => ['style', bookId] as const,
  foreshadowOverview: (bookId: number) => ['foreshadows', bookId, 'overview'] as const,
  bibleSnapshots: (bookId: number) => ['cards', bookId, 'snapshots'] as const,
  tropes: ['tropes'] as const,
  agentTools: ['agent', 'tools'] as const,
  agentSessions: (bookId: number) => ['agent', 'sessions', bookId] as const,
  agentSession: (sid: number) => ['agent', 'session', sid] as const,
  completeness: (bookId: number) => ['completeness', bookId] as const,
  onboarding: ['onboarding'] as const,
  refs: (bookId: number, q: string) => ['refs', bookId, q] as const,
  usage: (bookId: number) => ['usage', bookId] as const,
  teardowns: ['teardowns'] as const,
  teardownDetail: (id: number) => ['teardowns', id] as const,
}

// ---------- v0.9.4：任务续跑、书级写作设置（追加，避免与并行改动冲突） ----------
type BookWritingSettings = import('./types').BookWritingSettings
type BookWritingSettingsInput = import('./types').BookWritingSettingsInput
export const apiV094 = {
  /** 409：不可续跑（状态不对 / 不支持 / 没断点）；404：任务不存在 */
  resumeJob: (id: number) => post<Job>(`/jobs/${id}/resume`),
  bookWritingSettings: (bookId: number) => get<BookWritingSettings>(`/books/${bookId}/writing-settings`),
  saveBookWritingSettings: (bookId: number, b: BookWritingSettingsInput) => put<BookWritingSettings>(`/books/${bookId}/writing-settings`, b),
}
export const qkV094 = {
  bookWriting: (bookId: number) => ['book-writing-settings', bookId] as const,
}

// ---------------------------------------------------------------- v0.10 同人创作
import type {
  ChapterFanficMeta, FanficCatalog, FanficDepth, FanficImportPart, FanficInfo, FanficOverlap, FanficSource, FanficSourceBrief,
  FanficSpecInput, FanficTemplateCatalog, SourceCards, LibCat, LibEntry, LibPage, FanficProtagonist,
} from './types'

type FanficSourceCommon = { title?: string; focus?: string[]; depth?: FanficDepth; template_id?: string }
export type FanficSourceInput =
  | ({ source: 'paste'; text: string; web_supplement?: boolean } & FanficSourceCommon)
  | ({ source: 'txt'; file: File; web_supplement?: boolean } & FanficSourceCommon)
  /** v0.11.1 联网取材：只填作品名（title 必填） */
  | ({ source: 'search'; title: string } & Omit<FanficSourceCommon, 'title'>)
export type FanficPatchInput = Partial<Pick<FanficSpecInput, 'fidelity' | 'direction' | 'extra_source_ids' | 'notes'>>

export const fanficApi = {
  directions: () => get<FanficCatalog>('/fanfic/directions'),
  /** v0.11.1 热门同人题材模板 + 联网搜索可用状态 */
  templates: () => get<FanficTemplateCatalog>('/fanfic/templates'),
  /** v0.11.1 已有原著资料联网补充：Job（kind=fanfic_supplement），result = {source, source_id, added, warnings} */
  supplementSource: (id: number, b: { focus?: string[]; depth?: FanficDepth } = {}) => viaJobId(post<{ job_id: number }>(`/fanfic/sources/${id}/supplement`, b)),
  sources: () => get<FanficSourceBrief[]>('/fanfic/sources'),
  source: (id: number) => get<FanficSource>(`/fanfic/sources/${id}`),
  /** Job（kind=fanfic_source），result = {source, source_id} */
  createSource: (b: FanficSourceInput) => {
    if (b.source === 'txt') {
      const fd = new FormData()
      fd.append('file', b.file)
      if (b.title) fd.append('title', b.title)
      if (b.focus?.length) fd.append('focus', b.focus.join(','))
      if (b.depth) fd.append('depth', b.depth)
      if (b.web_supplement) fd.append('web_supplement', '1')
      if (b.template_id) fd.append('template_id', b.template_id)
      return viaJobId(request('POST', '/fanfic/sources', fd))
    }
    return viaJobId(post('/fanfic/sources', b))
  },
  /** v0.15 原著世界库 */
  entries: (id: number, p: { cat?: LibCat; sub?: string; q?: string; page?: number; size?: number }) => get<LibPage>(`/fanfic/sources/${id}/entries${qs(p)}`),
  addEntry: (id: number, b: Partial<LibEntry>) => post<LibEntry>(`/fanfic/sources/${id}/entries`, b),
  updateEntry: (id: number, eid: string, b: Partial<LibEntry>) => put<LibEntry>(`/fanfic/sources/${id}/entries/${eid}`, b),
  deleteEntry: (id: number, eid: string) => del<{ ok: boolean }>(`/fanfic/sources/${id}/entries/${eid}`),
  /** Job（kind=fanfic_expand），result = {source_id, added, cat} */
  /** v0.16 创作想法 AI 重写（同步） */
  rewriteIdea: (b: { source_id: number; direction?: string; text: string; instruction?: string; notes?: string; protagonist?: FanficProtagonist }) =>
    post<{ text: string }>('/fanfic/idea/rewrite', b),
  expandLibrary: (id: number, b: { cat: LibCat; sub?: string; hint?: string; count?: number }) => viaJobId(post<{ job_id: number }>(`/fanfic/sources/${id}/expand`, b)),
  updateSource: (id: number, b: { title?: string; cards?: Partial<SourceCards>; intro?: string; tags?: string[] }) => put<{ source: FanficSource; warnings: string[] }>(`/fanfic/sources/${id}`, b),
  /** 有书在用时 409，force=true 强删 */
  deleteSource: (id: number, force = false) => del<{ ok: boolean }>(`/fanfic/sources/${id}${qs({ force: force || undefined })}`),
  /** 建同人书：copyright_ack 必须 true */
  createBook: (b: { title?: string; genre: string; gender: Gender; premise?: string; platform_style?: PlatformStyle; fanfic: FanficSpecInput; copyright_ack: boolean
    target_words?: number; chapter_words?: number; mode?: 'serial' | 'wanben'; volume_chapters?: number }) => post<Book>('/books', b),
  generateOc: (bookId: number) => post<Job>(`/books/${bookId}/fanfic/oc/generate`),
  bookFanfic: (bookId: number) => get<FanficInfo>(`/books/${bookId}/fanfic`),
  attachFanfic: (bookId: number, b: FanficSpecInput & { copyright_ack: true }) => post<FanficInfo>(`/books/${bookId}/fanfic`, b),
  patchFanfic: (bookId: number, b: FanficPatchInput) => patch<FanficInfo>(`/books/${bookId}/fanfic`, b),
  detachFanfic: (bookId: number) => del<{ ok: boolean }>(`/books/${bookId}/fanfic`),
  context: (bookId: number) => get<{ book_id: number; text: string; chars: number }>(`/books/${bookId}/fanfic/context`),
  importCards: (bookId: number, parts?: FanficImportPart[]) => post<{ cards: Card[]; skipped: number }>(`/books/${bookId}/fanfic/import-cards`, parts?.length ? { parts } : {}),
  /** Job（kind=fanfic_ooc），result = {chapter_id, ooc, overlap} */
  oocCheck: (chapterId: number) => viaJobId(post(`/chapters/${chapterId}/ooc-check`)),
  chapterOoc: (chapterId: number) => get<ChapterFanficMeta>(`/chapters/${chapterId}/ooc`),
  overlap: (chapterId: number) => post<{ chapter_id: number; overlap: FanficOverlap }>(`/chapters/${chapterId}/fanfic-overlap`),
}

export const fqk = {
  directions: ['fanfic', 'directions'] as const,
  templates: ['fanfic', 'templates'] as const,
  sources: ['fanfic', 'sources'] as const,
  source: (id: number) => ['fanfic', 'sources', id] as const,
  book: (bookId: number) => ['fanfic', 'book', bookId] as const,
  context: (bookId: number) => ['fanfic', 'context', bookId] as const,
  chapter: (chapterId: number) => ['fanfic', 'chapter', chapterId] as const,
}

// ---------------------------------------------------------------- v0.11 完本模式 / 质检
import type {
  AdaptHistoryItem, AdaptReport, BookCheckHistoryItem, BookCheckReport, CheckFix, DuanjuCheck, HomoReport, IterateInput, PlatformStyleOpt,
  RangeItem, RefineSummary, WanbenBatch, WanbenIteration, WanbenPlanSummary, WanbenProgress, WanbenSettings, WanbenSettingsInput,
} from './types'

export const wanbenApi = {
  settings: (bookId: number) => get<WanbenSettings>(`/books/${bookId}/wanben`),
  saveSettings: (bookId: number, b: WanbenSettingsInput) => put<WanbenSettings>(`/books/${bookId}/wanben`, b),
  /** Job（wanben_plan），result = WanbenPlanResult */
  plan: (bookId: number) => viaJobId(post(`/books/${bookId}/wanben/plan`)),
  planSummary: (bookId: number) => get<WanbenPlanSummary>(`/books/${bookId}/wanben/plan`),
  /** Job（wanben_batch）；force：精修待审批时也继续写 */
  batch: (bookId: number, force = false) => viaJobId(post(`/books/${bookId}/wanben/batch`, { force })),
  pause: (bookId: number) => post<{ ok: boolean; paused: boolean; running_batch_id: number | null; job_id: number | null; message: string }>(`/books/${bookId}/wanben/batch/pause`),
  batches: (bookId: number) => get<WanbenBatch[]>(`/books/${bookId}/wanben/batches`),
  batchDetail: (bookId: number, batchId: number) => get<WanbenBatch>(`/books/${bookId}/wanben/batches/${batchId}`),
  refine: (bookId: number) => get<RefineSummary>(`/books/${bookId}/wanben/refine`),
  editRefine: (bookId: number, action: 'add' | 'remove' | 'set', ranges: RangeItem[]) => post<RefineSummary>(`/books/${bookId}/wanben/refine`, { action, ranges }),
  /** Job（wanben_iterate） */
  iterate: (bookId: number, b: IterateInput) => viaJobId(post(`/books/${bookId}/wanben/iterate`, b)),
  stopIterate: (bookId: number) => post<{ ok: boolean; message: string }>(`/books/${bookId}/wanben/iterate/stop`),
  iterations: (bookId: number, p: { number?: number; chapter_id?: number; status?: 'pending' | 'adopted' | 'discarded' } = {}) => get<WanbenIteration[]>(`/books/${bookId}/wanben/iterations${qs(p)}`),
  iteration: (bookId: number, id: number) => get<WanbenIteration>(`/books/${bookId}/wanben/iterations/${id}`),
  adoptIteration: (bookId: number, id: number) => post<{ iteration: WanbenIteration; chapter_id: number; chapter_status: string; words: number }>(`/books/${bookId}/wanben/iterations/${id}/adopt`),
  discardIteration: (bookId: number, id: number) => post<WanbenIteration>(`/books/${bookId}/wanben/iterations/${id}/discard`),
  progress: (bookId: number) => get<WanbenProgress>(`/books/${bookId}/wanben/progress`),
  /** 下载整书 TXT（Blob，兼容 mock） */
  async exportTxt(bookId: number, fallback: string) {
    let res: Response
    try { res = await fetch(`/api/books/${bookId}/wanben/export.txt`, { credentials: 'same-origin' }) } catch { throw new ApiError(0, '无法连接到后端服务') }
    if (!res.ok) {
      let msg = `导出失败（${res.status}）`
      try { const j = await res.json(); if (j?.detail) msg = j.detail } catch { /* ignore */ }
      throw new ApiError(res.status, msg)
    }
    const cd = res.headers.get('Content-Disposition') || ''
    const m = /filename\*=UTF-8''([^;]+)/i.exec(cd) || /filename="?([^";]+)"?/i.exec(cd)
    const name = m ? decodeURIComponent(m[1]) : fallback
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a')
    a.href = url; a.download = name
    document.body.appendChild(a); a.click(); a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 2000)
  },
}

export const checkApi = {
  platformStyles: () => get<{ items: PlatformStyleOpt[] }>('/platform-styles'),
  /** Job（book_check），result = BookCheckReport */
  startBookCheck: (bookId: number, llm: boolean) => viaJobId(post(`/books/${bookId}/book-check`, { llm })),
  bookCheck: (bookId: number, jobId?: number) => get<{ report: BookCheckReport | null }>(`/books/${bookId}/book-check${qs({ job_id: jobId })}`),
  bookCheckHistory: (bookId: number) => get<{ items: BookCheckHistoryItem[] }>(`/books/${bookId}/book-check/history`),
  /** 一键修：按问题里的 fix（endpoint/method/body）调用已有接口；返回 Job 时交给轮询 */
  runFix: (fix: CheckFix) => request<any>(fix.method.toUpperCase(), fix.endpoint.replace(/^\/api(?=\/)/, ''), fix.body ?? {}),
  startAdapt: (bookId: number, b: { start?: number; end?: number; llm?: boolean }) => viaJobId(post(`/books/${bookId}/adaptability`, b)),
  adapt: (bookId: number, jobId?: number) => get<{ report: AdaptReport | null }>(`/books/${bookId}/adaptability${qs({ job_id: jobId })}`),
  adaptHistory: (bookId: number) => get<{ items: AdaptHistoryItem[] }>(`/books/${bookId}/adaptability/history`),
  duanjuCheck: (chapterId: number) => post<DuanjuCheck>(`/chapters/${chapterId}/duanju-check`),
  /** llm=false：同步 {mode:'sync', report}；llm=true：{mode:'job', job} */
  homogeneity: (target: 'book' | 'idea', id: number, llm = false) =>
    post<{ mode: 'sync'; report: HomoReport } | { mode: 'job'; job: Job }>(`/${target === 'book' ? 'books' : 'ideas'}/${id}/homogeneity`, { llm }),
}

/** v0.16 一键成书 */
export const autoApi = {
  get: (bookId: number) => get<AutoOverview>(`/books/${bookId}/autopilot`),
  saveSettings: (bookId: number, b: Partial<AutoSettings>) => put<AutoSettings>(`/books/${bookId}/autopilot/settings`, b),
  /** Job（autopilot） */
  start: (bookId: number, b?: Partial<AutoSettings>) => post<{ run_id: number; job: Job }>(`/books/${bookId}/autopilot/start`, b ?? {}).then((r) => r.job),
  pause: (bookId: number) => post<{ ok: boolean; running: boolean }>(`/books/${bookId}/autopilot/pause`),
  /** 拍板后自动继续：Job（autopilot） */
  answer: (bookId: number, decisionId: number, b: { choice: number | null; custom: string }) => viaJobId(post(`/books/${bookId}/autopilot/decisions/${decisionId}`, b)),
  resolveFlag: (bookId: number, chapterId: number) => post<{ ok: boolean }>(`/books/${bookId}/autopilot/flags/${chapterId}/resolve`),
  /** v0.17 待你看的章放行：Job（autopilot_accept） */
  acceptFlag: (bookId: number, chapterId: number) => post<Job>(`/books/${bookId}/autopilot/flags/${chapterId}/accept`),
  replanFlag: (bookId: number, chapterId: number) => post<Job>(`/books/${bookId}/autopilot/flags/${chapterId}/replan`),
  fromIdea: (ideaId: number, b?: Partial<AutoSettings>) => post<{ book: Book; run_id: number; job: Job }>(`/ideas/${ideaId}/autopilot`, b ?? {}),
}

export const aqk = { overview: (bookId: number) => ['autopilot', bookId] as const }

export const wqk = {
  settings: (bookId: number) => ['wanben', bookId, 'settings'] as const,
  progress: (bookId: number) => ['wanben', bookId, 'progress'] as const,
  batches: (bookId: number) => ['wanben', bookId, 'batches'] as const,
  batch: (bookId: number, id: number) => ['wanben', bookId, 'batch', id] as const,
  refine: (bookId: number) => ['wanben', bookId, 'refine'] as const,
  iterations: (bookId: number) => ['wanben', bookId, 'iterations'] as const,
  iteration: (bookId: number, id: number) => ['wanben', bookId, 'iteration', id] as const,
  bookCheck: (bookId: number, jobId?: number) => ['book-check', bookId, jobId ?? 'latest'] as const,
  bookCheckHistory: (bookId: number) => ['book-check', bookId, 'history'] as const,
  adapt: (bookId: number, jobId?: number) => ['adaptability', bookId, jobId ?? 'latest'] as const,
  adaptHistory: (bookId: number) => ['adaptability', bookId, 'history'] as const,
  platformStyles: ['platform-styles'] as const,
  duanju: (chapterId: number) => ['duanju', chapterId] as const,
}

/** v0.13 批量质检、章节工具、笔记、抽卡立项、@变量与上下文构成 */
export const v013Api = {
  batch: (bookId: number, b: BatchInput) => post<Job>(`/books/${bookId}/batch`, b),
  stopBatch: (bookId: number) => post<{ ok: boolean; message: string }>(`/books/${bookId}/batch/stop`),
  titles: (chapterId: number, n = 6) => post<Job>(`/chapters/${chapterId}/titles`, { n }),
  sparks: (bookId: number, b: { n?: number; use_context?: boolean; hint?: string }) => post<Job>(`/books/${bookId}/sparks`, b),
  readerComments: (chapterId: number, personas = 4) => post<Job>(`/chapters/${chapterId}/reader-comments`, { personas }),
  chapterFreq: (chapterId: number) => get<{ chapter_id: number; items: FreqItem[] }>(`/chapters/${chapterId}/freq`),
  bookFreq: (bookId: number, start?: number, end?: number) => get<{ book_id: number; chapters: number; items: FreqItem[] }>(`/books/${bookId}/freq${start || end ? `?${new URLSearchParams({ ...(start ? { start: String(start) } : {}), ...(end ? { end: String(end) } : {}) })}` : ''}`),
  format: (text: string) => post<{ text: string; changed: boolean; notes: string[] }>('/format', { text }),
  search: (bookId: number, q: string, scopes: SearchScope[], regex: boolean, ci = false) =>
    get<SearchResult>(`/books/${bookId}/search?${new URLSearchParams({ q, scope: scopes.join(','), regex: String(regex), case: String(!ci) })}`),
  replace: (bookId: number, b: { q: string; replacement: string; scopes: SearchScope[]; regex: boolean; case: boolean; expect?: number; skip?: string[] }) =>
    post<{ replaced: number; changed: Record<string, number>; skipped_locked: string[] }>(`/books/${bookId}/replace`, b),
  notes: (bookId: number, q = '') => get<Note[]>(`/books/${bookId}/notes${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  createNote: (bookId: number, b: Partial<Note>) => post<Note>(`/books/${bookId}/notes`, b),
  updateNote: (bookId: number, id: number, b: Partial<Note>) => put<Note>(`/books/${bookId}/notes/${id}`, b),
  deleteNote: (bookId: number, id: number) => del<{ ok: boolean }>(`/books/${bookId}/notes/${id}`),
  exportNotesUrl: (bookId: number) => `/api/books/${bookId}/notes/export`,
  importNotes: (bookId: number, text: string, folder = '') => post<{ created: number }>(`/books/${bookId}/notes/import`, { text, folder }),
  sparkToNote: (bookId: number, sp: Spark) => post<Note>(`/books/${bookId}/notes/from-spark`, sp),
  aigcReportUrl: (chapterId: number) => `/api/chapters/${chapterId}/aigc/report`,
  contextPreview: (bookId: number, chapterId?: number) => get<ContextPreview>(`/books/${bookId}/context-preview${chapterId ? `?chapter_id=${chapterId}` : ''}`),
  setContextExclude: (bookId: number, blocks: string[]) => put<{ blocks: string[] }>(`/books/${bookId}/context-exclude`, { blocks }),
  sparkTracks: (gender: Gender) => get<{ gender: Gender; tracks: SparkTrack[]; tag_groups: string[] }>(`/spark/tracks?gender=${gender}`),
  sparkSessions: () => get<{ id: number; track: string; gender: Gender; idea_id: number | null; title: string | null; updated_at: string | null }[]>('/spark/sessions'),
  sparkCreate: (b: { gender: Gender; track: string; sub?: string; tags?: string[]; inspiration?: Record<string, string> }) => post<SparkSessionData>('/spark/sessions', b),
  sparkGet: (id: number) => get<SparkSessionData>(`/spark/sessions/${id}`),
  sparkDraw: (id: number, axis: SparkAxis, keep: string[], custom = '') => post<Job>(`/spark/sessions/${id}/draw`, { axis, keep, custom }),
  sparkPick: (id: number, axis: SparkAxis, card_id: string | null, custom?: { title: string; desc: string }) => post<SparkSessionData>(`/spark/sessions/${id}/pick`, { axis, card_id, custom }),
  sparkProposal: (id: number) => post<Job>(`/spark/sessions/${id}/proposal`),
  sparkPatchProposal: (id: number, b: Partial<SparkProposal>) => patch<SparkSessionData>(`/spark/sessions/${id}/proposal`, b),
  sparkAdopt: (id: number) => post<{ idea_id: number }>(`/spark/sessions/${id}/adopt`),
}
