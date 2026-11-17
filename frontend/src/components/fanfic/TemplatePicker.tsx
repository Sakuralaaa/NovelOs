import { useMemo, useState } from 'react'
import { Check, Search } from '@/components/icons'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import type { FanficTemplate, FanficTemplateCategory } from '@/lib/types'
import { cn } from '@/lib/utils'

const norm = (s: string) => s.replace(/[\s·・:：]/g, '').toLowerCase()

/** v0.11.1 热门同人题材模板：可搜索的一排卡片（横向滚动，窄容器/390 宽也不挤） */
export function TemplatePicker({ templates, categories, loading, selected, onPick }: {
  templates: FanficTemplate[]; categories: FanficTemplateCategory[]; loading?: boolean
  selected?: string | null; onPick: (t: FanficTemplate) => void
}) {
  const [kw, setKw] = useState('')
  const [cat, setCat] = useState<FanficTemplateCategory | ''>('')
  const list = useMemo(() => {
    const k = norm(kw)
    return templates.filter((t) => (!cat || t.category === cat)
      && (!k || [t.title, ...t.aliases, ...t.characters].some((x) => norm(x).includes(k))))
  }, [templates, kw, cat])
  return (
    <div className="min-w-0 space-y-2" data-testid="fanfic-templates">
      <div className="flex min-w-0 items-baseline gap-2">
        <h3 className="shrink-0 text-[13px] font-semibold">热门同人题材</h3>
        <span className="min-w-0 truncate text-[11.5px] text-muted-foreground">点一下自动填作品名和重点人物</span>
      </div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜作品名 / 别名 / 人物" className="h-10 pl-8" aria-label="搜索热门同人题材" />
      </div>
      <div className="-mx-3 flex gap-1.5 overflow-x-auto px-3 [scrollbar-width:none] sm:-mx-4 sm:px-4">
        {(['', ...categories] as const).map((c) => (
          <button key={c || 'all'} type="button" onClick={() => setCat(c)} aria-pressed={cat === c}
            className={cn('focus-ring inline-flex h-9 shrink-0 items-center whitespace-nowrap rounded-full px-3 text-[12.5px] transition',
              cat === c ? 'bg-foreground text-background' : 'bg-muted/70 text-foreground/75 hover:bg-muted')}>{c || '全部'}</button>
        ))}
      </div>
      {loading ? (
        <div className="flex gap-2 overflow-hidden">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-[92px] w-[148px] shrink-0 rounded-xl" />)}</div>
      ) : !list.length ? (
        <p className="rounded-xl border border-dashed px-3 py-4 text-center text-[12.5px] text-muted-foreground">没有匹配的模板，直接在下面填作品名也可以联网取材</p>
      ) : (
        <div className="-mx-3 flex snap-x gap-2 overflow-x-auto px-3 pb-1.5 sm:-mx-4 sm:px-4">
          {list.map((t) => {
            const on = selected === t.id
            return (
              <button key={t.id} type="button" onClick={() => onPick(t)} aria-pressed={on} title={t.intro}
                className={cn('focus-ring flex min-h-[92px] w-[148px] shrink-0 snap-start flex-col rounded-xl border bg-surface p-2.5 text-left transition',
                  on ? 'border-primary bg-primary-soft/40 ring-1 ring-primary/30' : 'hover:border-foreground/20')}>
                <span className="flex min-w-0 items-center gap-1">
                  <span className={cn('min-w-0 flex-1 truncate text-[13.5px] font-semibold', on && 'text-primary')}>{t.title}</span>
                  {on ? <Check className="h-3.5 w-3.5 shrink-0 text-primary" /> : (
                    <span className="shrink-0 whitespace-nowrap rounded bg-muted px-1 text-[10.5px] leading-[16px] text-muted-foreground">{t.category}</span>
                  )}
                </span>
                <span className="mt-1 line-clamp-2 text-[11.5px] leading-snug text-muted-foreground">{t.intro}</span>
                <span className="mt-auto truncate pt-1 text-[11px] text-foreground/60">{t.characters.slice(0, 3).join('、')}</span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
