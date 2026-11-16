import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  AlertTriangle, BookPlus, Check, ChevronDown, Compass, Copy, Flame, Info, Lightbulb, Quote, RefreshCw, Save, ShieldCheck, Sparkles, Type, Waypoints, XCircle,
} from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/misc'
import { Select } from '@/components/ui/select'
import { Tip } from '@/components/ui/tooltip'
import { ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Gender, Idea, RankBoard, TrendBoard, TrendInspiration, TrendReport, TrendReportBody } from '@/lib/types'
import { cn, copyText, fmtDateTime } from '@/lib/utils'

// ---------------------------------------------------------------- scope

export type ParsedScope =
  | { kind: 'overall' }
  | { kind: 'board'; gender: Gender; board: RankBoard }
  | { kind: 'category'; gender: Gender; board: RankBoard; category: string; legacy?: boolean }

/** overall / board:<g>:<read|new> / category:<g>:<read|new>:<name>（旧 category:<g>:<name> = 阅读榜） */
export function parseScope(scope: string): ParsedScope {
  let m = /^board:(male|female):(read|new)$/.exec(scope)
  if (m) return { kind: 'board', gender: m[1] as Gender, board: m[2] as RankBoard }
  m = /^category:(male|female):(read|new):(.+)$/.exec(scope)
  if (m) return { kind: 'category', gender: m[1] as Gender, board: m[2] as RankBoard, category: m[3] }
  // 旧写法 category:<g>:<题材>：后端保持 v0.9 行为（阅读榜 + 新书榜），标签里不写榜
  m = /^category:(male|female):(.+)$/.exec(scope)
  if (m) return { kind: 'category', gender: m[1] as Gender, board: 'read', category: m[2], legacy: true }
  return { kind: 'overall' }
}
export const boardScope = (gender: Gender, board: RankBoard, category?: string) =>
  category ? `category:${gender}:${board}:${category}` : `board:${gender}:${board}`
export const boardName = (g: Gender, b: RankBoard) => `${g === 'male' ? '男频' : '女频'}${b === 'new' ? '新书榜' : '阅读榜'}`
export function scopeLabel(scope: string) {
  const p = parseScope(scope)
  if (p.kind === 'overall') return '总榜风向标'
  if (p.kind === 'board') return boardName(p.gender, p.board)
  if (p.legacy) return `${p.gender === 'male' ? '男频' : '女频'} · ${p.category}`
  return `${boardName(p.gender, p.board)} · ${p.category}`
}
/** 面包屑：男频阅读榜 · 总榜 */
export function scopeCrumbs(scope: string): string[] {
  const p = parseScope(scope)
  if (p.kind === 'overall') return ['四榜总览']
  if (p.kind === 'category' && p.legacy) return [`${p.gender === 'male' ? '男频' : '女频'}两榜`, p.category]
  return [boardName(p.gender, p.board), p.kind === 'category' ? p.category : '总榜']
}
const boardGender = (b?: string): Gender | undefined => (!b ? undefined : b.includes('女') ? 'female' : b.includes('男') ? 'male' : undefined)
const issueNo = (iso?: string) => {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '' : `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}期`
}
const SOURCE: Record<string, string> = { web: '番茄网页榜', app: '番茄 App 榜', mock: '示例数据' }

// ---------------------------------------------------------------- data

