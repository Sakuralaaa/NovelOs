import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowRight, Check, Coins, FileText, Flag, Pause, Play, Sparkles, Zap } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Progress, Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { ErrorState, PageHeader } from '@/components/common/States'
import { Tile, wan } from '@/components/wanben/bits'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'
import { useJobs } from '@/lib/jobs'
import { aqk, autoApi, qk } from '@/lib/api'
import type { AutoDecision, AutoLevel, AutoOverview, AutoRun, AutoSettings, AutoStopKind } from '@/lib/types'
import { cn, fmtNum } from '@/lib/utils'

const PRESETS = [300_000, 500_000, 1_200_000, 2_000_000]
const STAGES: { key: AutoRun['stage']; label: string }[] = [
  { key: 'setup', label: '准备设定' }, { key: 'plan', label: '规划卷纲' }, { key: 'write', label: '连写' }, { key: 'done', label: '完本' },
]
const STATUS: Record<AutoRun['status'], { label: string; tone: 'primary' | 'warning' | 'danger' | 'success' | 'neutral' }> = {
  running: { label: '正在写', tone: 'primary' }, waiting: { label: '等你拍板', tone: 'warning' }, paused: { label: '已暂停', tone: 'neutral' },
  stopped: { label: '已停下', tone: 'danger' }, done: { label: '已完本', tone: 'success' },
}
const STOPS: { value: AutoStopKind; label: string }[] = [{ value: 'opening', label: '开篇写完确认' }, { value: 'volume', label: '每卷写完选下一卷走向' }]
const EVENT_TONE: Record<string, string> = { error: 'text-danger', llm_down: 'text-danger', budget: 'text-danger', forced: 'text-warning', needs_review: 'text-warning', retry: 'text-warning', done: 'text-success' }
const statusOf = (r: AutoRun) => (r.status === 'waiting' && r.stop_reason === 'needs_review' ? { label: '待你看', tone: 'warning' as const } : STATUS[r.status])

export default function AutoPage() {
  const id = useBookId()
  const qc = useQueryClient()
  const { start } = useJobs()
  const q = useQuery({
    queryKey: aqk.overview(id), queryFn: () => autoApi.get(id),
    refetchInterval: (query) => ((query.state.data as AutoOverview | undefined)?.running ? 3000 : false),
  })
  const refresh = () => { qc.invalidateQueries({ queryKey: aqk.overview(id) }); qc.invalidateQueries({ queryKey: ['wanben', id] }); qc.invalidateQueries({ queryKey: qk.book(id) }) }
  const run = async (p: Promise<any>, label: string) => {
    await start(p, { key: `autopilot:${id}`, label: '一键成书', onSuccess: refresh, onError: refresh })
    refresh()
    toast.success(label)
  }
  const pause = useMutation({ mutationFn: () => autoApi.pause(id), meta: { errorTitle: '暂停失败' }, onSuccess: () => { refresh(); toast.success('写完手上这一章就停') } })

  if (q.isLoading) return <div className="page"><Skeleton className="h-8 w-48" /><Skeleton className="mt-6 h-48 rounded-xl" /></div>
  if (q.error || !q.data) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>
  const o = q.data
  const r = o.run
  const pending = o.decisions.find((d) => d.status === 'pending') ?? null
  const fresh = !r || r.status === 'done'
  const canResume = !!r && !o.running && (r.status === 'paused' || r.status === 'stopped' || (r.status === 'waiting' && r.stop_reason === 'needs_review'))

  return (
    <div className="page">
      <BookCrumb bookId={id} page="一键成书" />
      <PageHeader className="mt-3" title="一键成书" desc={o.fanfic ? '同人书：导入原著设定 → 规划 → 连写到完本' : '设定 → 规划 → 连写到完本'}
        actions={o.running ? <Button icon={<Pause className="h-4 w-4" />} loading={pause.isPending} onClick={() => pause.mutate()}>暂停</Button>
          : canResume ? <Button variant="primary" icon={<Play className="h-4 w-4" />} onClick={() => void run(autoApi.start(id), '继续一键成书')}>继续</Button> : undefined} />

      {r && <StatusCard o={o} r={r} />}
      {pending && <DecisionCard bookId={id} d={pending} onDone={refresh} />}

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-6">
          {(fresh || canResume) && <StartCard o={o} resume={canResume} onStart={(b) => void run(autoApi.start(id, b), canResume ? '继续一键成书' : '一键成书开始了')} />}
          {r && <FlagsCard bookId={id} r={r} onDone={refresh} />}
          {o.recaps.length > 0 && <RecapsCard o={o} />}
        </div>
        <div className="min-w-0 space-y-6">
          {r && <EventsCard r={r} />}
          {r && r.guidance.length > 0 && (
            <Card>
              <CardHeader icon={<Flag />} title="作者导向" desc="写章时一直带着" />
              <CardBody className="space-y-2 p-4">
                {r.guidance.map((g, i) => (
                  <div key={i} className="rounded-lg bg-subtle px-3 py-2 text-[13px]">
                    <div className="break-words">{g.text}</div>
                    <div className="num mt-0.5 text-[11.5px] text-muted-foreground">{g.source} · 第{g.from_chapter}章起{g.to_chapter ? `到第${g.to_chapter}章` : ''}</div>
                  </div>
                ))}
              </CardBody>
            </Card>
          )}
          {o.decisions.some((d) => d.status !== 'pending') && <HistoryCard ds={o.decisions.filter((d) => d.status !== 'pending')} />}
        </div>
      </div>
    </div>
  )
}

