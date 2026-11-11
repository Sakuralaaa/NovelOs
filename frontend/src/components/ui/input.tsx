import * as React from 'react'
import { cn } from '@/lib/utils'

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...p }, ref) => (
    <input
      ref={ref}
      className={cn(
        'flex h-9 w-full rounded-md border border-input bg-surface px-3 text-sm shadow-xs transition-[border,box-shadow] placeholder:text-muted-foreground/70 focus:border-primary/60 focus:shadow-glow focus:outline-none disabled:opacity-60',
        className,
      )}
      {...p}
    />
  ),
)
Input.displayName = 'Input'

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...p }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        'flex min-h-[84px] w-full rounded-md border border-input bg-surface px-3 py-2 text-sm leading-relaxed shadow-xs transition-[border,box-shadow] placeholder:text-muted-foreground/70 focus:border-primary/60 focus:shadow-glow focus:outline-none',
        className,
      )}
      {...p}
    />
  ),
)
Textarea.displayName = 'Textarea'

export function Label({ className, hint, children, ...p }: React.LabelHTMLAttributes<HTMLLabelElement> & { hint?: React.ReactNode }) {
  return (
    <label className={cn('mb-1.5 flex items-baseline justify-between gap-2 text-[13px] font-medium text-foreground/85', className)} {...p}>
      <span>{children}</span>
      {hint && <span className="text-xs font-normal text-muted-foreground">{hint}</span>}
    </label>
  )
}

export function Field({ label, hint, children, className }: { label: React.ReactNode; hint?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <Label hint={hint}>{label}</Label>
      {children}
    </div>
  )
}