/** 一个 scope 的最新风向标 + 历史 + 生成任务 */
export function useTrendReport(scope: string) {
  const [picked, setPicked] = useState<number | null>(null)
  useEffect(() => setPicked(null), [scope])
  const { start } = useJobs()
  const jobKey = `radar-report:${scope}`
  const job = useActiveJob(jobKey)
  const latest = useQuery({
    queryKey: qk.radarReport(scope),
    queryFn: () => api.radarReport(scope),
    retry: (n, e: any) => e?.status !== 404 && e?.status !== 400 && n < 2,
  })
  const notFound = (latest.error as any)?.status === 404 || (latest.error as any)?.status === 400
  const history = useQuery({
    queryKey: [...qk.radarReports, scope],
    queryFn: () => api.radarReports({ limit: 20, scope, full: true }),
    enabled: !!latest.data,
  })
  const list = history.data ?? []
  useEffect(() => { if (picked != null && list.length && !list.some((r) => r.id === picked)) setPicked(null) }, [list, picked])
  const shown: TrendReport | undefined = picked != null ? list.find((r) => r.id === picked) ?? latest.data : latest.data
  const isLatest = !shown || shown.id === latest.data?.id
  const generate = () => start(api.generateRadarReport({ scope }), {
    key: jobKey, label: `生成${scopeLabel(scope)}风向标`, successMsg: '风向标已生成', onSuccess: () => setPicked(null),
  })
  return { latest, history, list, shown, isLatest, notFound, picked, setPicked, job, generate }
}

// ---------------------------------------------------------------- 卡片

const LS_OPEN = 'novelos.trend-brief-open'

/**
 * v0.9.2「今日创作风向标」卡：
 * collapsible=true（榜单页内嵌）默认折叠，只露热词、总述、情绪/机会和 2 张灵感卡；
 * collapsible=false（风向标标签）始终展开。
 */
