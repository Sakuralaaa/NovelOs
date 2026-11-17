import { useState, type ReactNode } from 'react'
import { Plus, X } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import type { BatchStatus, BatchStopReason, Severity } from '@/lib/types'
import { cn } from '@/lib/utils'

export const wan = (n: number) => {
  if (!n) return '0'
  const w = n / 10000
  return `${Number.isInteger(w) ? w : w.toFixed(w >= 10 ? 1 : 2).replace(/0+$/, '').replace(/\.$/, '')} 万`
}

export const STOP_REASON: Record<string, string> = {
  refine_pending: '精修章待审批',
  pending_chapter: '有章节还没提交',
  review_failed: '审稿未通过',
  awaiting_adopt: '等待选版本',
  paused: '作者暂停',
  target_reached: '已写满目标',
  error: '运行出错',
  needs_review: '待你看',
}
export const stopReasonLabel = (r?: BatchStopReason | string | null) => (r ? STOP_REASON[r] ?? r : '')

export const BATCH_STATUS: Record<BatchStatus, { label: string; tone: 'primary' | 'success' | 'warning' | 'danger' | 'neutral' }> = {
  running: { label: '连写中', tone: 'primary' },
  done: { label: '本批写完', tone: 'success' },
  stopped: { label: '已停下', tone: 'warning' },
  paused: { label: '已暂停', tone: 'neutral' },
  failed: { label: '失败', tone: 'danger' },
}

export const CH_STATUS: Record<string, { label: string; tone: 'neutral' | 'primary' | 'success' | 'warning' | 'outline' }> = {
  unwritten: { label: '未写', tone: 'outline' },
  draft: { label: '草稿', tone: 'neutral' },
  reviewing: { label: '待审批', tone: 'warning' },
  committed: { label: '已提交', tone: 'success' },
}
export function ChStatus({ status }: { status: string }) {
  const s = CH_STATUS[status] ?? { label: status, tone: 'neutral' as const }
  return <Badge tone={s.tone}>{s.label}</Badge>
}

export const SEV: Record<Severity, { label: string; tone: 'danger' | 'warning' | 'neutral'; dot: string }> = {
  high: { label: '严重', tone: 'danger', dot: 'bg-danger' },
  mid: { label: '中等', tone: 'warning', dot: 'bg-warning' },
  low: { label: '轻微', tone: 'neutral', dot: 'bg-muted-foreground/60' },
}
export function SevBadge({ s }: { s: Severity | string }) {
  const v = SEV[(s as Severity)] ?? SEV.mid
  return <Badge tone={v.tone} dot>{v.label}</Badge>
}

