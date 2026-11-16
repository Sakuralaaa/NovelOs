import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Clock, Coins, Cpu, Loader2, Sparkles } from '@/components/icons'
import { Button, type ButtonProps } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { api } from '@/lib/api'
import { fmtSeconds, fmtTokens, setCostHint, useCostHint } from '@/lib/cost'
import type { Estimate, EstimateKind } from '@/lib/types'
import { cn } from '@/lib/utils'

export interface CostTarget { kind: EstimateKind; bookId?: number; chapterId?: number; words?: number }

export function useEstimate(t: CostTarget, enabled: boolean) {
  return useQuery({
    queryKey: ['estimate', t.kind, t.bookId ?? 0, t.chapterId ?? 0, t.words ?? 0],
    queryFn: () => api.estimate({ kind: t.kind, book_id: t.bookId, chapter_id: t.chapterId, ...(t.words ? { words: t.words } : {}) }),
    enabled,
    staleTime: 60_000,
    retry: false,
  })
}

/** 成本提示正文：预计 token / 调用次数 / 模型 / 预计耗时 */
export function EstimateBody({ q, compact }: { q: ReturnType<typeof useEstimate>; compact?: boolean }) {
  if (q.isLoading) return <div className="flex items-center gap-2 py-2 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />正在估算…</div>
  if (q.error || !q.data) return <p className="py-1 text-[12.5px] text-muted-foreground">暂时估算不了（{(q.error as Error | null)?.message || '后端没有返回'}），仍可以直接开始。</p>
  const e: Estimate = q.data
  const rows = [
    { i: Coins, k: '预计 token', v: <>{fmtTokens((e.input_tokens_est || 0) + (e.output_tokens_est || 0))}<span className="ml-1 text-[11.5px] font-normal text-muted-foreground">入 {fmtTokens(e.input_tokens_est)} / 出 {fmtTokens(e.output_tokens_est)}</span></> },
    { i: Sparkles, k: '调用次数', v: `${e.calls_est} 次` },
    { i: Cpu, k: '模型', v: <span className="font-mono text-[12px]" title={e.route ? `路由：${e.route}` : undefined}>{e.model || '默认路由'}</span> },
    { i: Clock, k: '预计耗时', v: <>{fmtSeconds(e.seconds_est)}{e.seconds_source === 'default' && <span className="ml-1 text-[11px] font-normal text-muted-foreground">经验值</span>}</> },
  ]
  return (
    <div className={cn('grid gap-x-3 gap-y-2', compact ? 'grid-cols-2' : 'grid-cols-1')}>
      {rows.map((r) => (
        <div key={r.k} className="flex min-w-0 items-center gap-2">
          <r.i className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
          <span className="shrink-0 text-[12px] text-muted-foreground">{r.k}</span>
          <span className="num ml-auto min-w-0 truncate text-right text-[13px] font-medium">{r.v}</span>
        </div>
      ))}
      {e.note && <p className="col-span-full text-[11.5px] leading-relaxed text-muted-foreground">{e.note}</p>}
    </div>
  )
}

/**
 * AI 操作按钮：开着成本提示时，先弹浮层显示预估再确认；在设置里关掉后直接执行。
 * `label` 给浮层标题用（按钮文字可能在窄屏隐藏）。
 */
export function CostButton({ target, label, onRun, confirmLabel = '开始', children, disabled, ...btn }: ButtonProps & {
  target: CostTarget; label: string; onRun: () => void; confirmLabel?: string
}) {
  const hint = useCostHint()
  const [open, setOpen] = useState(false)
  const q = useEstimate(target, hint && open)
  const [never, setNever] = useState(false)
  if (!hint) return <Button {...btn} disabled={disabled} onClick={onRun}>{children}</Button>
  const go = () => { if (never) setCostHint(false); setOpen(false); onRun() }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild><Button {...btn} disabled={disabled} aria-haspopup="dialog">{children}</Button></PopoverTrigger>
      <PopoverContent className="w-[300px]" onOpenAutoFocus={(e) => e.preventDefault()}>
        <div className="mb-2.5 flex items-center gap-1.5 text-[13.5px] font-semibold"><Sparkles className="h-4 w-4 text-primary" />{label}</div>
        <EstimateBody q={q} />
        <label className="mt-3 flex min-h-[40px] cursor-pointer items-center gap-2 text-[12.5px] text-muted-foreground">
          <input type="checkbox" checked={never} onChange={(e) => setNever(e.target.checked)} className="h-4 w-4 accent-[hsl(var(--primary))]" />
          不再提示（可在设置里重新打开）
        </label>
        <div className="mt-2 flex justify-end gap-2">
          <Button variant="ghost" className="h-10" onClick={() => setOpen(false)}>取消</Button>
          <Button variant="primary" className="h-10" onClick={go}>{confirmLabel}</Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
