import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check, ChevronDown, Coins, ListChecks, Sparkles } from '@/components/icons'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { CostButton } from '@/components/cost/CostButton'
import { Button } from '@/components/ui/button'
import { api, qk } from '@/lib/api'
import { fmtTokens } from '@/lib/cost'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { CompletenessItem, EstimateKind } from '@/lib/types'
import { cn, fmtTime, jobLabel } from '@/lib/utils'

/** 大号环形进度（0–100） */
export function Ring({ value, size = 104, stroke = 9, children }: { value: number; size?: number; stroke?: number; children?: React.ReactNode }) {
  const v = Math.max(0, Math.min(100, Math.round(value)))
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const color = v >= 80 ? 'hsl(var(--success))' : v >= 50 ? 'hsl(var(--primary))' : 'hsl(var(--warning))'
  return (
    <div className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} stroke="hsl(var(--muted))" strokeWidth={stroke} fill="none" />
        <circle cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ transition: 'stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)' }} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">{children}</div>
    </div>
  )
}

/** 完整度 job 目标 → 成本估算 kind */
function jobKind(target: string): EstimateKind | null {
  if (/\/bible\/generate$/.test(target)) return 'bible'
  if (/\/outline\/generate$/.test(target)) return 'outline'
  if (/\/chapters\/write-next$/.test(target)) return 'chapter_write'
  if (/\/characters\/\d+\/soul$/.test(target)) return 'soul'
  if (/\/package\/generate$/.test(target)) return 'package'
  return null
}
const JOB_CTA: Record<string, string> = { bible: '一键生成设定', outline: '一键生成大纲', chapter_write: '写第 1 章', soul: 'AI 补全五维', package: '生成包装' }

