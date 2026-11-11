import * as S from '@radix-ui/react-select'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface Opt { value: string; label: React.ReactNode; group?: string; disabled?: boolean }

const NONE = '__none__'

export function Select({ value, onChange, options, placeholder = '请选择', className, allowEmpty, emptyLabel = '不设置' }: {
  value: string | null | undefined; onChange: (v: string | null) => void; options: Opt[]; placeholder?: string; className?: string; allowEmpty?: boolean; emptyLabel?: string
}) {
  const groups = Array.from(new Set(options.map((o) => o.group ?? '')))
  return (
    <S.Root value={value ?? (allowEmpty ? NONE : undefined)} onValueChange={(v) => onChange(v === NONE ? null : v)}>
      <S.Trigger
        className={cn(
          'focus-ring flex h-9 w-full items-center justify-between gap-2 rounded-md border border-input bg-surface px-3 text-sm shadow-xs transition hover:bg-subtle data-[placeholder]:text-muted-foreground',
          className,
        )}
      >
        <span className="truncate"><S.Value placeholder={placeholder} /></span>
        <S.Icon><ChevronDown className="h-4 w-4 opacity-60" /></S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content position="popper" sideOffset={6} className="z-[60] max-h-[320px] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg bg-popover p-1 shadow-pop hairline animate-zoom-in">
          <S.Viewport>
            {allowEmpty && <Item value={NONE}><span className="text-muted-foreground">{emptyLabel}</span></Item>}
            {groups.map((g) => (
              <S.Group key={g}>
                {g && <S.Label className="px-2 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{g}</S.Label>}
                {options.filter((o) => (o.group ?? '') === g).map((o) => (
                  <Item key={o.value} value={o.value} disabled={o.disabled}>{o.label}</Item>
                ))}
              </S.Group>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  )
}

function Item({ value, children, disabled }: { value: string; children: React.ReactNode; disabled?: boolean }) {
  return (
    <S.Item
      value={value}
      disabled={disabled}
      className="relative flex cursor-default select-none items-center rounded-md py-1.5 pl-7 pr-3 text-sm outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-muted"
    >
      <S.ItemIndicator className="absolute left-2"><Check className="h-3.5 w-3.5 text-primary" /></S.ItemIndicator>
      <S.ItemText>{children}</S.ItemText>
    </S.Item>
  )
}
