import { forwardRef, useImperativeHandle, useLayoutEffect, useMemo, useRef } from 'react'
import { cn } from '@/lib/utils'

export interface Range { start: number; end: number; kind: 'focus' | 'bare' | 'summary' }
export interface EditorHandle { reveal: (start: number, end: number) => void; focus: () => void; getSelection: () => { start: number; end: number } }

const MARK: Record<Range['kind'], string> = {
  focus: 'rounded-sm bg-warning/40 animate-flash',
  bare: 'rounded-sm bg-amber-400/25 shadow-[inset_0_-2px_0_0_rgb(245_158_11/0.7)]',
  summary: 'rounded-sm bg-sky-400/20 shadow-[inset_0_-2px_0_0_rgb(14_165_233/0.6)]',
}

/**
 * 长文编辑器：原生 textarea（中文输入法与长文最稳）+ 背景镜像层做高亮。
 * textarea 自动增高，由外层容器滚动，镜像层与之逐字对齐。
 */
export const HighlightEditor = forwardRef<EditorHandle, {
  value: string; onChange: (v: string) => void; ranges: Range[]; readOnly?: boolean; serif?: boolean; scroller: React.RefObject<HTMLDivElement>; placeholder?: string
}>(function HighlightEditor({ value, onChange, ranges, readOnly, serif, scroller, placeholder }, ref) {
  const ta = useRef<HTMLTextAreaElement>(null)
  const mirror = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = ta.current
    if (!el) return
    const top = scroller.current?.scrollTop
    el.style.height = '0px'
    el.style.height = `${el.scrollHeight}px`
    if (scroller.current && top !== undefined) scroller.current.scrollTop = top
  }, [value, serif, scroller])

  useLayoutEffect(() => {
    const el = ta.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => { el.style.height = '0px'; el.style.height = `${el.scrollHeight}px` })
    ro.observe(el.parentElement!)
    return () => ro.disconnect()
  }, [])

  useImperativeHandle(ref, () => ({
    focus: () => ta.current?.focus(),
    getSelection: () => ({ start: ta.current?.selectionStart ?? 0, end: ta.current?.selectionEnd ?? 0 }),
    reveal: (start, end) => {
      const el = ta.current, sc = scroller.current
      if (!el || !sc) return
      // 等镜像层渲染出 focus 标记后再滚动
      requestAnimationFrame(() => {
        const mk = mirror.current?.querySelector('[data-focus]') as HTMLElement | null
        if (mk) {
          const r = mk.getBoundingClientRect(), sr = sc.getBoundingClientRect()
          sc.scrollTo({ top: sc.scrollTop + r.top - sr.top - sr.height / 3, behavior: 'smooth' })
        }
        el.focus({ preventScroll: true })
        el.setSelectionRange(start, end)
      })
    },
  }))

  const segs = useMemo(() => {
    if (!ranges.length) return null
    const rs = [...ranges].filter((r) => r.end > r.start).sort((a, b) => a.start - b.start)
    const out: React.ReactNode[] = []
    let pos = 0
    rs.forEach((r, i) => {
      if (r.start < pos) return
      out.push(value.slice(pos, r.start))
      out.push(<mark key={i} data-focus={r.kind === 'focus' ? '' : undefined} className={cn('text-transparent', MARK[r.kind])}>{value.slice(r.start, r.end)}</mark>)
      pos = r.end
    })
    out.push(value.slice(pos))
    out.push('\u200b')
    return out
  }, [value, ranges])

  const font = cn('prose-zh whitespace-pre-wrap break-words text-[17px] tracking-[0.015em]', serif ? 'font-serif' : 'font-sans')
  return (
    <div className="relative">
      {segs && <div ref={mirror} aria-hidden className={cn(font, 'pointer-events-none absolute inset-0 select-none text-transparent')}>{segs}</div>}
      <textarea
        ref={ta}
        value={value}
        readOnly={readOnly}
        spellCheck={false}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={cn(font, 'relative block w-full resize-none overflow-hidden bg-transparent p-0 text-foreground caret-primary outline-none placeholder:text-muted-foreground/60', readOnly && 'cursor-default text-foreground/85')}
        style={{ minHeight: 320 }}
      />
    </div>
  )
})