export function TrendBriefCard({ scope, collapsible = true, className }: { scope: string; collapsible?: boolean; className?: string }) {
  const t = useTrendReport(scope)
  const [openState, setOpenState] = useState(() => localStorage.getItem(LS_OPEN) === '1')
  const open = !collapsible || openState
  const setOpen = (o: boolean) => { setOpenState(o); localStorage.setItem(LS_OPEN, o ? '1' : '0') }
  const r = t.shown
  const crumbs = [...scopeCrumbs(scope), ...(r ? [fmtDateTime(r.created_at).split(' ')[0]] : [])]

  return (
    <section className={cn('overflow-hidden rounded-xl border bg-surface shadow-card', className)} aria-label="今日创作风向标">
      {/* 卡头 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b bg-gradient-to-r from-primary-soft/60 via-surface to-surface px-4 py-3 sm:px-5">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground"><Compass className="h-[17px] w-[17px]" weight="fill" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <h2 className="text-[15px] font-semibold tracking-tight">今日创作风向标</h2>
            {r && !t.isLatest && <Badge tone="neutral">往期</Badge>}
            {r?.stale && t.isLatest && <Badge tone="warning" dot>榜单已更新</Badge>}
            {r?.model === 'mock' && <Badge tone="warning">示例</Badge>}
          </div>
          <div className="mt-0.5 truncate text-[12.5px] text-muted-foreground">{crumbs.join(' · ')}</div>
        </div>
        <div className="flex w-full flex-wrap items-center gap-1.5 sm:w-auto">
          {t.list.length > 0 && (
            <div className="min-w-[150px] flex-1 sm:w-[190px] sm:flex-none">
              <Select className="h-9 text-[13px]" value={String(r?.id ?? '')} onChange={(v) => v && t.setPicked(Number(v) === t.latest.data?.id ? null : Number(v))}
                placeholder="选择往期"
                options={t.list.map((x, k) => ({ value: String(x.id), label: `${issueNo(x.created_at)}${k === 0 ? ' · 最新' : ` · ${fmtDateTime(x.created_at).slice(5)}`}` }))} />
            </div>
          )}
          {r && !t.isLatest && <Button size="sm" variant="ghost" className="h-9" onClick={() => t.setPicked(null)}>最新</Button>}
          {(r || (!t.latest.isLoading && !t.notFound)) && (
            <Button size="sm" variant={!r || r.stale ? 'primary' : 'secondary'} className="h-9" loading={!!t.job} icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={t.generate}>
              {t.job ? '生成中' : r ? '重新生成' : '生成'}
            </Button>
          )}
        </div>
      </div>

      {t.job && <div className="border-b px-4 py-3 sm:px-5"><JobInline job={t.job} /></div>}

      {t.latest.isLoading ? (
        <div className="space-y-3 p-4 sm:p-5">
          <div className="flex gap-1.5">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-7 w-20 rounded-full" />)}</div>
          <Skeleton className="h-14" />
          <div className="grid gap-3 md:grid-cols-2"><Skeleton className="h-28 rounded-xl" /><Skeleton className="h-28 rounded-xl" /></div>
        </div>
      ) : t.notFound && !r ? (
        <div className="flex flex-col items-start gap-3 px-4 py-4 sm:flex-row sm:items-center sm:px-5">
          <div className="min-w-0 flex-1">
            <div className="text-[14px] font-medium">这个榜还没有风向标</div>
            <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">读这份榜单的前排作品，总结热词、读者情绪、赛道机会和可直接立项的灵感。约 30–60 秒。</p>
          </div>
          <Button variant="primary" loading={!!t.job} icon={<Sparkles className="h-4 w-4" />} onClick={t.generate} className="h-10 shrink-0">生成风向标</Button>
        </div>
      ) : t.latest.error && !r ? (
        <ErrorState className="m-4 border-0 py-8" error={t.latest.error} onRetry={() => t.latest.refetch()} />
      ) : r?.report ? (
        <BriefBody report={r} scope={scope} open={open} />
      ) : null}

      {collapsible && r?.report && (
        <button onClick={() => setOpen(!openState)}
          className="flex h-11 w-full items-center justify-center gap-1.5 border-t text-[13px] font-medium text-primary transition hover:bg-primary-soft/40">
          {openState ? '收起' : '展开完整风向标'}<ChevronDown className={cn('h-4 w-4 transition-transform', openState && 'rotate-180')} />
        </button>
      )}
    </section>
  )
}

// ---------------------------------------------------------------- 正文

/** 旧报告兼容：从 boards[].idea_hooks 退化出灵感卡 */
export function inspirationsOf(r: TrendReportBody): TrendInspiration[] {
  if (r.inspirations?.length) return r.inspirations
  return (r.boards ?? []).flatMap((b) => (b.idea_hooks ?? []).map((h) => ({ title: h.title, logline: h.pitch, board: b.board })))
}

function BriefBody({ report, scope, open }: { report: TrendReport; scope: string; open: boolean }) {
  const r = report.report!
  const boards = r.boards ?? []
  const one = boards.length === 1 ? boards[0] : null
  const insp = inspirationsOf(r)
  const summary = r.summary || one?.overview || ''
  const mood = boardTexts(boards, 'reader_mood')
  const chance = boardTexts(boards, 'opportunity')
  const advice = r.writing_advice || boards.map((b) => b.writing_tips).filter(Boolean).join('\n')
  const risks = r.risk_alerts?.length ? r.risk_alerts : boards.flatMap((b) => riskList(b.risks))
  const meta = r.meta ?? {}
  const topN = meta.top_n ?? r.inputs?.top_n
  const nBooks = meta.books_read ?? meta.books ?? r.inputs?.books
  const visible = open ? insp : insp.slice(0, 2)

  return (
    <div className="space-y-4 p-4 sm:space-y-5 sm:p-5">
      {/* 热词 */}
      {!!r.hot_words?.length && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 inline-flex items-center gap-1 text-[12px] font-medium text-muted-foreground"><Flame className="h-3.5 w-3.5 text-danger" />创作热词</span>
          {r.hot_words.map((h, i) => (
            <Tip key={h.word + i} content={h.why || null}>
              <span className={cn('inline-flex h-7 items-center rounded-full px-3 text-[12.5px] font-medium', i < 3 ? 'bg-danger-soft text-danger' : 'bg-muted text-foreground/75')}>#{h.word}</span>
            </Tip>
          ))}
        </div>
      )}

      {/* 总述 */}
      {(r.headline || summary) && (
        <div>
          {r.headline && <h3 className="font-serif text-[18px] font-bold leading-snug tracking-tight">{r.headline}</h3>}
          {summary && <p className={cn('text-[13.5px] leading-[1.75] text-foreground/80', r.headline && 'mt-1.5')}>{summary}</p>}
        </div>
      )}

      {(mood.length > 0 || chance.length > 0) && (
        <div className="grid gap-3 md:grid-cols-2">
          {mood.length > 0 && <MiniPanel title="读者情绪" icon={<Quote className="h-3.5 w-3.5" />} items={mood} tone="warm" />}
          {chance.length > 0 && <MiniPanel title="赛道机会" icon={<Waypoints className="h-3.5 w-3.5" />} items={chance} tone="cool" />}
        </div>
      )}

      {/* 灵感推荐 + 侧栏 */}
      {insp.length > 0 && (
        <div className={cn(open && (advice || risks.length) && 'grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]')}>
          <div>
            <div className="mb-2.5 flex items-baseline justify-between gap-2">
              <div className="flex items-center gap-1.5 text-[13.5px] font-semibold"><Lightbulb className="h-4 w-4 text-warning" />灵感推荐</div>
              <span className="text-[12px] text-muted-foreground">{open ? `${insp.length} 个` : `${Math.min(2, insp.length)} / ${insp.length}`} · 可直接立项</span>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              {visible.map((x, i) => (
                <motion.div key={x.title + i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: Math.min(i, 6) * 0.04, duration: 0.25 }} className="flex">
                  <InspirationCard insp={x} scope={scope} reportId={report.id} idx={i} />
                </motion.div>
              ))}
            </div>
          </div>
          {open && (advice || risks.length > 0) && (
            <aside className="grid content-start gap-3 sm:grid-cols-2 xl:grid-cols-1">
              {advice && (
                <div className="rounded-xl border bg-success-soft/30 p-3.5">
                  <div className="flex items-center gap-1.5 text-[13px] font-semibold text-success"><ShieldCheck className="h-4 w-4" />写作建议</div>
                  <div className="mt-1.5 space-y-1.5 text-[13px] leading-relaxed text-foreground/85">{advice.split('\n').filter(Boolean).map((l, i) => <p key={i}>{l}</p>)}</div>
                </div>
              )}
              {risks.length > 0 && (
                <div className="rounded-xl border bg-warning-soft/40 p-3.5">
                  <div className="flex items-center gap-1.5 text-[13px] font-semibold text-warning"><AlertTriangle className="h-4 w-4" />风险提醒</div>
                  <ul className="mt-1.5 space-y-1.5">{risks.map((x, i) => <li key={i} className="flex gap-1.5 text-[13px] leading-relaxed"><span className="mt-[0.6em] h-1 w-1 shrink-0 rounded-full bg-warning" /><span className="min-w-0 break-words">{x}</span></li>)}</ul>
                </div>
              )}
            </aside>
          )}
        </div>
      )}

      {open && <FullSections r={r} />}

      {open && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t pt-3 text-[12px] text-muted-foreground">
          <span>生成于 <span className="num">{fmtDateTime(report.created_at)}</span></span>
          <span>模型 <span className="font-mono">{report.model || '—'}</span></span>
          {report.snapshot && <span>榜单 {SOURCE[report.snapshot.source] ?? report.snapshot.source} · <span className="num">{fmtDateTime(report.snapshot.taken_at)}</span></span>}
          {nBooks ? <span className="num">读了 {nBooks} 本{topN ? `（每榜前 ${topN}）` : ''}</span> : null}
        </div>
      )}
    </div>
  )
}