/** 「1-10, 15, 20~25」→ [[1,10],[15,15],[20,25]]（合并重叠、排序） */
export function parseRanges(text: string): [number, number][] {
  const out: [number, number][] = []
  for (const part of text.split(/[,，、;；\s]+/)) {
    const m = /^(\d+)(?:\s*[-–~～至到]\s*(\d+))?$/.exec(part.trim())
    if (!m) continue
    let a = Number(m[1]), b = Number(m[2] ?? m[1])
    if (a > b) [a, b] = [b, a]
    if (b < 1) continue
    out.push([Math.max(1, a), b])
  }
  return mergeRanges(out)
}
export function mergeRanges(rs: [number, number][]): [number, number][] {
  const s = [...rs].sort((x, y) => x[0] - y[0])
  const out: [number, number][] = []
  for (const [a, b] of s) {
    const last = out[out.length - 1]
    if (last && a <= last[1] + 1) last[1] = Math.max(last[1], b)
    else out.push([a, b])
  }
  return out
}
export const fmtRange = ([a, b]: [number, number] | number[]) => (a === b ? `第${a}章` : `第${a}–${b}章`)
/** 把章号列表压成区间文字：1,2,3,5 → 1–3、5 */
export function compactNums(nums: number[], max = 6): string {
  if (!nums.length) return ''
  const rs: [number, number][] = []
  for (const n of [...nums].sort((a, b) => a - b)) {
    const l = rs[rs.length - 1]
    if (l && n === l[1] + 1) l[1] = n
    else rs.push([n, n])
  }
  const parts = rs.slice(0, max).map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`))
  return parts.join('、') + (rs.length > max ? ' 等' : '')
}

/** 区间列表编辑：每行「起 – 止」两个输入，可增删；底部支持一次粘贴多段（如 1-10, 15） */
export function RangeEditor({ value, onChange }: { value: [number, number][]; onChange: (v: [number, number][]) => void }) {
  const [quick, setQuick] = useState('')
  const set = (i: number, k: 0 | 1, v: number) => onChange(value.map((r, j) => (j === i ? (k === 0 ? [v, r[1]] : [r[0], v]) as [number, number] : r)))
  const addQuick = () => {
    const rs = parseRanges(quick)
    if (!rs.length) return
    onChange(mergeRanges([...value, ...rs]))
    setQuick('')
  }
  const last = value[value.length - 1]
  return (
    <div className="space-y-2">
      {value.length === 0 && <p className="rounded-lg border border-dashed px-3 py-3 text-center text-[12.5px] text-muted-foreground">还没有区间，添加一段或在下方输入「1-10, 15」</p>}
      {value.map((r, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className="w-5 shrink-0 text-right text-[12px] text-muted-foreground num">{i + 1}</span>
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <span className="shrink-0 text-[12.5px] text-muted-foreground">第</span>
            <Input type="number" min={1} inputMode="numeric" className="h-9 min-w-0 flex-1 text-center num" value={r[0] || ''} onChange={(e) => set(i, 0, Number(e.target.value))} aria-label="起始章号" />
            <span className="shrink-0 text-[12.5px] text-muted-foreground">–</span>
            <Input type="number" min={1} inputMode="numeric" className="h-9 min-w-0 flex-1 text-center num" value={r[1] || ''} onChange={(e) => set(i, 1, Number(e.target.value))} aria-label="结束章号" />
            <span className="shrink-0 text-[12.5px] text-muted-foreground">章</span>
          </div>
          <button type="button" aria-label="删除这一段" onClick={() => onChange(value.filter((_, j) => j !== i))}
            className="focus-ring flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-danger-soft hover:text-danger">
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button type="button" onClick={() => onChange([...value, last ? [last[1] + 1, last[1] + 5] : [1, 10]])}
          className="focus-ring inline-flex h-9 items-center gap-1 rounded-md px-2 text-[13px] text-primary hover:bg-primary-soft/60">
          <Plus className="h-3.5 w-3.5" />添加区间
        </button>
        <div className="flex min-w-[200px] flex-1 items-center gap-1.5">
          <Input value={quick} onChange={(e) => setQuick(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addQuick() } }}
            placeholder="或输入：1-10, 15, 30-32" className="h-9 min-w-0 flex-1" />
          <button type="button" onClick={addQuick} disabled={!parseRanges(quick).length}
            className="focus-ring h-9 shrink-0 rounded-md border px-3 text-[13px] font-medium hover:bg-subtle disabled:opacity-50">加入</button>
        </div>
      </div>
    </div>
  )
}

/** 小标签行：左标签右内容 */
export function KV({ k, v, className }: { k: ReactNode; v: ReactNode; className?: string }) {
  return (
    <div className={cn('flex min-w-0 items-baseline justify-between gap-3 text-[13px]', className)}>
      <span className="shrink-0 text-muted-foreground">{k}</span>
      <span className="min-w-0 truncate text-right font-medium">{v}</span>
    </div>
  )
}

/** 指标小块 */
export function Tile({ label, value, sub, tone, className }: { label: ReactNode; value: ReactNode; sub?: ReactNode; tone?: 'danger' | 'success' | 'warning'; className?: string }) {
  return (
    <div className={cn('min-w-0 rounded-xl bg-subtle/70 px-3.5 py-3 hairline', className)}>
      <div className="truncate text-[12px] text-muted-foreground">{label}</div>
      <div className={cn('num mt-1 truncate text-[18px] font-semibold leading-tight tracking-tight', tone === 'danger' && 'text-danger', tone === 'success' && 'text-success', tone === 'warning' && 'text-warning')}>{value}</div>
      {sub && <div className="mt-1 line-clamp-2 break-words text-[11.5px] leading-snug text-muted-foreground">{sub}</div>}
    </div>
  )
}

export function Delta({ v, className }: { v: number | null | undefined; className?: string }) {
  if (v === null || v === undefined) return <span className={cn('text-muted-foreground', className)}>—</span>
  const r = Math.round(v * 10) / 10
  return <span className={cn('num font-semibold', r > 0 ? 'text-success' : r < 0 ? 'text-danger' : 'text-muted-foreground', className)}>{r > 0 ? `+${r}` : r}</span>
}
