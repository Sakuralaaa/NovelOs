import { useState } from 'react'
import { X } from '@/components/icons'
import { cn } from '@/lib/utils'

/** 标签/模型名输入：回车或逗号添加 */
export function TagInput({ value, onChange, placeholder = '输入后回车添加', className, suggestions }: {
  value: string[]; onChange: (v: string[]) => void; placeholder?: string; className?: string; suggestions?: string[]
}) {
  const [draft, setDraft] = useState('')
  const add = (raw: string) => {
    const parts = raw.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean)
    if (!parts.length) return
    onChange(Array.from(new Set([...value, ...parts])))
    setDraft('')
  }
  const rest = (suggestions ?? []).filter((s) => !value.includes(s))
  return (
    <div>
      <div className={cn('flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border border-input bg-surface px-2 py-1.5 shadow-xs focus-within:border-primary/60 focus-within:shadow-glow', className)}>
        {value.map((t) => (
          <span key={t} className="inline-flex h-6 items-center gap-1 rounded-md bg-muted pl-2 pr-1 text-[12.5px]">
            {t}
            <button type="button" className="rounded p-0.5 text-muted-foreground hover:bg-background hover:text-foreground" onClick={() => onChange(value.filter((x) => x !== t))} aria-label={`移除 ${t}`}>
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
        <input
          value={draft}
          onChange={(e) => {
            const v = e.target.value
            if (/[,，]/.test(v)) add(v)
            else setDraft(v)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); add(draft) }
            if (e.key === 'Backspace' && !draft && value.length) onChange(value.slice(0, -1))
          }}
          onBlur={() => draft && add(draft)}
          placeholder={value.length ? '' : placeholder}
          className="h-6 min-w-[120px] flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-muted-foreground/70"
        />
      </div>
      {rest.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {rest.map((s) => (
            <button key={s} type="button" onClick={() => onChange([...value, s])} className="h-6 rounded-md border border-dashed px-2 text-xs text-muted-foreground transition hover:border-primary/50 hover:text-primary">
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
