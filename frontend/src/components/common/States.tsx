import type { ReactNode } from 'react'
import { RotateCw } from 'lucide-react'
import { Illustration } from './Illustrations'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export function EmptyState({ kind, title, desc, action, className, compact }: {
  kind: Parameters<typeof Illustration>[0]['kind']; title: ReactNode; desc?: ReactNode; action?: ReactNode; className?: string; compact?: boolean
}) {
  return (
    <div className={cn('flex flex-col items-center justify-center rounded-xl border border-dashed bg-surface/60 px-6 text-center', compact ? 'py-8' : 'py-16', className)}>
      <Illustration kind={kind} size={compact ? 88 : 112} />
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
    <div className={cn('mb-7 flex min-h-[40px] flex-wrap items-center justify-between gap-x-4 gap-y-3', className)}>
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[12.5px] text-muted-foreground">{eyebrow}</div>}
        <h1 className="truncate text-[22px] font-semibold leading-tight tracking-tight">{title}</h1>
        {desc && <p className="mt-1 text-[13px] text-muted-foreground">{desc}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function LogoMark({ className }: { className?: string }) {
  return (
    <div className={cn('relative flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-[9px] bg-[linear-gradient(135deg,#6366f1_0%,#7c3aed_100%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.25),0_1px_2px_rgb(76_29_149/0.35)]', className)}>
      <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none">
        <path d="M6 18.5V6.8c0-.6.7-.9 1.1-.5l9.8 11.4c.4.4 1.1.1 1.1-.5V5.5" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  )
}

export function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && <span className="text-[15px] font-semibold tracking-tight">NovelOS</span>}
    </div>
  )
}
