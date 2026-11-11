import * as React from 'react'
import { cn } from '@/lib/utils'

export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={cn('relative overflow-hidden rounded-md bg-muted', className)}>
      <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/40 to-transparent dark:via-white/5" />
    </div>
  )
}

export function Progress({ value, className, indeterminate, tone = 'primary' }: { value: number; className?: string; indeterminate?: boolean; tone?: 'primary' | 'success' | 'danger' }) {
  const bar = tone === 'success' ? 'bg-success' : tone === 'danger' ? 'bg-danger' : 'bg-primary'
  return (
    <div className={cn('h-1.5 w-full overflow-hidden rounded-full bg-muted', className)}>
      <div
        className={cn('h-full rounded-full transition-[width] duration-500 ease-out', bar, indeterminate && 'animate-stripes')}
        style={{
          width: `${Math.max(indeterminate ? 30 : 3, Math.min(100, value))}%`,
          backgroundImage: indeterminate ? 'linear-gradient(45deg,rgba(255,255,255,.25) 25%,transparent 25%,transparent 50%,rgba(255,255,255,.25) 50%,rgba(255,255,255,.25) 75%,transparent 75%)' : undefined,
          backgroundSize: '24px 24px',
        }}
      />
    </div>
  )
}

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <kbd className={cn('inline-flex h-5 min-w-5 items-center justify-center rounded border border-b-2 bg-surface px-1 font-mono text-[10.5px] text-muted-foreground', className)}>{children}</kbd>
}

export function Separator({ className, vertical }: { className?: string; vertical?: boolean }) {
  return <div className={cn(vertical ? 'mx-1 h-5 w-px' : 'h-px w-full', 'bg-border', className)} />
}

/** 圆环评分 */
export function ScoreRing({ value, size = 52, stroke = 5, label, className }: { value: number; size?: number; stroke?: number; label?: string; className?: string }) {
  const v = Math.max(0, Math.min(100, Math.round(value)))
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const color = v >= 80 ? 'hsl(var(--success))' : v >= 60 ? 'hsl(var(--primary))' : v >= 40 ? 'hsl(var(--warning))' : 'hsl(var(--danger))'
  return (
    <div className={cn('relative inline-flex shrink-0 items-center justify-center', className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} stroke="hsl(var(--muted))" strokeWidth={stroke} fill="none" />
        <circle
          cx={size / 2} cy={size / 2} r={r} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} style={{ transition: 'stroke-dashoffset .8s cubic-bezier(.2,.8,.2,1)' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        <span className="num font-semibold" style={{ fontSize: size * 0.3 }}>{v}</span>
        {label && <span className="mt-0.5 text-[10px] text-muted-foreground">{label}</span>}
      </div>
    </div>
  )
}

export function Stat({ label, value, sub, icon, className }: { label: string; value: React.ReactNode; sub?: React.ReactNode; icon?: React.ReactNode; className?: string }) {
  return (
    <div className={cn('rounded-xl bg-surface p-4 hairline shadow-card', className)}>
      <div className="flex items-center gap-1.5 text-[12.5px] text-muted-foreground">{icon}{label}</div>
      <div className="num mt-1.5 text-[22px] font-semibold tracking-tight">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  )
}
