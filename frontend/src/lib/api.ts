import type {
  BibleOp, BibleSnapshot, BookInfo, ForeshadowOverview, ForeshadowPlanItem, Impact, Trope,
  Book, Card, CardType, Channel, ChannelInput, Chapter, Fact, Foreshadow, Gender, Idea, IdeaField, Job,
  OutlineNode, Package, RadarConfig, RadarSnapshot, RankItem, Routing, Style, TrendTopic, WritingSettings,
} from './types'

export interface AuthStatus { enabled: boolean; authenticated: boolean; username: string; managed_by_env: boolean; min_password_len: number }

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
  try {
    res = await fetch(`/api${url}`, {
      method,
      credentials: 'same-origin',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
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
    if (res.status === 502 || res.status === 504) msg = '后端服务暂时不可用，请稍后再试'
    if (res.status === 401 && !url.startsWith('/auth/')) window.dispatchEvent(new Event('novelos:unauthorized'))
    throw new ApiError(res.status, msg)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

const get = <T,>(u: string) => request<T>('GET', u)
const post = <T,>(u: string, b?: unknown) => request<T>('POST', u, b ?? {})
const put = <T,>(u: string, b: unknown) => request<T>('PUT', u, b)
const patch = <T,>(u: string, b: unknown) => request<T>('PATCH', u, b)
const del = <T,>(u: string) => request<T>('DELETE', u)

export const api = {
  health: () => get<{ status: string; version: string }>('/health'),

  authStatus: () => get<AuthStatus>('/auth/status'),
  login: (password: string, remember: boolean) => post<{ ok: boolean }>('/auth/login', { password, remember }),
  logout: () => post<{ ok: boolean }>('/auth/logout'),
  changePassword: (current: string, next: string) => post<{ ok: boolean }>('/auth/password', { current, new: next }),

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

  /** 合约增补“默认设置可选自动采纳最高分”的落点（后端已实现 /settings/writing） */
  writingSettings: () => get<WritingSettings>('/settings/writing'),
  saveWritingSettings: (b: Partial<WritingSettings>) => put<WritingSettings>('/settings/writing', b),

  radarRefresh: () => post<Job>('/radar/refresh'),
  radarSnapshots: () => get<RadarSnapshot[]>('/radar/snapshots'),
  radarLatest: (p: { gender?: Gender; category?: string }) =>
    get<{ snapshot: RadarSnapshot | null; items: RankItem[] }>(`/radar/latest${qs(p)}`),
  radarTrends: (gender?: Gender) => get<TrendTopic[]>(`/radar/trends${qs({ gender })}`),
  radarConfig: () => get<RadarConfig>('/radar/config'),
  saveRadarConfig: (b: RadarConfig) => put<RadarConfig>('/radar/config', b),

  books: () => get<Book[]>('/books'),
  book: (id: number) => get<Book>(`/books/${id}`),
  createBook: (b: { title?: string; genre: string; gender: Gender; premise?: string }) => post<Book>('/books', b),
  updateBook: (id: number, b: Partial<Book>) => patch<Book>(`/books/${id}`, b),
  deleteBook: (id: number) => del<void>(`/books/${id}`),

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
  commitChapter: (id: number) => post<Chapter>(`/chapters/${id}/commit`),

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

  generatePackage: (bookId: number) => post<Job>(`/books/${bookId}/package/generate`),
  reviseCoverPrompt: (bookId: number, b: { instruction: string; current?: string; route?: string | null }) => post<Job>(`/books/${bookId}/covers/prompt`, b),
  deleteCover: (bookId: number, url: string) => post<Package>(`/books/${bookId}/covers/delete`, { url }),
  suggestCard: (bookId: number, b: { card_id: number | null; field: string | null; instruction: string; route?: string | null; draft: Record<string, any> }) => post<Job>(`/books/${bookId}/cards/suggest`, b),
  generateCovers: (bookId: number, b: { prompt?: string; n?: number; title_mode?: 'model' | 'overlay' }) => post<Job>(`/books/${bookId}/covers/generate`, b),
  package: (bookId: number) => get<Package>(`/books/${bookId}/package`),
  savePackage: (bookId: number, b: Partial<Package>) => put<Package>(`/books/${bookId}/package`, b),

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
  status: ['status'] as const,
  channels: ['channels'] as const,
  routing: ['routing'] as const,
  writing: ['writing-settings'] as const,
  jobs: (bookId?: number) => ['jobs', bookId ?? 'all'] as const,
  job: (id: number) => ['job', id] as const,
  radarLatest: (gender?: string, category?: string) => ['radar', 'latest', gender ?? '', category ?? ''] as const,
  radarTrends: (gender?: string) => ['radar', 'trends', gender ?? ''] as const,
  radarSnapshots: ['radar', 'snapshots'] as const,
  radarConfig: ['radar', 'config'] as const,
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
}
