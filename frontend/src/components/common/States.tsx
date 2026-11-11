import type { ReactNode } from 'react'
import { RotateCw } from 'lucide-react'
import { Illustration } from './Illustrations'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function EmptyState({ kind, title, desc, action, className, compact }: {
  kind: Parameters<typeof Illustration>[0]['kind']; title: ReactNode; desc?: ReactNode; action?: ReactNode; className?: string; compact?: boolean
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center rounded-xl border border-dashed bg-surface/60 px-6 text-center', compact ? 'py-8' : 'py-14', className)}>
      <Illustration kind={kind} size={compact ? 96 : 132} />
      <h3 className="mt-3 text-[15px] font-semibold">{title}</h3>
      {desc && <p className="mt-1.5 max-w-sm text-[13px] leading-relaxed text-muted-foreground text-balance">{desc}</p>}
      {action && <div className="mt-5 flex flex-wrap items-center justify-center gap-2">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry, className }: { error: unknown; onRetry?: () => void; className?: string }) {
  const msg = (error as any)?.message ?? '出了点问题'
  return (
    <EmptyState
      kind="error"
      className={className}
      title="数据加载失败"
      desc={msg}
      action={onRetry && <Button size="sm" icon={<RotateCw className="h-3.5 w-3.5" />} onClick={onRetry}>重试</Button>}
    />
  )
}

export function PageHeader({ title, desc, actions, eyebrow, className }: { title: ReactNode; desc?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode; className?: string }) {
  return (
    <div className={cn('mb-6 flex flex-wrap items-end justify-between gap-4', className)}>
      <div className="min-w-0">
        {eyebrow && <div className="mb-1.5 text-[12.5px] font-medium text-muted-foreground">{eyebrow}</div>}
        <h1 className="text-[24px] font-semibold leading-tight tracking-tight">{title}</h1>
        {desc && <p className="mt-1.5 max-w-2xl text-[13.5px] leading-relaxed text-muted-foreground">{desc}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-[#5b6cf0] to-[#8b5cf6] shadow-[0_2px_8px_-2px_rgb(91_108_240/0.6)]">
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none"><path d="M7 17V7l10 10V7" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" /></svg>
      </div>
      {!collapsed && (
        <div className="leading-none">
          <div className="text-[15px] font-semibold tracking-tight">NovelOS</div>
          <div className="mt-1 text-[10.5px] text-muted-foreground">网文创作工作台</div>
        </div>
      )}
    </div>
  )
}
