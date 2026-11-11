import * as React from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-xl bg-surface hairline shadow-card', className)} {...p} />
}
export function CardHeader({ className, title, desc, action, icon }: {
  className?: string; title: React.ReactNode; desc?: React.ReactNode; action?: React.ReactNode; icon?: React.ReactNode
}) {
  return (
    <div className={cn('flex items-start justify-between gap-3 px-5 pt-4 pb-3', className)}>
      <div className="flex min-w-0 items-start gap-2.5">
        {icon && <div className="mt-0.5 text-muted-foreground">{icon}</div>}
        <div className="min-w-0">
          <h3 className="text-[15px] font-semibold tracking-tight">{title}</h3>
          {desc && <p className="mt-0.5 text-[13px] text-muted-foreground">{desc}</p>}
        </div>
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  )
}
export function CardBody({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 pb-5', className)} {...p} />
}
