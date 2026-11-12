import * as React from 'react'
import { Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger' | 'soft' | 'link'
type Size = 'xs' | 'sm' | 'md' | 'lg' | 'icon' | 'icon-sm'

const variants: Record<Variant, string> = {
  primary:
    'bg-primary text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.16),0_1px_2px_rgb(30_27_75/0.18)] hover:brightness-[1.06] active:brightness-95',
  secondary: 'border border-border bg-surface text-foreground shadow-xs hover:border-foreground/15 hover:bg-subtle active:bg-muted',
  outline: 'border border-input bg-transparent hover:bg-subtle',
  ghost: 'text-foreground/80 hover:bg-muted hover:text-foreground',
  soft: 'bg-primary-soft text-primary hover:bg-primary/15',
  danger: 'bg-danger text-white hover:bg-danger/90',
  link: 'text-primary underline-offset-4 hover:underline px-0 h-auto',
}
const sizes: Record<Size, string> = {
  xs: 'h-7 px-2 text-xs gap-1 rounded-sm',
  sm: 'h-8 px-3 text-[13px] gap-1.5 rounded-md',
  md: 'h-9 px-3.5 text-sm gap-2 rounded-md',
  lg: 'h-10 px-5 text-[14px] gap-2 rounded-lg',
  icon: 'h-9 w-9 rounded-md',
  'icon-sm': 'h-7 w-7 rounded-sm',
}

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: React.ReactNode
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'secondary', size = 'md', loading, icon, children, disabled, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'focus-ring inline-flex shrink-0 select-none items-center justify-center whitespace-nowrap font-medium transition-[background,color,box-shadow,transform] duration-150 disabled:pointer-events-none disabled:opacity-55',
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  ),
)
Button.displayName = 'Button'
