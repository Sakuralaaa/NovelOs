import * as React from 'react'
import * as T from '@radix-ui/react-tabs'
import { cn } from '@/lib/utils'

export const Tabs = T.Root
export const TabsContent = T.Content
export function TabsList({ className, ...p }: React.ComponentProps<typeof T.List>) {
  return <T.List className={cn('inline-flex h-9 items-center gap-0.5 rounded-lg bg-muted p-[3px]', className)} {...p} />
}
export function TabsTrigger({ className, ...p }: React.ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        'focus-ring inline-flex h-full flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-3 text-[13px] font-medium text-muted-foreground transition-all hover:text-foreground data-[state=active]:bg-surface data-[state=active]:text-foreground data-[state=active]:shadow-card',
        className,
      )}
      {...p}
    />
  )
}

/** 轻量分段控件 */
export function Segmented<T extends string>({ value, onChange, options, className, size = 'md' }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: React.ReactNode }[]; className?: string; size?: 'sm' | 'md'
}) {
  return (
    <div className={cn('inline-flex items-center gap-0.5 rounded-lg bg-muted p-[3px]', size === 'sm' ? 'h-8' : 'h-9', className)} role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            'focus-ring inline-flex h-full items-center gap-1.5 whitespace-nowrap rounded-md px-3 text-[13px] font-medium transition-all',
            value === o.value ? 'bg-surface text-foreground shadow-card' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
