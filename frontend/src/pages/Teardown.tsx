import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, ChevronLeft, CloudUpload, FileText, Gem, Layers, Lightbulb, Loader2, Plus, Scissors, Sparkles, Trash, X,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Select } from '@/components/ui/select'
import { EmptyState, ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { BookCover } from '@/components/radar/BookCover'
import { BookPicker, TextSource, bareLen, type TextDoc } from '@/components/ideas/BookPicker'
import { useBooks } from '@/hooks/queries'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { PacingPoint, RankItem, TeardownBiblePart, TeardownRecord, TeardownResult, TeardownSourceType } from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

/** 后端：txt / paste 去空白后 ≤20000 字 */
const TEXT_LIMIT = 20000
const SRC_LABEL: Record<TeardownSourceType, string> = { rank_book: '榜单书', txt: 'TXT', paste: '粘贴' }
const CREATE_KEY = 'teardown-create'

export default function TeardownPage() {
  const { id } = useParams()
  const tdId = id && /^\d+$/.test(id) ? Number(id) : 0
  return (
    <div className="min-h-full lg:flex lg:h-full lg:flex-col">
      <header className="flex shrink-0 items-center gap-2 border-b px-3 py-2.5 sm:px-5">
        {tdId ? (
          <Link to="/teardown" className="focus-ring inline-flex h-10 items-center gap-0.5 rounded-md pr-2 text-[13px] text-muted-foreground hover:text-foreground">
            <ChevronLeft className="h-4 w-4" />拆书
          </Link>
        ) : (
          <h1 className="flex items-center gap-2 text-[17px] font-semibold tracking-tight"><Scissors className="h-[18px] w-[18px] text-primary" weight="duotone" />拆书工作台</h1>
        )}
        <span className="ml-auto hidden text-[12px] text-muted-foreground sm:inline">拆结构、人设、金手指、卖点与节奏，产物可转选题或写进设定库</span>
      </header>
      <div className={cn('flex min-w-0 flex-col lg:grid lg:min-h-0 lg:flex-1', tdId ? 'lg:grid-cols-[320px_minmax(0,1fr)_300px]' : 'lg:grid-cols-[360px_minmax(0,1fr)]')}>
        <aside className="min-w-0 border-b p-3 sm:p-4 lg:overflow-y-auto lg:border-b-0 lg:border-r">
          <SourcePanel />
        </aside>
        {tdId ? <Detail id={tdId} /> : (
          <section className="min-w-0 p-3 sm:p-5 lg:overflow-y-auto"><History /></section>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 左栏：来源

function SourcePanel() {
  const [sp, setSp] = useSearchParams()
  const ext = sp.get('ext')
  const nav = useNavigate()
  const { start } = useJobs()
  const running = useActiveJob(CREATE_KEY)
  const [src, setSrc] = useState<'rank' | 'upload' | 'paste'>('rank')
  const [book, setBook] = useState<RankItem | null>(null)
  const [doc, setDoc] = useState<TextDoc | null>(null)
  const [picking, setPicking] = useState(!ext)

  // ?ext=书ID 预选榜单书
  const pre = useQuery({ queryKey: ['radar', 'book-detail', ext], queryFn: () => api.radarBookDetail(ext!), enabled: !!ext, retry: false })
  const done = useRef<string | null>(null)
  useEffect(() => {
    if (!ext || done.current === ext) return
    if (pre.data) { done.current = ext; setSrc('rank'); setBook(pre.data.item); setPicking(false) }
    else if (pre.isError) { done.current = ext; setPicking(true); toast.info('没找到这本榜单书，请重新选择') }
  }, [ext, pre.data, pre.isError])

  const textN = doc ? bareLen(doc.text) : 0
  const tooLong = src !== 'rank' && textN > TEXT_LIMIT
  const ready = src === 'rank' ? !!book : !!doc && textN > 0 && !tooLong

  const go = async () => {
    if (!ready) return
    const body = src === 'rank'
      ? { source: 'rank_book' as const, book_id_ext: book!.book_id_ext, title: book!.title }
      : { source: (src === 'upload' ? 'txt' : 'paste') as TeardownSourceType, text: doc!.text, title: doc!.title || undefined }
    await start(api.createTeardown(body), {
      label: '拆书', key: CREATE_KEY,
      successMsg: '拆书完成',
      onSuccess: (j) => {
        const tid = j.result?.teardown_id ?? j.result?.teardown?.id
        if (tid) nav(`/teardown/${tid}`)
      },
    })
  }

  return (
    <div className="space-y-3">
      <div>
        <h2 className="text-[14px] font-semibold">新建拆书</h2>
        <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">选一本榜单书，或上传 / 粘贴正文（≤20,000 字）。原文只用于拆解，不保存。</p>
      </div>
      <Segmented block value={src} onChange={(v) => setSrc(v)} className="h-10" options={[
        { value: 'rank', label: <span className="inline-flex items-center gap-1"><Lightbulb className="h-3.5 w-3.5" />榜单书</span> },
        { value: 'upload', label: <span className="inline-flex items-center gap-1"><CloudUpload className="h-3.5 w-3.5" />TXT</span> },
        { value: 'paste', label: <span className="inline-flex items-center gap-1"><FileText className="h-3.5 w-3.5" />粘贴</span> },
      ]} />

      {src === 'rank' ? (
        <>
          {ext && pre.isLoading && !book && <Skeleton className="h-[72px] rounded-xl" />}
          {book && (
            <div className="flex min-w-0 items-center gap-3 rounded-xl border border-primary/40 bg-primary-soft/40 p-2.5">
              <BookCover src={book.cover} title={book.title} size="sm" className="w-[40px] shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14px] font-semibold">{book.title}</div>
                <div className="truncate text-[12px] text-muted-foreground">{book.author || '佚名'} · {book.category}</div>
              </div>
              <button type="button" aria-label="移除" onClick={() => { setBook(null); setPicking(true); if (ext) { sp.delete('ext'); setSp(sp, { replace: true }) } }}
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"><X className="h-4 w-4" /></button>
            </div>
          )}
          {book && !picking ? (
            <Button variant="ghost" size="sm" className="h-10 w-full" onClick={() => setPicking(true)}>换一本</Button>
          ) : (
            <BookPicker single selected={book ? [book] : []}
              initial={pre.data ? { gender: pre.data.item.gender, board: pre.data.item.board } : undefined}
              onToggle={(i) => { setBook((b) => (b?.book_id_ext === i.book_id_ext ? null : i)); setPicking(false) }} />
          )}
        </>
      ) : (
        <TextSource key={src} mode={src} value={doc && doc.from === src ? doc : null} onChange={setDoc} />
      )}
      {tooLong && <p className="text-[12px] text-danger">正文超过 {TEXT_LIMIT.toLocaleString('zh-CN')} 字，请删减后再拆</p>}

      <div className="sticky bottom-0 -mx-3 bg-background/95 px-3 pb-1 pt-2 backdrop-blur sm:-mx-4 sm:px-4">
        {running ? <JobInline job={running} /> : (
          <Button variant="primary" className="h-11 w-full" disabled={!ready} icon={<Scissors className="h-4 w-4" />} onClick={() => void go()}>开始拆书</Button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 列表

function History() {
  const q = useQuery({ queryKey: qk.teardowns, queryFn: api.teardowns })
  if (q.isLoading) return <div className="space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[68px] rounded-xl" />)}</div>
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const list = q.data ?? []
  return (
    <div className="space-y-3">
      <h2 className="text-[14px] font-semibold">历史拆书<span className="num ml-1.5 font-normal text-muted-foreground">{list.length}</span></h2>
      {!list.length ? (
        <EmptyState kind="book" title="还没有拆过书" desc="在左边选一本榜单书或导入正文，点「开始拆书」。" />
      ) : (
        <ul className="grid gap-2 xl:grid-cols-2">
          {list.map((t) => (
            <li key={t.id}>
              <Link to={`/teardown/${t.id}`} className="card-hover focus-ring flex min-h-[64px] min-w-0 items-center gap-3 rounded-xl border bg-surface px-3.5 py-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><Scissors className="h-[18px] w-[18px]" /></span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-semibold">{t.title || '未命名'}</span>
                  <span className="num mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[12px] text-muted-foreground">
                    <span className="rounded bg-muted px-1.5 leading-[18px]">{SRC_LABEL[t.source] ?? t.source}</span>
                    <span>{t.chars ? `${fmtNum(t.chars)} 字` : '无原文'}</span>
                    <span className="opacity-40">·</span><span>{fmtDateTime(t.created_at)}</span>
                    {t.warnings_count > 0 && <span className="inline-flex items-center gap-0.5 text-warning"><AlertTriangle className="h-3 w-3" />{t.warnings_count}</span>}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 详情

type TabKey = 'structure' | 'characters' | 'golden_finger' | 'selling_points' | 'pacing_chart' | 'reusable'
const TABS: { value: TabKey; label: string }[] = [
  { value: 'structure', label: '结构' }, { value: 'characters', label: '人设' }, { value: 'golden_finger', label: '金手指' },
  { value: 'selling_points', label: '卖点' }, { value: 'pacing_chart', label: '节奏图' }, { value: 'reusable', label: '可复用套路' },
]

function Detail({ id }: { id: number }) {
  const q = useQuery({ queryKey: qk.teardownDetail(id), queryFn: () => api.teardownDetail(id), retry: false })
  const [tab, setTab] = useState<TabKey>('structure')
  if (q.isLoading) return <section className="space-y-3 p-3 sm:p-5 lg:col-span-2"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-64 rounded-xl" /></section>
  if (q.isError || !q.data) return <section className="p-3 sm:p-5 lg:col-span-2"><ErrorState error={q.error ?? { message: '没找到这份拆书' }} onRetry={() => q.refetch()} /></section>
  const t = q.data
  return (
    <>
      <section className="min-w-0 p-3 sm:p-5 lg:overflow-y-auto">
        <h2 className="break-words text-[19px] font-semibold tracking-tight">{t.title || '未命名'}</h2>
        <div className="num mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted-foreground">
          <span className="rounded bg-muted px-1.5 leading-[20px]">{SRC_LABEL[t.source] ?? t.source}</span>
          <span>{t.chars ? `${fmtNum(t.chars)} 字` : '无原文'}</span>
          <span>{fmtDateTime(t.created_at)}</span>
          {t.model && <span className="truncate">模型 {t.model}</span>}
        </div>
        {t.warnings?.length > 0 && (
          <ul className="mt-3 space-y-1 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning">
            {t.warnings.map((w, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}</li>)}
          </ul>
        )}
        <div className="-mx-3 mt-4 overflow-x-auto px-3 [scrollbar-width:none] sm:mx-0 sm:px-0">
          <Segmented value={tab} onChange={setTab} className="h-10" options={TABS} />
        </div>
        <div className="mt-4">
          <TabBody tab={tab} r={t.result ?? {}} />
        </div>
      </section>
      <aside className="min-w-0 border-t p-3 sm:p-4 lg:overflow-y-auto lg:border-l lg:border-t-0">
        <Actions t={t} />
      </aside>
    </>
  )
}

const Empty = () => <div className="rounded-xl border border-dashed px-4 py-10 text-center text-[13px] text-muted-foreground">这一项没有拆出内容</div>
const Box = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="rounded-xl border bg-surface p-3.5">
    <div className="mb-1 text-[12px] font-medium text-muted-foreground">{title}</div>
    <div className="whitespace-pre-wrap break-words text-[13.5px] leading-[1.7]">{children}</div>
  </div>
)

function TabBody({ tab, r }: { tab: TabKey; r: TeardownResult }) {
  if (tab === 'structure') {
    const s = r.structure
    if (!s || (!s.opening && !s.rhythm && !s.chapter_hooks?.length)) return <Empty />
    return (
      <div className="space-y-3">
        {s.opening && <Box title="开篇">{s.opening}</Box>}
        {s.rhythm && <Box title="节奏">{s.rhythm}</Box>}
        {!!s.chapter_hooks?.length && (
          <div className="rounded-xl border bg-surface p-3.5">
            <div className="mb-2 text-[12px] font-medium text-muted-foreground">章末钩子</div>
            <ol className="space-y-1.5">
              {s.chapter_hooks.map((h, i) => (
                <li key={i} className="flex gap-2 text-[13.5px] leading-[1.6]"><span className="num w-5 shrink-0 text-right text-muted-foreground">{i + 1}</span><span className="min-w-0 break-words">{h}</span></li>
              ))}
            </ol>
          </div>
        )}
      </div>
    )
  }
  if (tab === 'characters') {
    if (!r.characters?.length) return <Empty />
    return (
      <div className="grid gap-3 xl:grid-cols-2">
        {r.characters.map((c, i) => (
          <div key={i} className="min-w-0 rounded-xl border bg-surface p-3.5">
            <div className="flex items-center gap-2"><span className="rounded-md bg-primary-soft px-2 text-[12px] font-medium leading-[22px] text-primary">{c.role}</span></div>
            <p className="mt-2 break-words text-[13.5px] leading-[1.7]">{c.template}</p>
            {!!c.traits?.length && <div className="mt-2 flex flex-wrap gap-1.5">{c.traits.map((x) => <span key={x} className="rounded bg-muted px-1.5 text-[12px] leading-[20px] text-muted-foreground">{x}</span>)}</div>}
            {c.function && <p className="mt-2 text-[12.5px] text-muted-foreground">作用：{c.function}</p>}
          </div>
        ))}
      </div>
    )
  }
  if (tab === 'golden_finger') {
    const g = r.golden_finger
    if (!g || (!g.mechanism && !g.limits && !g.growth && !g.payoff)) return <Empty />
    return (
      <div className="grid gap-3 xl:grid-cols-2">
        {g.mechanism && <Box title="机制">{g.mechanism}</Box>}
        {g.limits && <Box title="限制">{g.limits}</Box>}
        {g.growth && <Box title="成长">{g.growth}</Box>}
        {g.payoff && <Box title="爽点兑现">{g.payoff}</Box>}
      </div>
    )
  }
  if (tab === 'selling_points') {
    if (!r.selling_points?.length) return <Empty />
    return (
      <ol className="space-y-2">
        {r.selling_points.map((x, i) => (
          <li key={i} className="flex gap-3 rounded-xl border bg-surface p-3.5 text-[13.5px] leading-[1.7]">
            <span className="num flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary-soft text-[12px] font-semibold text-primary">{i + 1}</span>
            <span className="min-w-0 break-words">{x}</span>
          </li>
        ))}
      </ol>
    )
  }
  if (tab === 'pacing_chart') {
    if (!r.pacing_chart?.length) return <Empty />
    return <PacingChart data={r.pacing_chart} />
  }
  if (!r.reusable?.length) return <Empty />
  return (
    <div className="space-y-3">
      {r.reusable.map((x, i) => (
        <div key={i} className="min-w-0 rounded-xl border bg-surface p-3.5">
          <div className="text-[14px] font-semibold">{x.name}</div>
          <p className="mt-1.5 break-words text-[13.5px] leading-[1.7]">{x.pattern}</p>
          {x.how_to_use && <p className="mt-2 break-words rounded-lg bg-subtle px-3 py-2 text-[12.5px] leading-[1.6] text-foreground/80"><span className="text-primary">怎么用 · </span>{x.how_to_use}</p>}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- 节奏图（内联 SVG）

const SERIES: { key: 'conflict' | 'payoff' | 'hook'; label: string; color: string; dash?: string }[] = [
  { key: 'conflict', label: '冲突', color: 'hsl(var(--danger))' },
  { key: 'payoff', label: '爽点', color: 'hsl(var(--warning))' },
  { key: 'hook', label: '钩子', color: 'hsl(var(--success))', dash: '6 4' },
]

function PacingChart({ data }: { data: PacingPoint[] }) {
  const W = 640, H = 240, L = 28, R = 12, T = 12, B = 28
  const n = data.length
  const x = (i: number) => (n <= 1 ? L + (W - L - R) / 2 : L + (i * (W - L - R)) / (n - 1))
  const y = (v: number) => T + ((5 - Math.min(5, Math.max(1, v || 1))) * (H - T - B)) / 4
  const step = Math.max(1, Math.ceil(n / 12))
  const [hover, setHover] = useState<number | null>(null)
  const pts = useMemo(() => SERIES.map((s) => data.map((d, i) => `${x(i).toFixed(1)},${y(d[s.key]).toFixed(1)}`).join(' ')), [data]) // eslint-disable-line react-hooks/exhaustive-deps
  const cur = hover !== null ? data[hover] : null
  return (
    <div className="min-w-0 rounded-xl border bg-surface p-3.5">
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
        {SERIES.map((s) => <span key={s.key} className="inline-flex items-center gap-1.5"><svg width="18" height="6" aria-hidden><line x1="1" x2="17" y1="3" y2="3" stroke={s.color} strokeWidth={2.5} strokeLinecap="round" strokeDasharray={s.dash ? '4 3' : undefined} /></svg>{s.label}</span>)}
        <span className="ml-auto text-[11.5px] text-muted-foreground">强度 1–5</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full max-w-full" role="img" aria-label="节奏图：冲突、爽点、钩子强度折线">
        {[1, 2, 3, 4, 5].map((v) => (
          <g key={v}>
            <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="currentColor" strokeOpacity={0.08} />
            <text x={L - 8} y={y(v) + 4} textAnchor="end" fontSize={11} fill="currentColor" fillOpacity={0.45}>{v}</text>
          </g>
        ))}
        {data.map((d, i) => (i % step === 0 || i === n - 1) && (
          <text key={i} x={x(i)} y={H - 8} textAnchor="middle" fontSize={11} fill="currentColor" fillOpacity={0.45}>{d.chapter}</text>
        ))}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="currentColor" strokeOpacity={0.2} strokeDasharray="3 3" />}
        {SERIES.map((s, k) => (
          <g key={s.key}>
            <polyline points={pts[k]} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray={s.dash} strokeLinejoin="round" strokeLinecap="round" />
            {data.map((d, i) => <circle key={i} cx={x(i)} cy={y(d[s.key])} r={hover === i ? 4 : 2.5} fill={s.color} />)}
          </g>
        ))}
        {data.map((_, i) => {
          const w = n <= 1 ? W - L - R : (W - L - R) / (n - 1)
          return <rect key={i} x={x(i) - w / 2} y={T} width={w} height={H - T - B} fill="transparent" onMouseEnter={() => setHover(i)} onClick={() => setHover(i)} onMouseLeave={() => setHover(null)} />
        })}
      </svg>
      <div className="mt-2 min-h-[40px] rounded-lg bg-subtle px-3 py-2 text-[12.5px] leading-[1.6]">
        {cur ? (
          <>
            <span className="font-medium">第 {cur.chapter} 章{cur.title ? ` · ${cur.title}` : ''}</span>
            <span className="num ml-2 text-muted-foreground">冲突 {cur.conflict} · 爽点 {cur.payoff} · 钩子 {cur.hook}</span>
            {cur.note && <p className="mt-0.5 break-words text-foreground/75">{cur.note}</p>}
          </>
        ) : <span className="text-muted-foreground">点按或悬停查看每章强度</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 右栏：操作

const PARTS: { value: TeardownBiblePart; label: string; desc: string }[] = [
  { value: 'characters', label: '人设模板', desc: '写为人物条目' },
  { value: 'golden_finger', label: '金手指', desc: '写为能力条目' },
  { value: 'reusable', label: '可复用套路', desc: '写为世界条目' },
  { value: 'selling_points', label: '卖点', desc: '写为世界条目' },
]

function Actions({ t }: { t: TeardownRecord }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { start } = useJobs()
  const ideaKey = `teardown-idea:${t.id}`
  const ideaJob = useActiveJob(ideaKey)
  const books = useBooks()
  const [bookId, setBookId] = useState<string | null>(null)
  const [parts, setParts] = useState<TeardownBiblePart[]>(['characters', 'golden_finger', 'reusable', 'selling_points'])
  const [res, setRes] = useState<{ cards: number; warnings: string[]; skipped: number; bookId: number } | null>(null)

  const toIdea = () => start(api.teardownToIdeaJob(t.id), {
    label: '拆书生成选题', key: ideaKey, successMsg: '选题已生成',
    onSuccess: (j) => {
      const iid = j.result?.idea_id ?? j.result?.idea?.id
      nav(iid ? `/ideas/${iid}` : '/ideas')
    },
  })
  const bible = useMutation({
    mutationFn: () => api.teardownToBible(t.id, { book_id: Number(bookId), parts }),
    meta: { errorTitle: '写入设定失败' },
    onSuccess: (r) => {
      setRes({ cards: r.cards?.length ?? 0, warnings: r.warnings ?? [], skipped: r.skipped ?? 0, bookId: Number(bookId) })
      qc.invalidateQueries({ queryKey: ['books'] })
      toast.success(`已写入 ${r.cards?.length ?? 0} 条设定`)
    },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteTeardown(t.id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.teardowns })
      qc.removeQueries({ queryKey: qk.teardownDetail(t.id) })
      toast.success('已删除')
      nav('/teardown', { replace: true })
    },
  })
  const toggle = (p: TeardownBiblePart) => setParts((ps) => (ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p]))

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h3 className="flex items-center gap-1.5 text-[14px] font-semibold"><Sparkles className="h-4 w-4 text-primary" />生成选题</h3>
        <p className="text-[12px] leading-relaxed text-muted-foreground">用卖点、金手指机制与开篇做种子，换皮扩写成一个选题，完成后自动打开。</p>
        {ideaJob ? <JobInline job={ideaJob} /> : (
          <Button variant="primary" className="h-11 w-full" icon={<Lightbulb className="h-4 w-4" />} onClick={() => void toIdea()}>生成选题</Button>
        )}
      </section>

      <section className="space-y-2 border-t pt-4">
        <h3 className="flex items-center gap-1.5 text-[14px] font-semibold"><Layers className="h-4 w-4 text-primary" />写入某本书设定</h3>
        {books.isLoading ? <Skeleton className="h-10 rounded-md" /> : !books.data?.length ? (
          <p className="text-[12.5px] text-muted-foreground">还没有书。<Link to="/books" className="text-primary underline-offset-2 hover:underline">去建一本</Link></p>
        ) : (
          <Select value={bookId} onChange={(v) => { setBookId(v); setRes(null) }} placeholder="选择要写入的书" className="h-10"
            options={books.data.map((b) => ({ value: String(b.id), label: b.title || `书 #${b.id}` }))} />
        )}
        <div className="space-y-1">
          {PARTS.map((p) => {
            const on = parts.includes(p.value)
            return (
              <label key={p.value} className="flex min-h-[40px] cursor-pointer items-center gap-2.5 rounded-lg px-2 hover:bg-muted/60">
                <input type="checkbox" checked={on} onChange={() => toggle(p.value)} className="h-4 w-4 shrink-0 accent-[hsl(var(--primary))]" />
                <span className="min-w-0 flex-1 text-[13.5px]">{p.label}</span>
                <span className="shrink-0 text-[11.5px] text-muted-foreground">{p.desc}</span>
              </label>
            )
          })}
        </div>
        <Button variant="soft" className="h-11 w-full" disabled={!bookId || !parts.length} loading={bible.isPending} icon={<Gem className="h-4 w-4" />} onClick={() => bible.mutate()}>写入设定（草稿）</Button>
        <p className="text-[11.5px] leading-relaxed text-muted-foreground">写入前自动存设定快照；与原文过于相似的条目会跳过。</p>
        {res && (
          <div className="space-y-1.5 rounded-lg bg-subtle px-3 py-2.5 text-[12.5px]">
            <div>写入 <b className="num">{res.cards}</b> 条{res.skipped > 0 && <>，跳过 <b className="num text-warning">{res.skipped}</b> 条</>}</div>
            {res.warnings.length > 0 && (
              <ul className="space-y-1 text-warning">{res.warnings.map((w, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words">{w}</span></li>)}</ul>
            )}
            <Link to={`/books/${res.bookId}/bible`} className="inline-flex h-10 items-center text-primary underline-offset-2 hover:underline">去设定库查看 →</Link>
          </div>
        )}
      </section>

      <section className="space-y-2 border-t pt-4">
        <Button variant="ghost" className="h-11 w-full text-danger hover:bg-danger-soft" loading={remove.isPending}
          icon={remove.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash className="h-4 w-4" />}
          onClick={() => { if (window.confirm(`删除拆书「${t.title}」？已生成的选题和设定不受影响。`)) remove.mutate() }}>删除这份拆书</Button>
        <Button variant="ghost" className="h-11 w-full" icon={<Plus className="h-4 w-4" />} onClick={() => nav('/teardown')}>再拆一本</Button>
      </section>
    </div>
  )
}
