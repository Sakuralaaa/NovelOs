import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { AlertTriangle, BookPlus, Compass, Copy, Flame, Info, Lightbulb, RefreshCw, Sparkles, Type, XCircle } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { Select } from '@/components/ui/select'
import { Segmented } from '@/components/ui/tabs'
import { EmptyState, ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { QuickCreateDialog } from '@/components/common/BookBits'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Gender, TrendBoard, TrendReport, TrendReportBody } from '@/lib/types'
import { cn, copyText, fmtDateTime } from '@/lib/utils'

const SOURCE: Record<string, string> = { web: '番茄网页榜', app: '番茄 App 榜', mock: '示例数据' }
const LS_SCOPE = 'novelos.trend-scope'

export function scopeLabel(scope: string) {
  if (scope === 'overall') return '总榜风向标'
  const m = /^category:(male|female):(.+)$/.exec(scope)
  return m ? `${m[1] === 'male' ? '男频' : '女频'} · ${m[2]}` : scope
}
function parseScope(scope: string): { gender: Gender; category: string } | null {
  const m = /^category:(male|female):(.+)$/.exec(scope)
  return m ? { gender: m[1] as Gender, category: m[2] } : null
}
const boardGender = (b: string): Gender => (b.startsWith('女') ? 'female' : 'male')

