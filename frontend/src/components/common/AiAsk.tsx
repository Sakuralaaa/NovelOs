import { useState, type ReactNode } from 'react'
import { AlertTriangle, Sparkles, Wand2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { Select, type Opt } from '@/components/ui/select'
import { JobInline } from '@/components/common/JobInline'
import { useChannels } from '@/hooks/queries'
import type { TrackedJob } from '@/lib/jobs'
import type { TropeHit } from '@/lib/types'
import { cn } from '@/lib/utils'

/** 「可选模型」：和选题卡、设定卡一样，按页面记住上次选的模型；不选走默认路由 */
export function useModelRoute(storageKey: string) {
  const channels = useChannels()
  const opts: Opt[] = (channels.data ?? []).filter((c) => c.enabled).flatMap((c) => c.models.map((m) => ({ value: `${c.id}:${m}`, label: <span className="font-mono text-[12.5px]">{m}</span>, group: c.name })))
  const [route, setRouteState] = useState<string | null>(() => localStorage.getItem(storageKey) || null)
  const model = route && opts.some((o) => o.value === route) ? route : null
  const setRoute = (v: string | null) => { setRouteState(v); if (v) localStorage.setItem(storageKey, v); else localStorage.removeItem(storageKey) }
  return { opts, model, setRoute }
}

export function ModelSelect({ storage, emptyLabel = '默认（策划模型）', className }: { storage: ReturnType<typeof useModelRoute>; emptyLabel?: string; className?: string }) {
  return <div className={cn('w-[200px]', className)}><Select value={storage.model} onChange={storage.setRoute} options={storage.opts} allowEmpty emptyLabel={emptyLabel} placeholder={emptyLabel} /></div>
}

/** 写要求 + 选模型 + 发起：各页「让 AI 改」统一用这一块 */
export function AskBox({ title, placeholder, value, onChange, onSubmit, job, storage, submitLabel = '让 AI 改', disabled, emptyLabel, extra, allowEmpty, className }: {
  title: ReactNode; placeholder: string; value: string; onChange: (v: string) => void; onSubmit: () => void
  job?: TrackedJob; storage: ReturnType<typeof useModelRoute>; submitLabel?: string; disabled?: boolean; emptyLabel?: string; extra?: ReactNode
  allowEmpty?: boolean; className?: string
}) {
  const can = (allowEmpty || !!value.trim()) && !job && !disabled
  return (
    <div className={cn('space-y-2.5 rounded-xl bg-primary-soft/40 p-3 hairline', className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-[13px] font-semibold"><Wand2 className="h-4 w-4 text-primary" />{title}</span>
        <ModelSelect storage={storage} emptyLabel={emptyLabel} />
      </div>
      <Textarea rows={2} value={value} disabled={!!job} onChange={(e) => onChange(e.target.value)} className="min-h-[64px] bg-surface text-[13px]"
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && can) onSubmit() }} placeholder={placeholder} />
      {extra}
      <div className="flex items-center justify-end gap-3">
        {job && <div className="min-w-0 flex-1"><JobInline job={job} /></div>}
        <Button size="sm" variant="primary" icon={<Sparkles className="h-3.5 w-3.5" />} loading={!!job} disabled={!can} onClick={onSubmit}>{submitLabel}</Button>
      </div>
    </div>
  )
}

/** 命中禁用套路时的黄色提醒，可一键让 AI 换掉 */
export function TropeAlert({ hits, onReplace, busy, className, compact }: { hits?: TropeHit[]; onReplace?: () => void; busy?: boolean; className?: string; compact?: boolean }) {
  if (!hits?.length) return null
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning', className)}>
      <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 flex-1 break-words">
        命中禁用套路：{hits.map((h) => h.name).join('、')}
        {!compact && <span className="opacity-75">（{hits.flatMap((h) => h.hits).join('、')}）</span>}
      </span>
      {onReplace && <Button size="xs" variant="ghost" loading={busy} onClick={onReplace} className="text-warning hover:bg-warning/10 hover:text-warning">让 AI 换掉</Button>}
    </div>
  )
}

/** 旧 / 新对比（字段级） */
export function CompareRow({ label, before, after, onChange, multiline }: { label: string; before: string; after: string; onChange?: (v: string) => void; multiline?: boolean }) {
  const changed = before !== after
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2 text-[13px] font-medium text-foreground/85">{label}{changed ? <span className="rounded bg-primary-soft px-1.5 py-px text-[11px] font-normal text-primary">有改动</span> : <span className="text-[11px] font-normal text-muted-foreground">未改</span>}</div>
      <div className="grid gap-2 md:grid-cols-2">
        <div className={cn('rounded-lg px-3 py-2 text-[13px] leading-relaxed', changed ? 'bg-danger-soft/50 text-foreground/60' : 'bg-subtle text-foreground/70')}>
          <div className="mb-0.5 text-[11px] text-muted-foreground">现在</div>
          <p className="whitespace-pre-wrap break-words">{before || <span className="text-muted-foreground">（空）</span>}</p>
        </div>
        <div className={cn('rounded-lg px-3 py-2', changed ? 'bg-success-soft/60 ring-1 ring-success/25' : 'bg-subtle')}>
          <div className="mb-0.5 text-[11px] text-muted-foreground">改后（可再手改）</div>
          {onChange ? (
            <Textarea value={after} rows={multiline ? 4 : 1} onChange={(e) => onChange(e.target.value)} className={cn('bg-surface text-[13px]', multiline ? 'min-h-[96px]' : 'min-h-[38px]')} />
          ) : <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed">{after}</p>}
        </div>
      </div>
    </div>
  )
}
