import { useMemo, useState } from 'react'
import { Check, RotateCcw, Undo2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { diffParas, type DiffRow } from '@/lib/textAnalysis'
import { cn } from '@/lib/utils'

/** 修改前后逐段对比：每处改动可单独接受 / 撤销 */
export function DiffView({ title, before, after, onApply, onClose, applying }: {
  title: string; before: string; after: string; applying: boolean
  onApply: (content: string, summary: { accepted: number; reverted: number }) => void; onClose: () => void
}) {
  const rows = useMemo(() => diffParas(before, after), [before, after])
  const changedIdx = rows.map((r, i) => (r.type === 'same' ? -1 : i)).filter((i) => i >= 0)
  const [rejected, setRejected] = useState<Set<number>>(new Set())
  const toggle = (i: number) => setRejected((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })
  const compose = () => rows.flatMap((r, i): string[] => {
    const acc = !rejected.has(i)
    if (r.type === 'same') return [r.text]
    if (r.type === 'changed') return [acc ? r.after : r.before]
    if (r.type === 'added') return acc ? [r.after] : []
    return acc ? [] : [r.before]
  }).join('\n')

  return (
    <div className="flex h-full flex-col">
      <div className="sticky top-0 z-10 flex flex-wrap items-center justify-between gap-3 border-b bg-background/90 px-6 py-3 backdrop-blur">
        <div>
          <div className="text-[14px] font-semibold">{title}</div>
          <div className="text-xs text-muted-foreground">共改动 {changedIdx.length} 处 · 已接受 {changedIdx.length - rejected.size} · 撤销 {rejected.size}</div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setRejected(new Set(changedIdx))}>全部撤销</Button>
          <Button size="sm" variant="ghost" icon={<Check className="h-3.5 w-3.5" />} onClick={() => setRejected(new Set())}>全部接受</Button>
          <Button size="sm" variant="primary" loading={applying} onClick={() => onApply(compose(), { accepted: changedIdx.length - rejected.size, reverted: rejected.size })}>确定</Button>
          <Button size="icon-sm" variant="ghost" onClick={onClose} aria-label="关闭"><X className="h-4 w-4" /></Button>
        </div>
      </div>
      <div className="mx-auto w-full max-w-[860px] flex-1 space-y-2 px-6 py-6">
        {changedIdx.length === 0 && <p className="py-16 text-center text-sm text-muted-foreground">这次没有改动任何段落。</p>}
        {rows.map((r, i) => <Row key={i} row={r} rejected={rejected.has(i)} onToggle={() => toggle(i)} />)}
      </div>
    </div>
  )
}

function Row({ row: r, rejected, onToggle }: { row: DiffRow; rejected: boolean; onToggle: () => void }) {
  if (r.type === 'same') return <p className="prose-zh px-3 font-serif text-[15px] text-foreground/45">{r.text}</p>
  const before = r.type === 'changed' || r.type === 'removed' ? r.before : null
  const after = r.type === 'changed' || r.type === 'added' ? r.after : null
  return (
    <div className={cn('group rounded-xl p-3 transition hairline', rejected ? 'bg-subtle' : 'bg-surface shadow-card')}>
      <div className="grid gap-3 md:grid-cols-2">
        <div className={cn('rounded-lg px-3 py-2', rejected ? 'bg-surface ring-1 ring-primary/30' : 'bg-danger-soft/60')}>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">修改前</div>
          <p className={cn('prose-zh font-serif text-[14.5px]', !rejected && 'text-foreground/55 line-through decoration-danger/40')}>{before ?? <span className="text-muted-foreground">（无）</span>}</p>
        </div>
        <div className={cn('rounded-lg px-3 py-2', rejected ? 'opacity-50' : 'bg-success-soft/70 ring-1 ring-success/30')}>
          <div className="mb-1 text-[11px] font-medium text-muted-foreground">修改后</div>
          <p className="prose-zh font-serif text-[14.5px]">{after ?? <span className="text-muted-foreground">（删除此段）</span>}</p>
        </div>
      </div>
      <div className="mt-2 flex justify-end">
        <Button size="xs" variant={rejected ? 'soft' : 'ghost'} icon={rejected ? <Check className="h-3 w-3" /> : <Undo2 className="h-3 w-3" />} onClick={onToggle}>{rejected ? '改为接受' : '撤销这处'}</Button>
      </div>
    </div>
  )
}
