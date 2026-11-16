import { useEffect, useState, useSyncExternalStore } from 'react'
import * as D from '@radix-ui/react-dialog'
import { useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, ArrowUpRight, BookOpen, Check, ChevronDown, Copy, Feather, ImagePlus, Info, Quote, RefreshCw, Sparkles, Type, X,
} from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/misc'
import { JobInline } from '@/components/common/JobInline'
import { BookCover } from '@/components/radar/BookCover'
import { BoardTag, RankDiff, RankNumber, fmtAgoDays } from '@/components/radar/ShelfCard'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { RadarAiKind, RadarAiResult, RadarChapterLink, RankItem } from '@/lib/types'
import { cn, copyText, fmtDateTime, fmtNum } from '@/lib/utils'

// ---------- AI 候选结果的小 store：任务在抽屉关掉后完成也能留住，重新打开还在 ----------
type AiMap = Record<string, Partial<Record<RadarAiKind, RadarAiResult>>>
let aiStore: AiMap = {}
const aiListeners = new Set<() => void>()
const setAi = (ext: string, kind: RadarAiKind, r: RadarAiResult) => {
  aiStore = { ...aiStore, [ext]: { ...aiStore[ext], [kind]: r } }
  aiListeners.forEach((l) => l())
}
const useAi = (ext: string) => useSyncExternalStore((l) => { aiListeners.add(l); return () => aiListeners.delete(l) }, () => aiStore[ext])

const AI_META: Record<RadarAiKind, { label: string; short: string; icon: React.ReactNode; desc: string }> = {
  title: { label: 'AI 书名', short: '书名', icon: <Type className="h-4 w-4" />, desc: '参考这本书的卖点，起几个同赛道但不撞名的书名' },
  cover: { label: 'AI 封面词', short: '封面词', icon: <ImagePlus className="h-4 w-4" />, desc: '生成可直接用于生图的封面提示词' },
  blurb: { label: 'AI 简介', short: '简介', icon: <Quote className="h-4 w-4" />, desc: '仿照它的钩子结构写几版新简介' },
}

