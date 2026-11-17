import { Plus, X } from '@/components/icons'
import { Input } from '@/components/ui/input'
import type { FanficDepth, FanficFidelity, OocLevel, OverlapLevel } from '@/lib/types'
import { cn } from '@/lib/utils'

export const DEPTHS: { value: FanficDepth; label: string; desc: string }[] = [
  { value: 'quick', label: '快速', desc: '1 轮提炼，几分钟出主角与主线' },
  { value: 'standard', label: '标准', desc: '2 轮提炼，覆盖主要角色与势力' },
  { value: 'deep', label: '深入', desc: '4 轮提炼，配角、时间线更全，耗时更长' },
]
export const depthLabel = (d?: string) => DEPTHS.find((x) => x.value === d)?.label ?? d ?? ''
/** v0.11.1 来源标签：联网 / 粘贴 / TXT（原文 + 联网补充显示「+联网」） */
export const sourceLabel = (s: { source: string; web_rounds?: number }) =>
  s.source === 'search' ? '联网' : `${s.source === 'txt' ? 'TXT' : '粘贴'}${s.web_rounds ? '+联网' : ''}`

export const FIDELITY_FALLBACK: { id: FanficFidelity; label: string; desc: string; pass_score: number }[] = [
  { id: 'strict', label: '严格遵循', desc: '原著设定与时间线都不改', pass_score: 80 },
  { id: 'moderate', label: '有据延展', desc: '可改支线与结局，人设不变', pass_score: 70 },
  { id: 'loose', label: '分歧世界（AU）', desc: '只保留人物核心', pass_score: 55 },
]

export const LEVEL_TONE: Record<OocLevel, 'success' | 'warning' | 'danger'> = { pass: 'success', warn: 'warning', fail: 'danger' }
export const LEVEL_LABEL: Record<OocLevel, string> = { pass: '通过', warn: '注意', fail: '不通过' }
export const OVERLAP_TONE: Record<OverlapLevel, 'success' | 'neutral' | 'warning' | 'danger'> = { ok: 'success', info: 'neutral', warn: 'warning', high: 'danger' }
export const OVERLAP_LABEL: Record<OverlapLevel, string> = { ok: '无重合', info: '少量重合', warn: '重合偏多', high: '重合严重' }

/** 字符串列表编辑：每行一个输入框，可增删（触控目标 ≥40px） */
export function StrList({ value, onChange, placeholder, addLabel = '添加一条', max }: {
  value: string[]; onChange: (v: string[]) => void; placeholder?: string; addLabel?: string; max?: number
}) {
  return (
    <div className="space-y-1.5">
      {value.map((v, i) => (
        <div key={i} className="flex min-w-0 items-center gap-1.5">
          <Input value={v} placeholder={placeholder} className="h-10 min-w-0 flex-1"
            onChange={(e) => onChange(value.map((x, k) => (k === i ? e.target.value : x)))} />
          <RemoveBtn onClick={() => onChange(value.filter((_, k) => k !== i))} />
        </div>
      ))}
      {(!max || value.length < max) && (
        <button type="button" onClick={() => onChange([...value, ''])}
          className="focus-ring inline-flex h-10 items-center gap-1 rounded-md px-2 text-[13px] text-primary hover:bg-primary-soft/60">
          <Plus className="h-3.5 w-3.5" />{addLabel}
        </button>
      )}
    </div>
  )
}

export function RemoveBtn({ onClick, label = '删除', className }: { onClick: () => void; label?: string; className?: string }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick}
      className={cn('focus-ring flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-danger-soft hover:text-danger', className)}>
      <X className="h-4 w-4" />
    </button>
  )
}

/** 小标题 + 内容 */
export function Lbl({ children, hint }: { children: React.ReactNode; hint?: React.ReactNode }) {
  return <div className="mb-1 flex items-baseline justify-between gap-2 text-[12px] font-medium text-muted-foreground"><span>{children}</span>{hint && <span className="font-normal">{hint}</span>}</div>
}

/** 短标签编辑（别称、口癖、成员…）：回车/逗号添加，点标签移除；每个标签本身就是 40px 高的按钮 */
export function Chips({ value, onChange, placeholder = '输入后回车添加', max }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; max?: number }) {
  const add = (raw: string, el: HTMLInputElement) => {
    const parts = raw.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean)
    if (!parts.length) return
    const next = Array.from(new Set([...value, ...parts]))
    onChange(max ? next.slice(0, max) : next)
    el.value = ''
  }
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {value.map((t) => (
        <button key={t} type="button" aria-label={`移除 ${t}`} onClick={() => onChange(value.filter((x) => x !== t))}
          className="focus-ring inline-flex h-10 max-w-full items-center gap-1 rounded-md bg-muted px-2.5 text-[13px] hover:bg-danger-soft hover:text-danger">
          <span className="truncate">{t}</span><X className="h-3 w-3 shrink-0 opacity-60" />
        </button>
      ))}
      {(!max || value.length < max) && (
        <input placeholder={placeholder}
          className="h-10 min-w-[120px] flex-1 rounded-md border border-input bg-surface px-2.5 text-[13px] outline-none focus:border-primary/60"
          onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) { e.preventDefault(); add(e.currentTarget.value, e.currentTarget) } }}
          onChange={(e) => { if (/[,，]/.test(e.target.value)) add(e.target.value, e.target) }}
          onBlur={(e) => add(e.target.value, e.target)} />
      )}
    </div>
  )
}