const riskList = (x?: string | string[]) => (Array.isArray(x) ? x : x ? [x] : []).filter(Boolean)

function boardTexts(boards: TrendBoard[], k: 'reader_mood' | 'opportunity'): { label?: string; text: string }[] {
  const xs = boards.filter((b) => b[k])
  return xs.map((b) => ({ label: xs.length > 1 ? b.board : undefined, text: b[k] }))
}

function MiniPanel({ title, icon, items, tone }: { title: string; icon: React.ReactNode; items: { label?: string; text: string }[]; tone: 'warm' | 'cool' }) {
  return (
    <div className={cn('rounded-xl p-3.5 hairline', tone === 'warm' ? 'bg-primary-soft/40' : 'bg-sky-50/70 dark:bg-sky-950/20')}>
      <div className={cn('flex items-center gap-1.5 text-[12.5px] font-semibold', tone === 'warm' ? 'text-primary' : 'text-sky-700 dark:text-sky-300')}>{icon}{title}</div>
      <div className="mt-1.5 space-y-1.5">
        {items.map((x, i) => (
          <p key={i} className="text-[13px] leading-relaxed text-foreground/85">
            {x.label && <span className="mr-1.5 rounded bg-surface px-1.5 py-px text-[11.5px] font-medium text-muted-foreground hairline">{x.label}</span>}{x.text}
          </p>
        ))}
      </div>
    </div>
  )
}

