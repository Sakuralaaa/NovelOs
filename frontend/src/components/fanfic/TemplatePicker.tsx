import { useMemo, useState } from 'react'
import { Check, Search } from '@/components/icons'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import type { FanficTemplate, FanficTemplateCategory } from '@/lib/types'
import { cn } from '@/lib/utils'

const norm = (s: string) => s.replace(/[\s·・:：]/g, '').toLowerCase()

const COLLAPSED = 10

/** v0.11.1 热门同人题材模板；v0.11.2 改为全宽自适应网格（auto-fill），类别筛选换行排，不再横向滚动 */
export function TemplatePicker({ templates, categories, loading, selected, onPick }: {
  templates: FanficTemplate[]; categories: FanficTemplateCategory[]; loading?: boolean
  selected?: string | null; onPick: (t: FanficTemplate) => void
}) {
  const [kw, setKw] = useState('')
  const [cat, setCat] = useState<FanficTemplateCategory | ''>('')
  const [all, setAll] = useState(false)
  const list = useMemo(() => {
    const k = norm(kw)
    return templates.filter((t) => (!cat || t.category === cat)
      && (!k || [t.title, ...t.aliases, ...t.characters].some((x) => norm(x).includes(k))))
  }, [templates, kw, cat])
  const filtered = !!kw.trim() || !!cat
  const shown = useMemo(() => {
    if (all || filtered || list.length <= COLLAPSED + 2) return list
    const head = list.slice(0, COLLAPSED)
    const sel = selected ? list.find((t) => t.id === selected) : undefined
    return sel && !head.includes(sel) ? [...head.slice(0, COLLAPSED - 1), sel] : head
  }, [list, all, filtered, selected])
  const count = (c: FanficTemplateCategory | '') => (c ? templates.filter((t) => t.category === c).length : templates.length)
  return (
    <div className="min-w-0 space-y-3" data-testid="fanfic-templates">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <div className="min-w-0 flex-1 basis-[220px]">
          <h3 className="text-[13.5px] font-semibold">热门同人题材</h3>
          <p className="truncate text-[12px] text-muted-foreground">点一下自动填作品名和重点人物，也可以直接在下面手填任意作品名</p>
        </div>
        <div className="relative w-full sm:w-[260px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜作品名 / 别名 / 人物" className="h-10 pl-8" aria-label="搜索热门同人题材" />
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {(['', ...categories] as const).map((c) => (
          <button key={c || 'all'} type="button" onClick={() => setCat(c)} aria-pressed={cat === c}
            className={cn('focus-ring inline-flex h-8 shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-3 text-[12.5px] transition',
              cat === c ? 'bg-foreground text-background' : 'bg-muted/70 text-foreground/75 hover:bg-muted')}>
            {c || '全部'}{!loading && <span className="num opacity-55">{count(c)}</span>}
          </button>
        ))}
      </div>
      {loading ? (
        <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,190px),1fr))] max-sm:grid-cols-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)}</div>
      ) : !list.length ? (
        <p className="rounded-xl border border-dashed px-3 py-4 text-center text-[12.5px] text-muted-foreground">没有匹配的模板，直接在下面填作品名也可以联网取材</p>
      ) : (
        <>
          <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,190px),1fr))] max-sm:grid-cols-2">
            {shown.map((t) => {
              const on = selected === t.id
              return (
                <button key={t.id} type="button" onClick={() => onPick(t)} aria-pressed={on} title={t.intro}
                  className={cn('focus-ring flex min-h-[92px] min-w-0 flex-col rounded-xl border bg-surface p-2.5 text-left transition',
                    on ? 'border-primary bg-primary-soft/40 ring-1 ring-primary/30' : 'hover:border-foreground/20 hover:shadow-card')}>
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
          {!filtered && list.length > COLLAPSED + 2 && (
            <div className="text-center">
              <button type="button" onClick={() => setAll((x) => !x)} className="focus-ring inline-flex h-9 items-center rounded-md px-3 text-[13px] text-primary hover:bg-primary-soft/60">
                {all ? '收起' : `展开全部 ${list.length} 个题材`}
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
