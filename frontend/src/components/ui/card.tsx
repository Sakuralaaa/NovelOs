import * as React from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-xl border bg-surface shadow-card', className)} {...p} />
}

/** 卡片标题行：统一 56px 高、图标同尺寸色块，保证所有卡片标题对齐 */
export function CardHeader({ className, title, desc, action, icon, divider = true }: {
  className?: string; title: React.ReactNode; desc?: React.ReactNode; action?: React.ReactNode; icon?: React.ReactNode; divider?: boolean
}) {
  return (
    <div className={cn('flex min-h-[56px] items-center justify-between gap-3 px-5 py-3', divider && 'border-b', className)}>
      <div className="flex min-w-0 items-center gap-2.5">
        {icon && <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted text-foreground/70 [&_svg]:h-[15px] [&_svg]:w-[15px]">{icon}</div>}
        <div className="min-w-0">
          <h3 className="truncate text-[14.5px] font-semibold tracking-tight">{title}</h3>
          {desc && <p className="truncate text-[12.5px] text-muted-foreground">{desc}</p>}
        </div>
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  )
}
export function CardBody({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5', className)} {...p} />
}