/** 展开后：四栏工具区 + 各榜细览 + 开坑方向 + 校验记录 */
function FullSections({ r }: { r: TrendReportBody }) {
  const copy = async (t: string) => { (await copyText(t)) ? toast.success('已复制') : toast.info('复制失败，请长按选中后手动复制') }
  const tools = [
    r.title_patterns?.length ? (
      <ToolCol key="t" title="标题句式" icon={<Type className="h-3.5 w-3.5" />}>
        {r.title_patterns.map((t, i) => (
          <li key={i} className="group rounded-lg bg-subtle/70 px-2.5 py-2">
            <div className="flex items-start gap-1">
              <PatternText text={t.pattern} />
              <button aria-label="复制句式" onClick={() => copy(t.pattern)} className="-mr-1 -mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"><Copy className="h-3.5 w-3.5" /></button>
            </div>
            {!!t.examples?.length && <div className="mt-1 truncate text-[11.5px] text-muted-foreground">例：{t.examples.map((e) => `《${e.replace(/^《|》$/g, '')}》`).join(' ')}</div>}
          </li>
        ))}
      </ToolCol>
    ) : null,
    r.opening_hooks?.length ? (
      <ToolCol key="o" title="开篇钩子" icon={<Sparkles className="h-3.5 w-3.5" />}>
        {r.opening_hooks.map((h, i) => <NumLi key={i} n={i + 1}>{h}</NumLi>)}
      </ToolCol>
    ) : null,
    r.plot_devices?.length ? (
      <ToolCol key="p" title="剧情装置" icon={<Waypoints className="h-3.5 w-3.5" />}>
        {r.plot_devices.map((d, i) => (
          <li key={i} className="text-[13px] leading-relaxed">
            <span className="font-semibold text-primary">【{d.name.replace(/^【|】$/g, '')}】</span><span className="text-foreground/80">{d.desc}</span>
          </li>
        ))}
      </ToolCol>
    ) : null,
    r.pitfalls?.length ? (
      <ToolCol key="x" title="避坑提醒" icon={<XCircle className="h-3.5 w-3.5" />} danger>
        {r.pitfalls.map((d, i) => <li key={i} className="flex gap-1.5 text-[13px] leading-relaxed"><XCircle className="mt-[3px] h-3.5 w-3.5 shrink-0 text-danger" /><span className="min-w-0 break-words">{d}</span></li>)}
      </ToolCol>
    ) : null,
  ].filter(Boolean)
  const multi = (r.boards ?? []).length > 1

  return (
    <>
      {tools.length > 0 && <div className={cn('grid gap-3 sm:grid-cols-2', tools.length >= 4 ? 'xl:grid-cols-4' : tools.length === 3 ? 'xl:grid-cols-3' : '')}>{tools}</div>}

      {!!r.open_directions?.length && (
        <div className="rounded-xl p-3.5 hairline">
          <div className="flex items-center gap-1.5 text-[13px] font-semibold"><Compass className="h-4 w-4 text-primary" />开坑方向</div>
          <ol className="mt-2 grid gap-x-5 gap-y-1.5 md:grid-cols-2">{r.open_directions.map((d, i) => <NumLi key={i} n={i + 1}>{d}</NumLi>)}</ol>
        </div>
      )}

      {multi && (
        <div>
          <div className="mb-2.5 text-[13.5px] font-semibold">各榜细览</div>
          <div className="grid gap-3 lg:grid-cols-2">
            {r.boards.map((b, i) => <BoardMini key={b.board + i} b={b} />)}
          </div>
        </div>
      )}

      {!!r.warnings?.length && (
        <details className="group rounded-xl border bg-subtle/40 px-3.5 py-2.5 text-[12.5px]">
          <summary className="flex min-h-[32px] cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
            <Info className="h-4 w-4" />程序校验记录 <span className="num">{r.warnings.length}</span>
            <span className="ml-auto text-[11.5px] group-open:hidden">展开</span>
          </summary>
          <ul className="mt-2 space-y-1 pl-6 leading-relaxed text-foreground/70">{r.warnings.map((w, i) => <li key={i} className="list-disc">{w}</li>)}</ul>
        </details>
      )}
    </>
  )
}

