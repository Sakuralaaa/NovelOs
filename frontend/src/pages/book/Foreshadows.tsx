import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowRight, CircleDot, Flag, Search, Sprout, Trash } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import type { Foreshadow } from '@/lib/types'
import { cn } from '@/lib/utils'

const COLS: { key: Foreshadow['status']; label: string; desc: string; icon: typeof Sprout; accent: string; bg: string }[] = [
  { key: 'planted', label: '埋设', desc: '已经埋下，等待推进', icon: Sprout, accent: 'text-primary', bg: 'bg-primary' },
  { key: 'advancing', label: '推进', desc: '被再次提及，逐步升温', icon: ArrowRight, accent: 'text-warning', bg: 'bg-warning' },
  { key: 'resolved', label: '回收', desc: '已在正文中揭晓', icon: Flag, accent: 'text-success', bg: 'bg-success' },
  { key: 'dropped', label: '放弃', desc: '不再使用的线索', icon: Trash, accent: 'text-muted-foreground', bg: 'bg-muted-foreground' },
]

export default function Foreshadows() {
  const id = useBookId()
  const q = useQuery({ queryKey: qk.foreshadows(id), queryFn: () => api.foreshadows(id) })
  const chs = useQuery({ queryKey: qk.chapters(id), queryFn: () => api.chapters(id) })
  const [kw, setKw] = useState('')
  const list = useMemo(() => (q.data ?? []).filter((f) => !kw || f.desc.includes(kw)), [q.data, kw])
  const latestCh = Math.max(0, ...(chs.data ?? []).map((c) => c.number))
  const chId = (n: number) => chs.data?.find((c) => c.number === n)?.id

  return (
    <div className="page max-w-[1320px]">
      <BookCrumb bookId={id} page="伏笔" />
      <PageHeader className="mt-3" title="伏笔" desc="写作时自动登记的伏笔池。埋下太久没推进的线索会被标红，提醒你别忘了回收。"
        actions={<div className="relative w-56"><Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜索伏笔" className="pl-8" /></div>} />
      {q.isLoading ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">{COLS.map((c) => <Skeleton key={c.key} className="h-80 rounded-xl" />)}</div>
        : q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : !q.data?.length ? <EmptyState kind="foreshadow" title="还没有伏笔" desc="开始写正文后，每章的变更声明里提到的伏笔会自动出现在这里。" action={<Link to={`/books/${id}/chapters`} className="text-sm font-medium text-primary hover:underline">去写正文 →</Link>} />
        : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            {COLS.map((col) => {
              const items = list.filter((f) => f.status === col.key)
              return (
                <div key={col.key} className="flex flex-col rounded-xl bg-subtle/70 p-2.5 hairline">
                  <div className="flex items-center justify-between px-1.5 pb-2.5 pt-1">
                    <div className="flex items-center gap-2"><span className={cn('h-2 w-2 rounded-full', col.bg)} /><span className="text-[14px] font-semibold">{col.label}</span><span className="num rounded-full bg-surface px-1.5 text-xs text-muted-foreground hairline">{items.length}</span></div>
                    <col.icon className={cn('h-4 w-4', col.accent)} />
                  </div>
                  <p className="px-1.5 pb-2 text-[11.5px] text-muted-foreground">{col.desc}</p>
                  <div className="flex-1 space-y-2">
                    {items.map((f, i) => {
                      const stale = (f.status === 'planted' || f.status === 'advancing') && latestCh - f.last_ch >= 20
                      return (
                        <motion.div key={f.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }}
                          className={cn('rounded-lg bg-surface p-3 shadow-card hairline', f.status === 'dropped' && 'opacity-60', stale && 'ring-1 ring-danger/40')}>
                          <p className={cn('text-[13.5px] leading-relaxed', f.status === 'dropped' && 'line-through')}>{f.desc}</p>
                          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11.5px]">
                            <ChTag n={f.planted_ch} label="埋" to={chId(f.planted_ch) ? `/books/${id}/chapters/${chId(f.planted_ch)}` : undefined} />
                            {f.last_ch !== f.planted_ch && <ChTag n={f.last_ch} label="最近" to={chId(f.last_ch) ? `/books/${id}/chapters/${chId(f.last_ch)}` : undefined} />}
                            {f.resolved_ch && <ChTag n={f.resolved_ch} label="收" tone="success" to={chId(f.resolved_ch) ? `/books/${id}/chapters/${chId(f.resolved_ch)}` : undefined} />}
                            {stale && <span className="rounded bg-danger-soft px-1.5 py-0.5 text-danger">{latestCh - f.last_ch} 章未推进</span>}
                          </div>
                        </motion.div>
                      )
                    })}
                    {!items.length && <div className="flex h-20 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground/70"><CircleDot className="mr-1 h-3.5 w-3.5" />暂无</div>}
                  </div>
                </div>
              )
            })}
          </div>
        )}
    </div>
  )
}

function ChTag({ n, label, to, tone }: { n: number; label: string; to?: string; tone?: 'success' }) {
  const cls = cn('num inline-flex items-center gap-0.5 rounded px-1.5 py-0.5', tone === 'success' ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground', to && 'hover:text-foreground')
  const body = <>{label} 第{n}章</>
  return to ? <Link to={to} className={cls}>{body}</Link> : <span className={cls}>{body}</span>
}