/** 榜单书详情抽屉：平板/桌面右侧，手机底部 */
export function BookDetailDrawer({ item, onClose, onImitate, onAnalyze }: {
  item: RankItem | null; onClose: () => void; onImitate: (i: RankItem) => void; onAnalyze: (i: RankItem) => void
}) {
  const [shown, setShown] = useState<RankItem | null>(item)
  useEffect(() => { if (item) setShown(item) }, [item])
  return (
    <D.Root open={!!item} onOpenChange={(o) => { if (!o) onClose() }}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[1px] data-[state=open]:animate-fade-in" />
        <D.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          className={cn(
            'fixed z-50 flex flex-col bg-background shadow-pop hairline focus:outline-none',
            'inset-x-0 bottom-0 max-h-[94dvh] rounded-t-2xl data-[state=open]:animate-slide-in-up',
            'md:inset-y-0 md:left-auto md:right-0 md:h-full md:max-h-none md:w-[min(960px,100vw)] md:rounded-none md:data-[state=open]:animate-slide-in-right',
          )}
        >
          <div className="mx-auto mt-2 h-1.5 w-10 shrink-0 rounded-full bg-muted md:hidden" aria-hidden />
          {shown && <Body key={shown.book_id_ext} item={shown} onClose={onClose} onImitate={onImitate} onAnalyze={onAnalyze} />}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

function Body({ item: base, onClose, onImitate, onAnalyze }: { item: RankItem; onClose: () => void; onImitate: (i: RankItem) => void; onAnalyze: (i: RankItem) => void }) {
  const ext = base.book_id_ext
  const q = useQuery({ queryKey: qk.radarBookDetail(ext), queryFn: () => api.radarBookDetail(ext), staleTime: 10 * 60_000, retry: 1 })
  const d = q.data
  const ok = !!d && !d.detail_error
  // 详情里的 item 可能更新；但保留列表项的 id（仿写接口要用）
  const item: RankItem = ok ? { ...base, ...d!.item, id: base.id ?? d!.item.id } : base
  const total = (ok && d!.chapter_total) || item.chapter_count || 0
  const abstract = (ok && d!.abstract) || item.abstract
  const tags = [...new Set([item.category, ...(item.tags ?? [])].filter(Boolean))]
  const ago = fmtAgoDays(item.last_update_at)
  const ai = useAi(ext)
  const [aiTab, setAiTab] = useState<RadarAiKind | null>(null)
  const { start } = useJobs()
  const jobs = {
    title: useActiveJob(`radar-ai:${ext}:title`),
    cover: useActiveJob(`radar-ai:${ext}:cover`),
    blurb: useActiveJob(`radar-ai:${ext}:blurb`),
  }
  useEffect(() => { if (!aiTab && ai) setAiTab((['title', 'cover', 'blurb'] as RadarAiKind[]).find((k) => ai[k]) ?? null) }, [ai, aiTab])
  const runAi = (kind: RadarAiKind) => {
    setAiTab(kind)
    if (jobs[kind]) return
    void start(api.radarBookAi(ext, kind), {
      key: `radar-ai:${ext}:${kind}`, label: `${AI_META[kind].label}《${item.title}》`, silent: true,
      onSuccess: (j) => {
        const r = (j.result ?? {}) as Partial<RadarAiResult>
        setAi(ext, kind, { kind, candidates: r.candidates ?? [], dropped: r.dropped ?? 0, warnings: r.warnings ?? [] })
        toast.success(`${AI_META[kind].label}已生成`, { description: `《${item.title}》· ${(r.candidates ?? []).length} 条候选` })
      },
    })
  }
  const go = (fn: (i: RankItem) => void) => { onClose(); setTimeout(() => fn(item), 180) }

  return (
    <>
      <div className="flex items-center gap-3 border-b px-5 pb-3 pt-2.5 md:pt-4">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><BookOpen className="h-[17px] w-[17px]" weight="duotone" /></span>
        <div className="min-w-0 flex-1">
          <D.Title className="truncate text-[15px] font-semibold tracking-tight">书籍详情</D.Title>
          <D.Description className="num truncate text-[12px] text-muted-foreground">
            {item.board === 'new' ? '新书榜' : '阅读榜'} · {item.category} 第 {item.rank} 名{ok && d!.fetched_at ? ` · 抓取于 ${fmtDateTime(d!.fetched_at)}` : ''}
          </D.Description>
        </div>
        <D.Close className="focus-ring -mr-1.5 flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted" aria-label="关闭"><X className="h-4 w-4" /></D.Close>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="grid gap-6 px-5 py-5 md:grid-cols-[248px_minmax(0,1fr)] md:gap-7 md:px-6">
          {/* 左栏 */}
          <aside className="md:sticky md:top-5 md:self-start">
            <div className="flex gap-4 md:flex-col md:gap-0">
              <div className="relative w-[118px] shrink-0 sm:w-[136px] md:w-full">
                <BookCover src={item.cover} title={item.title} size="lg" className="w-full rounded-lg" />
              </div>
              <div className="min-w-0 flex-1 md:mt-4">
                <div className="flex items-start gap-2">
                  <RankNumber n={item.rank} className="mt-0.5 !text-[24px]" />
                  <h2 className="min-w-0 flex-1 text-[19px] font-bold leading-snug tracking-tight">{item.title}</h2>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[13px] text-muted-foreground">
                  <span>{item.author || '佚名'}</span><BoardTag board={item.board} /><RankDiff v={item.rank_diff} />
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {tags.slice(0, 6).map((t, k) => (
                    <span key={t} className={cn('h-6 rounded-md px-2 text-[12px] leading-6', k === 0 ? 'bg-primary-soft font-medium text-primary' : 'bg-muted text-muted-foreground')}>{t}</span>
                  ))}
                </div>
                <div className="mt-3.5 grid grid-cols-2 gap-2">
                  <NumBlock label="在读" value={fmtNum(item.read_count)} />
                  <NumBlock label="章节" value={total > 0 ? total.toLocaleString('zh-CN') : '—'} loading={q.isLoading && !item.chapter_count} />
                </div>
                <div className="num mt-2.5 space-y-1 text-[12px] text-muted-foreground">
                  <div>{fmtNum(item.word_count)} 字{ago ? ` · ${ago}` : ''}</div>
                  {item.last_chapter_title && <div className="line-clamp-2">最新：{item.last_chapter_title}</div>}
                </div>
              </div>
            </div>
          </aside>

          {/* 右栏 */}
          <div className="min-w-0 space-y-5">
            <section className="rounded-xl border bg-surface px-4 py-3.5">
              <div className="mb-1.5 flex items-center justify-between gap-2">
                <h3 className="text-[13px] font-semibold text-muted-foreground">简介</h3>
                {abstract && <CopyBtn text={abstract} />}
              </div>
              {q.isLoading && !abstract ? <div className="space-y-2"><Skeleton className="h-4" /><Skeleton className="h-4" /><Skeleton className="h-4 w-2/3" /></div>
                : <p className="whitespace-pre-line text-[14px] leading-[1.75] text-foreground/85">{abstract || '暂无简介'}</p>}
              {d?.detail_error && (
                <p className="mt-2.5 flex items-start gap-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
                  <Info className="mt-[2px] h-3.5 w-3.5 shrink-0" /><span>详情没取到（{d.detail_error}），这里只显示榜单里的信息。</span>
                </p>
              )}
              {q.error && <p className="mt-2.5 flex items-center gap-1.5 text-[11.5px] text-muted-foreground"><Info className="h-3.5 w-3.5" />详情加载失败，这里只显示榜单里的信息。<button className="text-primary hover:underline" onClick={() => q.refetch()}>重试</button></p>}
            </section>

            <section>
              <div className="grid grid-cols-3 gap-2">
                <Button variant="primary" size="lg" className={item.source_url ? 'col-span-2' : 'col-span-3'} icon={<Feather className="h-4 w-4" />} onClick={() => go(onImitate)}>仿写立项</Button>
                {item.source_url && (
                  <a href={item.source_url} target="_blank" rel="noopener noreferrer"
                    className="focus-ring inline-flex h-10 items-center justify-center gap-1 whitespace-nowrap rounded-lg border bg-surface px-2 text-[14px] font-medium shadow-xs transition hover:bg-subtle">
                    番茄原文<ArrowUpRight className="h-4 w-4 shrink-0" />
                  </a>
                )}
                {(['title', 'cover', 'blurb'] as RadarAiKind[]).map((k) => (
                  <Button key={k} size="lg" variant={aiTab === k ? 'soft' : 'secondary'} className="px-2" loading={!!jobs[k]} icon={AI_META[k].icon} onClick={() => runAi(k)}>{AI_META[k].label}</Button>
                ))}
              </div>
              <button onClick={() => go(onAnalyze)} className="mt-2.5 inline-flex items-center gap-1 text-[12.5px] text-muted-foreground hover:text-primary">
                <Sparkles className="h-3.5 w-3.5" />AI 结构拆解（爽点、金手指、开篇钩子）
              </button>
            </section>

            {aiTab && (
              <AiResults kind={aiTab} onTab={setAiTab} results={ai} jobs={jobs} onRun={runAi} />
            )}

            <section>
              <h3 className="mb-2 flex items-center gap-2 text-[14px] font-semibold">目录
                {total > 0 && <span className="num text-[12px] font-normal text-muted-foreground">共 {total.toLocaleString('zh-CN')} 章</span>}
              </h3>
              {q.isLoading ? (
                <div className="space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
              ) : ok && (d!.chapters_head.length || d!.chapters_tail.length) ? (
                <div className="space-y-2.5">
                  {d!.chapters_tail.length > 0 && <ChapterGroup title={`最新 ${d!.chapters_tail.length} 章`} list={d!.chapters_tail} defaultOpen startNo={total > 0 ? total - d!.chapters_tail.length + 1 : null} reverse />}
                  {d!.chapters_head.length > 0 && <ChapterGroup title={`前 ${d!.chapters_head.length} 章`} list={d!.chapters_head} defaultOpen={false} startNo={1} />}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed px-4 py-6 text-center text-[13px] text-muted-foreground">
                  暂无目录{item.first_chapter_url && <> · <a className="text-primary hover:underline" href={item.first_chapter_url} target="_blank" rel="noopener noreferrer">从第一章开始读</a></>}
                </div>
              )}
            </section>
          </div>
        </div>
        <div className="pb-[max(1rem,env(safe-area-inset-bottom))]" />
      </div>
    </>
  )
}

function NumBlock({ label, value, loading }: { label: string; value: string; loading?: boolean }) {
  return (
    <div className="rounded-lg border bg-surface px-3 py-2">
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
      {loading ? <Skeleton className="mt-1 h-6 w-14" /> : <div className="num mt-0.5 text-[19px] font-semibold leading-tight">{value}</div>}
    </div>
  )
}

function CopyBtn({ text, label = '复制', className }: { text: string; label?: string; className?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={async (e) => { e.stopPropagation(); if (await copyText(text)) { setDone(true); setTimeout(() => setDone(false), 1400) } else toast.error('复制失败，请长按手动复制') }}
      className={cn('focus-ring inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-muted-foreground transition hover:bg-muted hover:text-foreground', done && 'text-success', className)}>
      {done ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}{done ? '已复制' : label}
    </button>
  )
}

function AiResults({ kind, onTab, results, jobs, onRun }: {
  kind: RadarAiKind; onTab: (k: RadarAiKind) => void; results?: Partial<Record<RadarAiKind, RadarAiResult>>
  jobs: Record<RadarAiKind, ReturnType<typeof useActiveJob>>; onRun: (k: RadarAiKind) => void
}) {
  const r = results?.[kind]
  const job = jobs[kind]
  return (
    <section className="rounded-xl border bg-subtle/50 p-3.5">
      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {(['title', 'cover', 'blurb'] as RadarAiKind[]).map((k) => (
          <button key={k} onClick={() => onTab(k)}
            className={cn('inline-flex h-8 items-center gap-1 rounded-lg px-3 text-[13px] transition', k === kind ? 'bg-foreground text-background' : 'bg-surface text-foreground/70 hairline hover:text-foreground')}>
            {AI_META[k].short}{results?.[k] && <span className="num opacity-60">{results[k]!.candidates.length}</span>}{jobs[k] && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />}
          </button>
        ))}
        {r && !job && <Button size="xs" variant="ghost" className="ml-auto h-8" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => onRun(kind)}>换一批</Button>}
      </div>
      <p className="mb-3 text-[12px] text-muted-foreground">{AI_META[kind].desc}</p>
      {job && <JobInline job={job} className="mb-3" />}
      {!r ? (
        job ? <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-[72px] rounded-xl" />)}</div> : (
          <div className="rounded-xl border border-dashed bg-surface px-4 py-6 text-center">
            <Button variant="soft" icon={AI_META[kind].icon} onClick={() => onRun(kind)}>生成{AI_META[kind].short}</Button>
          </div>
        )
      ) : (
        <div className={cn('space-y-2', job && 'opacity-55')}>
          {r.dropped > 0 && (
            <p className="flex items-start gap-1.5 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning"><AlertTriangle className="h-3.5 w-3.5 shrink-0" /><span>已过滤与原书过于相似的 {r.dropped} 条{r.warnings?.length ? <span className="mt-0.5 block text-[11.5px] opacity-80">{r.warnings.join('；')}</span> : null}</span></p>
          )}
          {!r.candidates.length && <p className="rounded-lg bg-surface px-3 py-4 text-center text-[13px] text-muted-foreground">没有可用的候选，换一批试试</p>}
          {r.candidates.map((c: any, i) => {
            const main: string = kind === 'title' ? c.title : kind === 'cover' ? c.prompt : c.blurb
            const sub: string = kind === 'title' ? c.why : kind === 'cover' ? c.style : c.hook
            return (
              <div key={i} className="rounded-xl border bg-surface px-3.5 py-3">
                <div className="flex items-start gap-2">
                  <span className="num mt-[3px] flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-muted text-[11px] font-semibold text-muted-foreground">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className={cn('break-words', kind === 'title' ? 'text-[15.5px] font-bold' : kind === 'cover' ? 'font-mono text-[12.5px] leading-relaxed' : 'whitespace-pre-line text-[13.5px] leading-[1.7]')}>{main}</p>
                    {sub && (
                      <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">
                        {kind === 'cover' ? <Badge tone="outline" className="mr-1">风格</Badge> : kind === 'blurb' ? <Badge tone="primary" className="mr-1">钩子</Badge> : null}{sub}
                      </p>
                    )}
                  </div>
                  <CopyBtn text={main} className="-mr-1 -mt-1" />
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function ChapterGroup({ title, list, defaultOpen, startNo, reverse }: { title: string; list: RadarChapterLink[]; defaultOpen: boolean; startNo: number | null; reverse?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const rows = list.map((c, i) => ({ c, no: startNo ? startNo + i : null }))
  const shown = reverse ? [...rows].reverse() : rows
  return (
    <div className="overflow-hidden rounded-xl border bg-surface">
      <button onClick={() => setOpen((o) => !o)} className="flex h-11 w-full items-center gap-2 px-4 text-left text-[13.5px] font-medium">
        <span className="flex-1">{title}</span>
        <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform', open && 'rotate-180')} />
      </button>
      {open && (
        <ul className="max-h-[420px] overflow-y-auto overscroll-contain border-t">
          {shown.map(({ c, no }) => (
            <li key={c.item_id || c.url}>
              <a href={c.url} target="_blank" rel="noopener noreferrer"
                className="group flex min-h-[42px] items-center gap-3 border-b border-border/50 px-4 py-2 text-[13.5px] transition last:border-0 hover:bg-subtle">
                {no !== null && <span className="num w-9 shrink-0 text-right text-[11.5px] text-muted-foreground">{no}</span>}
                <span className="min-w-0 flex-1 truncate">{c.title}</span>
                <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50 transition group-hover:text-primary" />
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