function ToolCol({ title, icon, children, danger }: { title: string; icon: React.ReactNode; children: React.ReactNode; danger?: boolean }) {
  return (
    <div className={cn('rounded-xl p-3.5 hairline', danger ? 'bg-danger-soft/30' : 'bg-surface')}>
      <div className={cn('mb-2 flex items-center gap-1.5 text-[13px] font-semibold', danger && 'text-danger')}>
        <span className={cn('flex h-6 w-6 items-center justify-center rounded-md', danger ? 'bg-danger-soft' : 'bg-muted text-foreground/70')}>{icon}</span>{title}
      </div>
      <ul className="space-y-2">{children}</ul>
    </div>
  )
}
function NumLi({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <li className="flex gap-2 text-[13px] leading-relaxed">
      <span className="num mt-[2px] flex h-[18px] w-[18px] shrink-0 items-center justify-center rounded-full bg-primary-soft text-[10.5px] font-semibold text-primary">{n}</span>
      <span className="min-w-0 break-words">{children}</span>
    </li>
  )
}

export function PatternText({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]*\])/g).filter(Boolean)
  return (
    <div className="min-w-0 flex-1 text-[13.5px] font-semibold leading-relaxed">
      {parts.map((p, i) => p.startsWith('[')
        ? <span key={i} className="mx-0.5 rounded bg-primary-soft px-1 py-px text-[12.5px] font-medium text-primary">{p.slice(1, -1)}</span>
        : <span key={i}>{p}</span>)}
    </div>
  )
}

function BoardMini({ b }: { b: TrendBoard }) {
  const rows = ([['总览', b.overview], ['读者情绪', b.reader_mood], ['机会判断', b.opportunity], ['写作建议', b.writing_tips]] as [string, string][]).filter(([, v]) => !!v)
  const isNew = b.board.includes('新书')
  return (
    <div className="rounded-xl p-3.5 hairline">
      <div className="flex items-center gap-2"><span className="text-[14px] font-semibold">{b.board}</span><Badge tone={isNew ? 'primary' : 'neutral'}>{isNew ? '新书榜' : '阅读榜'}</Badge></div>
      <dl className="mt-2 space-y-1.5">
        {rows.map(([k, v]) => <div key={k} className="flex gap-2 text-[13px] leading-relaxed"><dt className="w-14 shrink-0 text-[12px] text-muted-foreground">{k}</dt><dd className="min-w-0 flex-1">{v}</dd></div>)}
      </dl>
      {riskList(b.risks).length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{riskList(b.risks).map((x, i) => <span key={i} className="rounded-md bg-warning-soft px-2 py-0.5 text-[12px] text-warning">{x}</span>)}</div>}
    </div>
  )
}

// ---------------------------------------------------------------- 灵感卡

