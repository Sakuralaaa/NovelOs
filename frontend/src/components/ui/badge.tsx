import * as React from 'react'
import { cn } from '@/lib/utils'

type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'danger' | 'outline'
const tones: Record<Tone, string> = {
  neutral: 'bg-muted text-muted-foreground',
  primary: 'bg-primary-soft text-primary',
  success: 'bg-success-soft text-success',
  warning: 'bg-warning-soft text-warning',
  danger: 'bg-danger-soft text-danger',
  outline: 'hairline text-muted-foreground',
}
export function Badge({ tone = 'neutral', className, dot, children, title, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone; dot?: boolean }) {
  return (
    <span
      title={title ?? (typeof children === 'string' ? children : undefined)}
      className={cn('inline-flex h-[22px] max-w-full shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2 text-[12px] font-medium leading-none', tones[tone], className)}
      {...p}
    >
      {dot && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />}
      <span className="inline-flex min-w-0 items-center gap-1 overflow-hidden text-ellipsis">{children}</span>
    </span>
  )
}
