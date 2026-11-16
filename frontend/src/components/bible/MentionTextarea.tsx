import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState, type TextareaHTMLAttributes } from 'react'
import { useQuery } from '@tanstack/react-query'
import { At, Loader2 } from '@/components/icons'
import { api, qk } from '@/lib/api'
import type { RefEntry } from '@/lib/types'
import { cn } from '@/lib/utils'

/** 光标前的「@xxx」：@ 前面是开头/空白/标点，xxx 不含空白，最多 16 字 */
function mentionAt(text: string, caret: number): { start: number; q: string } | null {
  const before = text.slice(0, caret)
  const m = /(^|[\s，。、；：！？,.;:!?（）()“”"'「」【】])@([^\s@，。、；：！？,.;:!?]{0,16})$/.exec(before)
  if (!m) return null
  return { start: caret - m[2].length - 1, q: m[2] }
}

export interface MentionHandle { focus: () => void; insertAt: () => void; el: HTMLTextAreaElement | null }

type Props = Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'value' | 'onChange'> & {
  bookId: number
  value: string
  onChange: (v: string) => void
  /** 候选列表出现在输入框上方（输入框贴底时用） */
  placement?: 'top' | 'bottom'
  wrapperClassName?: string
}

/**
 * 支持「@ 引用设定」的多行输入框：输入 @ 弹出条目补全（GET /books/{id}/refs?q=），
 * ↑↓ 选择、Enter/Tab 插入、Esc 关闭；触屏点选。插入后形如「@林野 」，生成时后端把条目内容注入提示词。
 */
export const MentionTextarea = forwardRef<MentionHandle, Props>(function MentionTextarea(
  { bookId, value, onChange, placement = 'bottom', wrapperClassName, className, onKeyDown, onBlur, ...rest }, ref,
) {
  const ta = useRef<HTMLTextAreaElement>(null)
  const [m, setM] = useState<{ start: number; q: string } | null>(null)
  const [active, setActive] = useState(0)
  const [q, setQ] = useState('')
  // 轻微去抖，中文输入法连续上屏时少打几次接口
  useEffect(() => { const t = setTimeout(() => setQ(m?.q ?? ''), 120); return () => clearTimeout(t) }, [m?.q])
  const refs = useQuery({ queryKey: qk.refs(bookId, q), queryFn: () => api.refs(bookId, q, 12), enabled: !!m && !!bookId, staleTime: 15_000 })
  const items: RefEntry[] = useMemo(() => refs.data ?? [], [refs.data])
  useEffect(() => setActive(0), [q])

  const sync = (el: HTMLTextAreaElement) => setM(mentionAt(el.value, el.selectionStart ?? el.value.length))
  const pick = (r: RefEntry) => {
    const el = ta.current
    if (!el || !m) return
    const caret = el.selectionStart ?? value.length
    const next = `${value.slice(0, m.start)}@${r.name} ${value.slice(caret)}`
    onChange(next)
    setM(null)
    const pos = m.start + r.name.length + 2
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(pos, pos) })
  }
  useImperativeHandle(ref, () => ({
    el: ta.current,
    focus: () => ta.current?.focus(),
    /** 「@」按钮：在光标处插入 @ 并打开候选（触屏上不方便打 @） */
    insertAt: () => {
      const el = ta.current
      if (!el) return
      const caret = el.selectionStart ?? value.length
      const needSpace = caret > 0 && !/\s/.test(value[caret - 1] ?? '')
      const ins = `${needSpace ? ' ' : ''}@`
      const next = value.slice(0, caret) + ins + value.slice(caret)
      onChange(next)
      const pos = caret + ins.length
      requestAnimationFrame(() => { el.focus(); el.setSelectionRange(pos, pos); setM({ start: pos - 1, q: '' }) })
    },
  }), [value, onChange])

  const open = !!m
  return (
    <div className={cn('relative', wrapperClassName)}>
      <textarea
        ref={ta}
        value={value}
        className={className}
        {...rest}
        aria-autocomplete="list"
        aria-expanded={open}
        onChange={(e) => { onChange(e.target.value); sync(e.target) }}
        onClick={(e) => sync(e.currentTarget)}
        onKeyUp={(e) => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) sync(e.currentTarget) }}
        onBlur={(e) => { setTimeout(() => setM(null), 150); onBlur?.(e) }}
        onKeyDown={(e) => {
          if (open && !e.nativeEvent.isComposing) {
            if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setM(null); return }
            if (items.length) {
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => (a + 1) % items.length); return }
              if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => (a - 1 + items.length) % items.length); return }
              if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); pick(items[Math.min(active, items.length - 1)]); return }
            }
          }
          onKeyDown?.(e)
        }}
      />
      {open && (
        <div role="listbox" aria-label="引用设定"
          className={cn('absolute left-0 right-0 z-30 max-h-[264px] overflow-y-auto rounded-xl bg-popover p-1.5 shadow-pop hairline animate-fade-in',
            placement === 'top' ? 'bottom-full mb-1.5' : 'top-full mt-1.5')}
          onMouseDown={(e) => e.preventDefault()}>
          <div className="flex items-center gap-1.5 px-2 pb-1 pt-0.5 text-[11.5px] text-muted-foreground">
            <At className="h-3.5 w-3.5" />引用设定{m.q && <>：包含「{m.q}」</>}
            {refs.isFetching && <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin" />}
          </div>
          {!items.length ? (
            <p className="px-2.5 py-3 text-[12.5px] text-muted-foreground">{refs.isLoading ? '加载中…' : m.q ? '没有匹配的条目（已弃用或关掉了「用于 @引用」的不会出现）' : '设定库里还没有可引用的条目'}</p>
          ) : items.map((r, i) => (
            <button key={r.id} type="button" role="option" aria-selected={i === active} onClick={() => pick(r)} onMouseEnter={() => setActive(i)}
              className={cn('flex min-h-[40px] w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left transition-colors', i === active ? 'bg-primary-soft text-foreground' : 'hover:bg-subtle')}>
              <span className="shrink-0 rounded bg-muted px-1.5 text-[11px] leading-[18px] text-muted-foreground">{r.type_label || r.type}</span>
              <span className="shrink-0 text-[13.5px] font-medium">{r.name}</span>
              {r.brief && <span className="min-w-0 flex-1 truncate text-[12px] text-muted-foreground">{r.brief}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
})

/** 输入框旁的「@」按钮 */
export function AtButton({ onClick, className }: { onClick: () => void; className?: string }) {
  return (
    <button type="button" onClick={onClick} onMouseDown={(e) => e.preventDefault()} title="@ 引用设定" aria-label="@ 引用设定"
      className={cn('focus-ring inline-flex h-10 min-w-10 items-center justify-center gap-1 rounded-lg px-2 text-[12.5px] text-muted-foreground transition hover:bg-primary-soft hover:text-primary', className)}>
      <At className="h-4 w-4" />
    </button>
  )
}