/** 灵感卡：书名式标题 + 强调色一句话 + 主角/机制/开局 + 3 个卖点胶囊 + 立项按钮 */
export function InspirationCard({ insp: x, scope, reportId, idx, className }: { insp: TrendInspiration; scope: string; reportId?: number; idx: number; className?: string }) {
  const nav = useNavigate()
  const { start } = useJobs()
  const key = `seed:${reportId ?? 'x'}:${idx}`
  const job = useActiveJob(key)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<Idea | null>(null)
  const p = parseScope(scope)
  const seed = useMemo(() => ({
    title: x.title, logline: x.logline, protagonist: x.protagonist, mechanism: x.mechanism, opening: x.opening, selling_points: x.selling_points,
    genre: p.kind === 'category' ? p.category : undefined,
    gender: boardGender(x.board) ?? (p.kind !== 'overall' ? p.gender : undefined),
    source: { type: 'trend_report' as const, ref: scope, report_id: reportId },
  }), [x, scope, reportId]) // eslint-disable-line react-hooks/exhaustive-deps
  const rows = ([['主角', x.protagonist], ['机制', x.mechanism], ['开局', x.opening]] as [string, string | undefined][]).filter(([, v]) => !!v)
  const sps = (x.selling_points ?? []).filter(Boolean).slice(0, 3)

  const expand = () => start(api.ideaFromSeedJob(seed), {
    key, label: `立项《${x.title}》`, successMsg: '已立项，打开选题详情',
    onSuccess: (j) => { const id = (j.result?.idea as Idea | undefined)?.id ?? j.result?.idea_id; if (id) nav(`/ideas/${id}`) },
  })
  const save = async () => {
    setSaving(true)
    try {
      const { idea } = await api.ideaFromSeed(seed)
      setSaved(idea)
      toast.success(`已存为选题《${idea.title}》`, { action: { label: '打开', onClick: () => nav(`/ideas/${idea.id}`) } })
    } catch (e: any) {
      toast.error('保存失败', { description: e?.message })
    } finally { setSaving(false) }
  }

  return (
    <div className={cn('flex w-full flex-col rounded-xl border bg-surface p-4 transition hover:border-foreground/15 hover:shadow-lift', className)}>
      <div className="flex items-start justify-between gap-2">
        <h4 className="min-w-0 break-words text-[15.5px] font-bold leading-snug tracking-tight">{x.title.replace(/^《|》$/g, '')}</h4>
        {x.board && <span className="mt-0.5 shrink-0 rounded bg-muted px-1.5 py-px text-[11px] text-muted-foreground">{x.board}</span>}
      </div>
      {x.logline && <p className="mt-1.5 text-[13.5px] font-medium leading-relaxed text-primary">{x.logline}</p>}
      {rows.length > 0 && (
        <dl className="mt-3 space-y-1.5">
          {rows.map(([k, v]) => (
            <div key={k} className="flex gap-2 text-[13px] leading-relaxed">
              <dt className="mt-[2px] flex h-[19px] shrink-0 items-center rounded bg-muted px-1.5 text-[11.5px] font-medium text-muted-foreground">{k}</dt>
              <dd className="min-w-0 flex-1 break-words text-foreground/85">{v}</dd>
            </div>
          ))}
        </dl>
      )}
      {sps.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {sps.map((s) => <span key={s} className="inline-flex min-h-[24px] items-center rounded-full bg-sky-50 px-2.5 text-[12px] font-medium text-sky-700 dark:bg-sky-950/40 dark:text-sky-300">{s}</span>)}
        </div>
      )}
      {job && <JobInline job={job} className="mt-3" />}
      <div className="mt-auto flex flex-wrap gap-2 pt-3.5">
        <Button size="sm" variant="primary" className="h-9 flex-1" loading={!!job} icon={<BookPlus className="h-3.5 w-3.5" />} onClick={expand}>{job ? '立项中' : '用这个立项'}</Button>
        {saved ? (
          <Button size="sm" variant="soft" className="h-9" icon={<Check className="h-3.5 w-3.5" />} onClick={() => nav(`/ideas/${saved.id}`)}>已保存 · 打开</Button>
        ) : (
          <Button size="sm" variant="ghost" className="h-9" loading={saving} icon={<Save className="h-3.5 w-3.5" />} onClick={save}>直接存为选题</Button>
        )}
      </div>
    </div>
  )
}
