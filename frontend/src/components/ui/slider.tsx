import * as S from '@radix-ui/react-slider'
import { cn } from '@/lib/utils'

/** 单值滑条：轨道 6px、拇指 24px（触控友好），外层留 32px 高度好按 */
export function Slider({ value, onChange, min = 0, max = 100, step = 1, className, label, color }: {
  value: number; onChange: (v: number) => void; min?: number; max?: number; step?: number; className?: string; label?: string; color?: string
}) {
  return (
    <S.Root value={[value]} min={min} max={max} step={step} onValueChange={(v) => onChange(v[0])} aria-label={label}
      className={cn('relative flex h-8 w-full touch-none select-none items-center', className)}>
      <S.Track className="relative h-1.5 grow overflow-hidden rounded-full bg-muted">
        <S.Range className="absolute h-full rounded-full bg-primary" style={color ? { background: color } : undefined} />
      </S.Track>
      <S.Thumb className="focus-ring block h-6 w-6 rounded-full border-2 border-primary bg-surface shadow-card transition-transform active:scale-110" style={color ? { borderColor: color } : undefined} />
    </S.Root>
  )
}