/** 书概览顶部：作品完整度环 + 待办清单（未完成的一键跳转或发起任务） */
export function CompletenessCard({ bookId }: { bookId: number }) {
  const q = useQuery({ queryKey: qk.completeness(bookId), queryFn: () => api.completeness(bookId) })
  const [showDone, setShowDone] = useState(false)
  if (q.isLoading) return <Skeleton className="mt-6 h-[188px] rounded-xl" />
  if (q.error || !q.data) return null
  const { items } = q.data
  const todo = items.filter((i) => !i.done)
  const done = items.filter((i) => i.done)
  const pct = items.length ? Math.round((done.length / items.length) * 100) : 0
  return (
    <Card className="mt-6 overflow-hidden">
      <div className="flex flex-col gap-5 p-5 md:flex-row md:items-start md:gap-7 md:p-6">
        <div className="flex items-center gap-4 md:w-[200px] md:shrink-0 md:flex-col md:items-start">
          <Ring value={pct}>
            <span className="num text-[22px] font-semibold tracking-tight">{done.length}/{items.length}</span>
            <span className="mt-1 text-[11px] text-muted-foreground">已完成</span>
          </Ring>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[15px] font-semibold"><ListChecks className="h-4 w-4 text-primary" />作品筹备清单</div>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">
              {todo.length ? <>还差 <b className="font-semibold text-foreground">{todo.length}</b> 项。资料越全，写作越不跑偏。</> : '全部筹备齐了，放心写吧。'}
            </p>
          </div>
        </div>
        <div className="min-w-0 flex-1">
          {todo.length > 0 && (
            <ul className="divide-y divide-border/60 overflow-hidden rounded-xl hairline">
              {todo.map((it) => <TodoRow key={it.key} bookId={bookId} item={it} />)}
            </ul>
          )}
          {done.length > 0 && (
            <div className={cn(todo.length > 0 && 'mt-3')}>
              <button onClick={() => setShowDone((x) => !x)} aria-expanded={showDone}
                className="flex min-h-[40px] items-center gap-1.5 rounded-lg px-1 text-[12.5px] text-muted-foreground hover:text-foreground">
                <Check className="h-3.5 w-3.5 text-success" strokeWidth={2.5} />已完成 {done.length} 项
                <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showDone && 'rotate-180')} />
              </button>
              {(showDone || !todo.length) && (
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {done.map((it) => (
                    <span key={it.key} className="inline-flex h-8 items-center gap-1 rounded-full bg-success-soft/70 px-3 text-[12.5px] text-success">
                      <Check className="h-3.5 w-3.5" strokeWidth={2.5} />{it.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

function TodoRow({ bookId, item: it }: { bookId: number; item: CompletenessItem }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { start } = useJobs()
  const a = it.action
  const key = `complete:${bookId}:${it.key}`
  const job = useActiveJob(key)
  const partial = it.weight > 0 && !it.done
  let cta: React.ReactNode = null
  if (a?.type === 'route') {
    cta = <Link to={a.target}><Button size="sm" className="h-10" icon={<ArrowRight className="h-4 w-4" />}>去完善</Button></Link>
  } else if (a?.type === 'job') {
    const kind = jobKind(a.target)
    const soul = /\/characters\/(\d+)\/soul$/.exec(a.target)
    if (soul) {
      // 灵魂五维的任务只出建议、不写库：带去设定库打开这张卡，自动补全后对比采纳
      cta = <Button size="sm" variant="soft" className="h-10" icon={<Sparkles className="h-4 w-4" />} onClick={() => nav(`/books/${bookId}/bible?entry=${soul[1]}&soul=1`)}>AI 补全五维</Button>
    } else {
      const run = () => start(api.postJobPath(a.target), {
        key, label: kind ? JOB_CTA[kind] : it.label,
        onSuccess: (j) => {
          qc.invalidateQueries({ queryKey: qk.completeness(bookId) })
          if (kind === 'chapter_write' && j.result?.chapter_id) nav(`/books/${bookId}/chapters/${j.result.chapter_id}`)
        },
      })
      const label = kind ? JOB_CTA[kind] : '一键完成'
      cta = kind
        ? <CostButton target={{ kind, bookId }} label={label} onRun={run} size="sm" variant="primary" className="h-10" loading={!!job} icon={<Sparkles className="h-4 w-4" />}>{job ? `${Math.round(job.progress)}%` : label}</CostButton>
        : <Button size="sm" variant="primary" className="h-10" loading={!!job} onClick={run}>{label}</Button>
    }
  }
  return (
    <li className="flex min-h-[60px] flex-wrap items-center gap-x-3 gap-y-2 bg-surface px-3.5 py-2.5 sm:flex-nowrap">
      <span className={cn('flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2', partial ? 'border-primary/60 bg-[conic-gradient(hsl(var(--primary))_0_50%,transparent_50%_100%)]' : 'border-border')} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-[13.5px] font-medium">{it.label}{partial && <span className="rounded bg-primary-soft px-1.5 text-[11px] font-normal leading-[18px] text-primary">进行中</span>}</div>
        {it.hint && <div className="mt-0.5 break-words text-[12px] leading-relaxed text-muted-foreground">{it.hint}</div>}
      </div>
      <div className="ml-9 shrink-0 sm:ml-0">{cta}</div>
    </li>
  )
}

/** 本书累计用量（来自 llm_usage） */
export function UsageCard({ bookId }: { bookId: number }) {
  const q = useQuery({ queryKey: qk.usage(bookId), queryFn: () => api.usage(bookId), retry: false })
  if (q.isLoading) return <Skeleton className="mt-6 h-[140px] rounded-xl" />
  if (q.error || !q.data) return null
  const u = q.data
  const total = u.in_tokens + u.out_tokens
  const kinds = [...(u.by_kind ?? [])].sort((a, b) => b.in_tokens + b.out_tokens - (a.in_tokens + a.out_tokens)).slice(0, 5)
  const max = Math.max(1, ...kinds.map((k) => k.in_tokens + k.out_tokens))
  const mins = Math.round(u.ms / 60000)
  return (
    <Card className="mt-6">
      <div className="flex min-h-[56px] items-center gap-2.5 border-b px-5 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-muted text-foreground/70"><Coins className="h-[15px] w-[15px]" /></div>
        <h3 className="text-[14.5px] font-semibold tracking-tight">本书累计用量</h3>
        {u.last_at && <span className="ml-auto text-[12px] text-muted-foreground">最近 {fmtTime(u.last_at)}</span>}
      </div>
      {!u.calls ? <p className="px-5 py-8 text-center text-[13px] text-muted-foreground">这本书还没有调用过模型</p> : (
        <div className="grid gap-5 p-5 md:grid-cols-[minmax(0,240px)_1fr]">
          <div className="grid grid-cols-3 gap-3 md:grid-cols-1">
            <div><div className="text-[12px] text-muted-foreground">token</div><div className="num mt-0.5 text-[22px] font-semibold leading-tight">{fmtTokens(total)}</div><div className="num text-[11.5px] text-muted-foreground">入 {fmtTokens(u.in_tokens)} · 出 {fmtTokens(u.out_tokens)}</div></div>
            <div><div className="text-[12px] text-muted-foreground">调用</div><div className="num mt-0.5 text-[22px] font-semibold leading-tight">{u.calls.toLocaleString('zh-CN')}<span className="ml-0.5 text-[12px] font-normal text-muted-foreground">次</span></div></div>
            <div><div className="text-[12px] text-muted-foreground">模型耗时</div><div className="num mt-0.5 text-[22px] font-semibold leading-tight">{mins >= 1 ? mins : '<1'}<span className="ml-0.5 text-[12px] font-normal text-muted-foreground">分钟</span></div></div>
          </div>
          <div className="space-y-2.5">
            {kinds.map((k) => {
              const t = k.in_tokens + k.out_tokens
              return (
                <div key={k.kind}>
                  <div className="flex items-baseline justify-between gap-2 text-[12.5px]"><span className="truncate">{jobLabel(k.kind)}</span><span className="num shrink-0 text-muted-foreground">{fmtTokens(t)} · {k.calls} 次</span></div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${Math.max(3, (t / max) * 100)}%` }} /></div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </Card>
  )
}
