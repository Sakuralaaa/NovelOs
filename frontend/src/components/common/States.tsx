import type { ReactNode } from 'react'
import { RotateCw } from '@/components/icons'
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

// "/N" mark, same slash geometry as Atoll's "/A" so the two sit together in a tab bar.
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="-15.84 -12 124 124" fill="currentColor" aria-hidden="true" className={cn('h-7 w-7 shrink-0 text-foreground', className)}>
      <path d="M18.313 0L34.109 0L1.109 100L-14.687 100ZM17.6 100L50.6 0L68.4 0L72.06 58L91.2 0L107 0L74 100L56.2 100L52.54 42L33.4 100Z" />
    </svg>
  )
}

export function Logo({ collapsed }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && <span className="font-serif text-[17px] font-semibold tracking-tight">NovelOS</span>}
    </div>
  )
}