/** v0.9 风向标日报：最新一份 + 历史切换 + 生成/重新生成（后台 Job） */
export function TrendReportView() {
  const [scope, setScopeState] = useState<string>(() => localStorage.getItem(LS_SCOPE) || 'overall')
  const setScope = (s: string) => { setScopeState(s); setPicked(null); localStorage.setItem(LS_SCOPE, s) }
  const parsed = parseScope(scope)
  const [mode, setMode] = useState<'overall' | 'category'>(parsed ? 'category' : 'overall')
  const [catGender, setCatGender] = useState<Gender>(parsed?.gender ?? 'male')
  const [picked, setPicked] = useState<number | null>(null)
  const { start } = useJobs()
  const job = useActiveJob(`radar-report:${scope}`)

  const latest = useQuery({
    queryKey: qk.radarReport(scope),
    queryFn: () => api.radarReport(scope),
    retry: (n, e: any) => e?.status !== 404 && e?.status !== 400 && n < 2,
  })
  const history = useQuery({
    queryKey: [...qk.radarReports, scope],
    queryFn: () => api.radarReports({ limit: 15, scope, full: true }),
  })
  // 题材风向标：从最新快照里取该频道的题材
  const snapCats = useQuery({
    queryKey: qk.radarLatest(catGender),
    queryFn: () => api.radarLatest({ gender: catGender }),
    enabled: mode === 'category',
  })
  const cats = useMemo(() => {
    const m = new Map<string, number>()
    ;(snapCats.data?.items ?? []).forEach((i) => m.set(i.category, (m.get(i.category) ?? 0) + 1))
    return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([c]) => c)
  }, [snapCats.data])

  const notFound = (latest.error as any)?.status === 404
  const list = history.data ?? []
  const shown: TrendReport | undefined = picked != null ? list.find((r) => r.id === picked) ?? latest.data : latest.data
  const isLatest = !shown || shown.id === latest.data?.id

  useEffect(() => { if (picked != null && !list.some((r) => r.id === picked)) setPicked(null) }, [list, picked])

  const generate = () => start(api.generateRadarReport({ scope }), {
    key: `radar-report:${scope}`, label: `生成${scopeLabel(scope)}`,
    successMsg: '风向标已生成',
    onSuccess: () => setPicked(null),
  })

  const switchMode = (m: 'overall' | 'category') => {
    setMode(m)
    if (m === 'overall') setScope('overall')
  }

  return (
    <div className="space-y-5">
      {/* 范围 */}
      <div className="flex flex-wrap items-center gap-2.5">
        <Segmented value={mode} onChange={switchMode} options={[{ value: 'overall', label: '总榜' }, { value: 'category', label: '按题材' }]} />
        {mode === 'category' && (
          <>
            <Segmented value={catGender} onChange={(g) => { setCatGender(g); if (parsed && parsed.gender !== g) setScope('overall') }} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
            <div className="w-[200px]">
              <Select value={parsed && parsed.gender === catGender ? parsed.category : null} onChange={(v) => v && setScope(`category:${catGender}:${v}`)}
                placeholder={snapCats.isLoading ? '读取题材…' : cats.length ? '选择题材' : '先刷新榜单'} options={cats.map((c) => ({ value: c, label: c }))} />
            </div>
          </>
        )}
      </div>

      {mode === 'category' && !parsed ? (
        <EmptyState kind="radar" title="选一个题材" desc="按题材生成的风向标只看这个题材在阅读榜和新书榜上的书，更细、更好下手。" />
      ) : (
        <>
          <ReportHeader report={shown} isLatest={isLatest} running={!!job} onGenerate={generate} scope={scope} />
          {job && <JobInline job={job} />}

          {list.length > 1 && (
            <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
              {list.map((r, k) => {
                const active = (shown?.id ?? -1) === r.id
                return (
                  <button key={r.id} onClick={() => setPicked(k === 0 ? null : r.id)}
                    className={cn('flex h-10 shrink-0 flex-col justify-center rounded-lg px-3 text-left transition', active ? 'bg-foreground text-background' : 'bg-muted/70 text-foreground/80 hover:bg-muted')}>
                    <span className="num text-[12px] font-medium leading-tight">{k === 0 ? '最新 · ' : ''}{fmtDateTime(r.created_at)}</span>
                    <span className={cn('max-w-[180px] truncate text-[11px] leading-tight', active ? 'opacity-70' : 'text-muted-foreground')}>
                      {(r.report?.hot_words ?? []).slice(0, 3).map((h) => h.word).join(' · ') || '—'}
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {latest.isLoading ? (
            <div className="space-y-4"><Skeleton className="h-36 rounded-xl" /><div className="grid gap-4 md:grid-cols-2"><Skeleton className="h-64 rounded-xl" /><Skeleton className="h-64 rounded-xl" /></div></div>
          ) : notFound && !shown ? (
            <EmptyState kind="radar" title={`还没有${scopeLabel(scope)}`}
              desc="风向标读最新一份榜单快照，总结今日热词、读者情绪、开坑方向和避坑清单。没有榜单时先刷新榜单。"
              action={<Button variant="primary" loading={!!job} icon={<Sparkles className="h-4 w-4" />} onClick={generate}>生成风向标</Button>} />
          ) : latest.error && !shown ? (
            <ErrorState error={latest.error} onRetry={() => latest.refetch()} />
          ) : shown?.report ? (
            <ReportBody report={shown.report} scope={scope} />
          ) : null}
        </>
      )}
    </div>
  )
}

function ReportHeader({ report, isLatest, running, onGenerate, scope }: { report?: TrendReport; isLatest: boolean; running: boolean; onGenerate: () => void; scope: string }) {
  const inputs = report?.report?.inputs
  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-surface px-4 py-3.5 shadow-card sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Compass className="h-4 w-4 text-primary" />
          <span className="text-[15px] font-semibold">{scopeLabel(scope)}</span>
          {report && !isLatest && <Badge tone="neutral">历史版本</Badge>}
          {report?.stale && <Badge tone="warning" dot>榜单已更新，建议重新生成</Badge>}
          {report && !report.stale && isLatest && <Badge tone="success" dot>基于最新榜单</Badge>}
        </div>
        {report ? (
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-muted-foreground">
            <span>生成于 <span className="num text-foreground/80">{fmtDateTime(report.created_at)}</span></span>
            <span>模型 <span className={cn('font-mono text-[12px]', report.model === 'mock' ? 'text-warning' : 'text-foreground/80')}>{report.model || '—'}</span></span>
            {report.snapshot && <span>榜单 {SOURCE[report.snapshot.source] ?? report.snapshot.source} · <span className="num">{fmtDateTime(report.snapshot.taken_at)}</span></span>}
            {inputs?.books ? <span className="num">读了 {inputs.books} 本{inputs.top_n ? `（每榜前 ${inputs.top_n}）` : ''}</span> : null}
          </div>
        ) : (
          <div className="mt-1 text-[12.5px] text-muted-foreground">还没生成过</div>
        )}
      </div>
      <Button variant={report?.stale || !report ? 'primary' : 'secondary'} loading={running} icon={<RefreshCw className="h-4 w-4" />} onClick={onGenerate} className="sm:shrink-0">
        {running ? '生成中' : report ? '重新生成' : '生成风向标'}
      </Button>
    </div>
  )
}

function ReportBody({ report: r, scope }: { report: TrendReportBody; scope: string }) {
  const nav = useNavigate()
  const parsed = parseScope(scope)
  const [create, setCreate] = useState<{ gender: Gender; premise: string; genre?: string } | null>(null)
  const copy = async (t: string) => { (await copyText(t)) ? toast.success('已复制') : toast.info('复制失败，请长按选中后手动复制') }
  const fade = (i: number) => ({ initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: { delay: Math.min(i, 8) * 0.04, duration: 0.3 } })

  return (
    <div className="space-y-5">
      {/* 今日热词 */}
      {!!r.hot_words?.length && (
        <Card>
          <CardHeader divider title="今日热词" icon={<Flame className="h-4 w-4" />} />
          <div className="grid gap-3 p-4 sm:grid-cols-2 xl:grid-cols-3">
            {r.hot_words.map((h, i) => (
              <motion.div key={h.word + i} {...fade(i)} className="flex flex-col rounded-xl bg-subtle/60 p-4 hairline">
                <div className="flex items-baseline gap-2">
                  <span className="num text-[12px] font-semibold text-danger">#{i + 1}</span>
                  <span className="text-[17px] font-semibold tracking-tight">{h.word}</span>
                </div>
                {h.why && <p className="mt-1.5 text-[13px] leading-relaxed text-foreground/80">{h.why}</p>}
                {!!h.examples?.length && (
                  <div className="mt-auto flex flex-wrap gap-1.5 pt-3">
                    {h.examples.map((e) => <span key={e} className="rounded-md bg-surface px-2 py-0.5 text-[12px] text-muted-foreground hairline">《{e.replace(/^《|》$/g, '')}》</span>)}
                  </div>
                )}
              </motion.div>
            ))}
          </div>
        </Card>
      )}

      {/* 各榜卡片 */}
      {!!r.boards?.length && (
        <div className="grid gap-5 lg:grid-cols-2">
          {r.boards.map((b, i) => (
            <BoardCard key={b.board + i} b={b} delay={i}
              onCopy={(t) => copy(t)}
              onCreate={(h) => setCreate({ gender: parsed?.gender ?? boardGender(b.board), genre: parsed?.category, premise: h.pitch ? `${h.title}：${h.pitch}` : h.title })}
              onIdeas={parsed ? () => nav(`/ideas?genre=${encodeURIComponent(parsed.category)}&gender=${parsed.gender}&from_trends=1`) : undefined} />
          ))}
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {!!r.open_directions?.length && (
          <Card>
            <CardHeader divider title="开坑方向" icon={<Compass className="h-4 w-4" />} />
            <ol className="space-y-2 p-4">
              {r.open_directions.map((d, i) => (
                <li key={i} className="flex gap-3 rounded-lg px-1 text-[13.5px] leading-relaxed">
                  <span className="num mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary-soft text-[11px] font-semibold text-primary">{i + 1}</span>
                  <span className="min-w-0 flex-1">{d}</span>
                </li>
              ))}
            </ol>
          </Card>
        )}
        {!!r.pitfalls?.length && (
          <Card>
            <CardHeader divider title="避坑清单" icon={<AlertTriangle className="h-4 w-4" />} />
            <ul className="space-y-2 p-4">
              {r.pitfalls.map((d, i) => (
                <li key={i} className="flex gap-2.5 rounded-lg bg-danger-soft/40 px-3 py-2 text-[13px] leading-relaxed">
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /><span className="min-w-0 flex-1">{d}</span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      {!!r.title_patterns?.length && (
        <Card>
          <CardHeader divider title="书名句式" icon={<Type className="h-4 w-4" />} />
          <div className="grid gap-3 p-4 md:grid-cols-2">
            {r.title_patterns.map((t, i) => (
              <div key={i} className="rounded-xl p-3.5 hairline">
                <div className="flex items-start justify-between gap-2">
                  <PatternText text={t.pattern} />
                  <Button size="icon-sm" variant="ghost" aria-label="复制句式" onClick={() => copy(t.pattern)}><Copy className="h-3.5 w-3.5" /></Button>
                </div>
                {!!t.examples?.length && (
                  <ul className="mt-2 space-y-1">
                    {t.examples.map((e) => <li key={e} className="truncate text-[12.5px] text-muted-foreground">例：《{e.replace(/^《|》$/g, '')}》</li>)}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {!!r.warnings?.length && (
        <details className="group rounded-xl border bg-subtle/40 px-4 py-3 text-[12.5px]">
          <summary className="flex min-h-[32px] cursor-pointer list-none items-center gap-2 font-medium text-muted-foreground">
            <Info className="h-4 w-4" />程序校验记录 <span className="num">{r.warnings.length}</span>
            <span className="ml-auto text-[11.5px] group-open:hidden">展开</span>
          </summary>
          <ul className="mt-2 space-y-1 pl-6 leading-relaxed text-foreground/70">
            {r.warnings.map((w, i) => <li key={i} className="list-disc">{w}</li>)}
          </ul>
        </details>
      )}

      <QuickCreateDialog open={!!create} onOpenChange={(o) => !o && setCreate(null)} defaults={create ?? undefined} />
    </div>
  )
}

function PatternText({ text }: { text: string }) {
  const parts = text.split(/(\[[^\]]*\])/g).filter(Boolean)
  return (
    <div className="min-w-0 text-[14.5px] font-semibold leading-relaxed">
      {parts.map((p, i) => p.startsWith('[')
        ? <span key={i} className="mx-0.5 rounded bg-primary-soft px-1 py-px text-[13px] font-medium text-primary">{p.slice(1, -1)}</span>
        : <span key={i}>{p}</span>)}
    </div>
  )
}

function BoardCard({ b, delay, onCopy, onCreate, onIdeas }: {
  b: TrendBoard; delay: number; onCopy: (t: string) => void; onCreate: (h: { title: string; pitch: string }) => void; onIdeas?: () => void
}) {
  const rows: [string, string][] = ([['总览', b.overview], ['读者情绪', b.reader_mood], ['机会判断', b.opportunity], ['写作建议', b.writing_tips]] as [string, string][]).filter(([, v]) => !!v)
  const isNew = b.board.includes('新书')
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: delay * 0.05, duration: 0.3 }}>
      <Card className="h-full overflow-hidden">
        <div className="flex items-center justify-between gap-2 border-b px-5 py-3.5">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold">{b.board}</span>
            <Badge tone={isNew ? 'primary' : 'neutral'}>{isNew ? '新书榜' : '阅读榜'}</Badge>
          </div>
        </div>
        <div className="space-y-3 p-5">
          {rows.map(([k, v]) => (
            <div key={k}>
              <div className="text-[12px] font-medium text-muted-foreground">{k}</div>
              <p className="mt-0.5 text-[13.5px] leading-relaxed">{v}</p>
            </div>
          ))}
          {!!b.idea_hooks?.length && (
            <div className="pt-1">
              <div className="mb-2 flex items-center gap-1.5 text-[12px] font-medium text-muted-foreground"><Lightbulb className="h-3.5 w-3.5" />灵感切口</div>
              <div className="space-y-2">
                {b.idea_hooks.map((h, i) => (
                  <div key={i} className="rounded-lg bg-warning-soft/40 p-3 hairline">
                    <div className="text-[13.5px] font-semibold">{h.title}</div>
                    {h.pitch && <p className="mt-0.5 text-[12.5px] leading-relaxed text-foreground/75">{h.pitch}</p>}
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Button size="xs" variant="soft" icon={<BookPlus className="h-3.5 w-3.5" />} onClick={() => onCreate(h)}>用这个梗开书</Button>
                      {onIdeas && <Button size="xs" variant="ghost" icon={<Lightbulb className="h-3.5 w-3.5" />} onClick={onIdeas}>这个题材出选题</Button>}
                      <Button size="xs" variant="ghost" icon={<Copy className="h-3.5 w-3.5" />} onClick={() => onCopy(h.pitch ? `${h.title}：${h.pitch}` : h.title)}>复制</Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>
    </motion.div>
  )
}