function StatusCard({ o, r }: { o: AutoOverview; r: AutoRun }) {
  const p = o.progress
  const st = statusOf(r)
  const idx = Math.max(0, STAGES.findIndex((s) => s.key === (r.stage === 'bible' ? 'setup' : r.stage)))
  const pct = p ? Math.round((p.ratio || 0) * 1000) / 10 : 0
  const s = r.stats
  return (
    <Card className={cn('overflow-hidden', r.status === 'running' && o.running && 'ring-1 ring-primary/25')}>
      <div className="flex flex-wrap items-center gap-3 border-b px-4 py-3 sm:px-5">
        <Badge tone={st.tone} dot>{o.running && r.status !== 'running' ? '正在写' : st.label}</Badge>
        <div className="order-last flex min-w-0 basis-full flex-wrap items-center gap-1.5 text-[12.5px] sm:order-none sm:basis-0 sm:flex-1">
          {STAGES.map((x, i) => (
            <span key={x.key} className="flex items-center gap-1.5">
              <span className={cn('rounded-full px-2 py-0.5', i < idx || r.stage === 'done' ? 'bg-success-soft text-success' : i === idx ? 'bg-primary-soft text-primary' : 'bg-muted text-muted-foreground')}>{x.label}</span>
              {i < STAGES.length - 1 && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
            </span>
          ))}
        </div>
        <span className="ml-auto text-[12.5px] text-muted-foreground sm:ml-0">{r.settings.level === 'guided' ? '关键时刻问我' : '全自动'}</span>
      </div>
      {r.message && r.status !== 'running' && (
        <div className={cn('flex items-start gap-2 border-b px-4 py-2.5 text-[13px] sm:px-5', r.status === 'stopped' ? 'bg-danger-soft/50 text-danger' : 'bg-subtle')}>
          {r.status === 'stopped' && <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />}<span className="min-w-0 break-words">{r.message}</span>
        </div>
      )}
      <div className="grid gap-5 p-4 sm:p-5 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="num font-serif text-[32px] font-semibold leading-none tracking-tight">{fmtNum(p?.words ?? 0)}</span>
            <span className="num text-[14px] text-muted-foreground">/ {fmtNum(p?.target_words ?? r.settings.target_words)} 字</span>
            <span className="num ml-auto text-[15px] font-semibold text-primary">{pct}%</span>
          </div>
          <Progress value={pct} className="mt-3 h-2.5" tone={r.status === 'done' ? 'success' : 'primary'} />
          <div className="num mt-3 flex flex-wrap justify-between gap-2 text-[12.5px] text-muted-foreground">
            <span>已写 {p?.chapters_written ?? 0} / {p?.chapters_total ?? '—'} 章</span>
            <span>{p?.current_volume ? `第${p.current_volume.order}卷 ${p.current_volume.title || ''}` : '还没规划卷纲'}</span>
          </div>
        </div>
        <div className="grid min-w-0 grid-cols-2 gap-2.5">
          <Tile label="自动修好" value={`${(s.healed ?? 0)} 章`} sub="重写后过审" />
          <Tile label="待你看" value={`${r.flags.filter((f) => f.blocking).length} 章`} sub={`清单共 ${r.flags.length} 章`} tone={r.flags.length ? 'warning' : undefined} />
          <Tile label="卷末复盘" value={`${s.volumes_reviewed ?? 0} 卷`} sub={`渠道重试 ${s.retries ?? 0} 次`} />
          <Tile label="本次花费" value={`¥${o.cost.toFixed(2)}`} sub={r.settings.max_cost_cny ? `上限 ¥${r.settings.max_cost_cny}` : '不设上限'} />
        </div>
      </div>
    </Card>
  )
}

function StartCard({ o, resume, onStart }: { o: AutoOverview; resume: boolean; onStart: (b: Partial<AutoSettings>) => void }) {
  const [d, setD] = useState<AutoSettings>(o.settings)
  useEffect(() => { setD(o.settings) }, [o.settings])
  const [custom, setCustom] = useState(() => !PRESETS.includes(o.settings.target_words))
  const set = (p: Partial<AutoSettings>) => setD((x) => ({ ...x, ...p }))
  const chapters = Math.ceil(d.target_words / Math.max(1000, d.chapter_words))
  const toggleStop = (k: AutoStopKind) => set({ stop_on: d.stop_on.includes(k) ? d.stop_on.filter((x) => x !== k) : [...d.stop_on, k] })
  return (
    <Card>
      <CardHeader icon={<Zap />} title={resume ? '继续写' : '开始一键成书'} desc={`约 ${chapters} 章`} />
      <CardBody className="space-y-5 p-4 sm:p-5">
        <Field label="怎么写">
          <Segmented<AutoLevel> block value={d.level} onChange={(v) => set({ level: v })}
            options={[{ value: 'full', label: '全自动' }, { value: 'guided', label: '关键时刻问我' }]} />
        </Field>
        {d.level === 'guided' && (
          <Field label="在这些地方停下">
            <div className="flex flex-wrap gap-1.5">
              {STOPS.map((x) => {
                const on = d.stop_on.includes(x.value)
                return (
                  <button key={x.value} type="button" aria-pressed={on} onClick={() => toggleStop(x.value)}
                    className={cn('inline-flex h-9 items-center gap-1 rounded-full border px-3 text-[13px] transition', on ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>
                    {on && <Check className="h-3.5 w-3.5" />}{x.label}
                  </button>
                )
              })}
            </div>
          </Field>
        )}
        <Field label="全书字数">
          <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-5">
            {PRESETS.map((p) => (
              <button key={p} type="button" onClick={() => { setCustom(false); set({ target_words: p }) }}
                className={cn('focus-ring num h-10 rounded-lg border text-[13.5px] font-medium transition', !custom && d.target_words === p ? 'border-primary bg-primary-soft text-primary' : 'bg-surface hover:border-foreground/25')}>
                {wan(p)}
              </button>
            ))}
            <button type="button" onClick={() => setCustom(true)}
              className={cn('focus-ring h-10 rounded-lg border text-[13.5px] font-medium transition', custom ? 'border-primary bg-primary-soft text-primary' : 'bg-surface hover:border-foreground/25')}>自定义</button>
          </div>
          {custom && <Input className="mt-2" type="number" min={10000} step={10000} value={d.target_words} onChange={(e) => set({ target_words: Number(e.target.value) || 0 })} />}
        </Field>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="每章字数"><Input type="number" min={1000} max={6000} step={100} value={d.chapter_words} onChange={(e) => set({ chapter_words: Number(e.target.value) || 0 })} /></Field>
          <Field label="开篇打磨章数"><Input type="number" min={0} max={30} value={d.golden_chapters} onChange={(e) => set({ golden_chapters: Number(e.target.value) || 0 })} /></Field>
          <Field label="花费上限（元，0 不限）"><Input type="number" min={0} step={10} value={d.max_cost_cny} onChange={(e) => set({ max_cost_cny: Number(e.target.value) || 0 })} /></Field>
        </div>
        <Button variant="primary" className="h-11 w-full" icon={resume ? <Play className="h-4 w-4" /> : <Zap className="h-4 w-4" />}
          disabled={d.target_words < 10000 || d.chapter_words < 1000} onClick={() => onStart(d)}>
          {resume ? '继续写' : '开始一键成书'}
        </Button>
      </CardBody>
    </Card>
  )
}

function DecisionCard({ bookId, d, onDone }: { bookId: number; d: AutoDecision; onDone: () => void }) {
  const { start } = useJobs()
  const [choice, setChoice] = useState<number | null>(d.kind === 'opening' ? 0 : d.recommended)
  const [custom, setCustom] = useState('')
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true)
    try {
      await start(autoApi.answer(bookId, d.id, { choice, custom }), { key: `autopilot:${bookId}`, label: '一键成书', onSuccess: onDone })
      toast.success('已拍板，接着写')
      onDone()
    } finally { setBusy(false) }
  }
  return (
    <Card className="mt-6 ring-1 ring-warning/40">
      <CardHeader icon={<Flag />} title={d.title} />
      <CardBody className="space-y-4 p-4 sm:p-5">
        {d.context && <p className="whitespace-pre-wrap break-words rounded-lg bg-subtle px-3 py-2.5 text-[13px] leading-relaxed">{d.context}</p>}
        {d.kind === 'opening' ? (
          <Link to={`/books/${bookId}/chapters`} className="inline-flex h-10 items-center gap-1 text-[13.5px] text-primary hover:underline"><FileText className="h-4 w-4" />去读开篇</Link>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {d.options.map((op, i) => {
              const on = choice === i
              return (
                <button key={i} type="button" aria-pressed={on} onClick={() => setChoice(on ? null : i)}
                  className={cn('focus-ring flex min-w-0 flex-col gap-2 rounded-xl border p-3.5 text-left transition', on ? 'border-primary bg-primary-soft/40 ring-1 ring-primary/40' : 'bg-surface hover:border-foreground/25')}>
                  <div className="flex items-start gap-2">
                    <span className="min-w-0 flex-1 break-words text-[14px] font-semibold">{op.title || `走向 ${i + 1}`}</span>
                    {i === d.recommended && <Badge tone="primary">推荐</Badge>}
                  </div>
                  <p className="break-words text-[13px] leading-relaxed">{op.summary}</p>
                  {op.crisis && <p className="break-words text-[12.5px] text-muted-foreground">危机：{op.crisis}</p>}
                  {op.turns.length > 0 && (
                    <div className="flex flex-wrap gap-1">{op.turns.map((t, k) => <span key={k} className="max-w-full break-words rounded-md bg-muted px-1.5 py-0.5 text-[12px]">{t}</span>)}</div>
                  )}
                  {op.why && <p className="break-words text-[12.5px] text-primary">{op.why}</p>}
                </button>
              )
            })}
          </div>
        )}
        <Textarea rows={2} value={custom} onChange={(e) => setCustom(e.target.value.slice(0, 1000))}
          placeholder={d.kind === 'opening' ? '想调整就写下来，后面每章都照着写，比如：女主第 15 章前登场' : '你的要求（可不填），比如：这一卷让师姐出场，别写宗门大比'} />
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="primary" className="h-11" loading={busy} disabled={choice === null && !custom.trim()} icon={<Check className="h-4 w-4" />} onClick={() => void go()}>
            {d.kind === 'opening' ? '接着写' : '按这个走'}
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

function FlagsCard({ bookId, r, onDone }: { bookId: number; r: AutoRun; onDone: () => void }) {
  const { start } = useJobs()
  const done = useMutation({ mutationFn: (cid: number) => autoApi.resolveFlag(bookId, cid), meta: { errorTitle: '操作失败' }, onSuccess: onDone })
  const [accepting, setAccepting] = useState<number | null>(null)
  const accept = async (cid: number) => {
    setAccepting(cid)
    const finish = () => { setAccepting(null); onDone() }
    const job = await start(autoApi.acceptFlag(bookId, cid), { key: `autopilot-accept:${cid}`, label: '放行这一章', successMsg: '已放行，点继续接着写', onSuccess: finish, onError: finish })
    if (!job) setAccepting(null)
  }
  const blocking = r.flags.filter((f) => f.blocking).length
  return (
    <Card>
      <CardHeader icon={<AlertTriangle />} title="待你看" desc={blocking ? `${blocking} 章自动修了 2 轮还没过审，等你看完再接着写` : r.flags.length ? `${r.flags.length} 章` : '没有需要你看的章'} />
      {r.flags.length > 0 && (
        <CardBody className="divide-y divide-border/70 p-0">
          {r.flags.map((f) => (
            <div key={f.chapter_id} className="flex min-h-[56px] flex-wrap items-center gap-3 px-4 py-2.5 sm:px-5">
              <div className="min-w-0 flex-1">
                <Link to={`/books/${bookId}/chapters/${f.chapter_id}`} className="block truncate text-[13.5px] font-medium hover:text-primary">第{f.number}章 {f.title}</Link>
                <p className="truncate text-[12.5px] text-muted-foreground" title={f.reason}>{f.reason}</p>
              </div>
              {f.blocking ? (
                <div className="flex shrink-0 gap-1.5">
                  <Link to={`/books/${bookId}/chapters/${f.chapter_id}`}><Button size="sm" variant="ghost" icon={<FileText className="h-3.5 w-3.5" />}>去改</Button></Link>
                  <Button size="sm" variant="secondary" loading={accepting === f.chapter_id} icon={<Check className="h-3.5 w-3.5" />} onClick={() => void accept(f.chapter_id)}>放行</Button>
                </div>
              ) : (
                <Button size="sm" variant="ghost" loading={done.isPending && done.variables === f.chapter_id} onClick={() => done.mutate(f.chapter_id)}>看过了</Button>
              )}
            </div>
          ))}
        </CardBody>
      )}
    </Card>
  )
}

function RecapsCard({ o }: { o: AutoOverview }) {
  return (
    <Card>
      <CardHeader icon={<Sparkles />} title="前情卷回顾" desc="写后面的章时当长期记忆" />
      <CardBody className="space-y-2 p-4">
        {[...o.recaps].reverse().map((x) => (
          <details key={x.order} className="rounded-xl border bg-surface px-3 py-1.5" open={x.order === o.recaps[o.recaps.length - 1]?.order}>
            <summary className="flex min-h-[40px] cursor-pointer items-center text-[13.5px] font-medium">第{x.order}卷 {x.title}</summary>
            <div className="space-y-2 pb-2 text-[13px] leading-relaxed">
              <p className="whitespace-pre-wrap break-words">{x.text}</p>
              {!!x.state?.length && <ul className="space-y-0.5 text-[12.5px] text-muted-foreground">{x.state.map((t, i) => <li key={i} className="break-words">· {t}</li>)}</ul>}
              {!!x.problems?.length && <ul className="space-y-0.5 text-[12.5px] text-warning">{x.problems.map((t, i) => <li key={i} className="break-words">· {t}</li>)}</ul>}
            </div>
          </details>
        ))}
      </CardBody>
    </Card>
  )
}

function EventsCard({ r }: { r: AutoRun }) {
  return (
    <Card>
      <CardHeader icon={<Coins />} title="运行记录" />
      <CardBody className="max-h-[420px] space-y-1.5 overflow-y-auto p-4">
        {r.events.length === 0 ? <p className="text-[13px] text-muted-foreground">还没有记录</p> : r.events.map((e, i) => (
          <div key={i} className="flex gap-2 text-[12.5px] leading-relaxed">
            <span className="num shrink-0 text-muted-foreground">{fmtTime(e.at)}</span>
            <span className={cn('min-w-0 break-words', EVENT_TONE[e.kind])}>{e.text}</span>
          </div>
        ))}
      </CardBody>
    </Card>
  )
}

function HistoryCard({ ds }: { ds: AutoDecision[] }) {
  return (
    <Card>
      <CardHeader icon={<Check />} title="拍板记录" />
      <CardBody className="space-y-2 p-4">
        {ds.map((d) => (
          <div key={d.id} className="text-[12.5px] leading-relaxed">
            <div className="flex items-center gap-1.5"><span className="min-w-0 flex-1 truncate font-medium">{d.title}</span><Badge tone={d.status === 'auto' ? 'neutral' : 'primary'}>{d.status === 'auto' ? '按推荐' : '你选的'}</Badge></div>
            <div className="break-words text-muted-foreground">{d.choice !== null && d.options[d.choice] ? d.options[d.choice].title : ''}{d.custom ? `｜${d.custom}` : ''}</div>
          </div>
        ))}
      </CardBody>
    </Card>
  )
}

function fmtTime(iso: string) {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return ''
  return `${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')} ${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`
}
