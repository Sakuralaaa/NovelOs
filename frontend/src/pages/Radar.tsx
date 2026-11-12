import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowDown, ArrowUp, LayoutGrid, Lightbulb, RefreshCw, Rows3 } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Tip } from '@/components/ui/tooltip'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Gender, RankItem, TrendTopic } from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

const PAGE = 50
const SOURCE: Record<string, string> = { web: '番茄阅读榜', app: '番茄 App 榜', mock: '示例数据' }

export default function RadarPage() {
  const [gender, setGender] = useState<Gender>('male')
  const [category, setCategory] = useState<string>('')
  const [view, setView] = useState<'table' | 'grid'>('table')
  const [limit, setLimit] = useState(PAGE)
  const nav = useNavigate()
  const qc = useQueryClient()
  const { start } = useJobs()
  const job = useActiveJob('radar-refresh')

  const latest = useQuery({ queryKey: qk.radarLatest(gender), queryFn: () => api.radarLatest({ gender }) })
  const trends = useQuery({ queryKey: qk.radarTrends(gender), queryFn: () => api.radarTrends(gender) })
  const cfg = useQuery({ queryKey: qk.radarConfig, queryFn: api.radarConfig })
  const enable = useMutation({
    mutationFn: () => api.saveRadarConfig({ ...(cfg.data ?? { daily_hour: 8 }), enabled: true }),
    onSuccess: (d) => { qc.setQueryData(qk.radarConfig, d); refresh() },
  })

  useEffect(() => setLimit(PAGE), [gender, category])

  const items = latest.data?.items ?? []
  const cats = useMemo(() => {
    const m = new Map<string, number>()
    items.forEach((i) => m.set(i.category, (m.get(i.category) ?? 0) + 1))
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [items])
  const filtered = category ? items.filter((i) => i.category === category) : items
  const shown = filtered.slice(0, limit)
  const snap = latest.data?.snapshot
  const isMock = !snap || snap.source === 'mock'

  const refresh = () => start(api.radarRefresh(), {
    key: 'radar-refresh', label: '刷新榜单',
    successMsg: (j) => (j.result?.unchanged ? '榜单今天还没更新' : j.result?.source === 'mock' ? '已生成示例数据' : '榜单已更新'),
  })
  const toIdeas = (genre: string, g: Gender = gender) => nav(`/ideas?genre=${encodeURIComponent(genre)}&gender=${g}&from_trends=1`)

  return (
    <div className="page">
      <PageHeader
        title="热点雷达"
        actions={
          <>
            {snap && (
              <span className="mr-1 flex items-center gap-2 text-[13px] text-muted-foreground">
                <Badge tone={isMock ? 'warning' : 'success'} dot>{SOURCE[snap.source] ?? snap.source}</Badge>
                <span className="num">{fmtDateTime(snap.taken_at)}</span>
              </span>
            )}
            <Button variant="primary" loading={!!job} icon={<RefreshCw className="h-4 w-4" />} onClick={refresh}>{job ? '刷新中' : '刷新榜单'}</Button>
          </>
        }
      />

      {job && <JobInline job={job} className="mb-5" />}

      {isMock && cfg.data && !cfg.data.enabled && !latest.isLoading && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-warning/25 bg-warning-soft px-4 py-3">
          <span className="text-[13.5px] font-medium text-warning">当前是示例数据，开启雷达后获取番茄真实阅读榜</span>
          <Button size="sm" variant="primary" loading={enable.isPending || !!job} onClick={() => enable.mutate(undefined, { onError: (e: any) => toast.error('开启失败', { description: e?.message }) })}>开启并刷新</Button>
        </div>
      )}

      <div className="mb-6 flex items-center justify-between gap-3">
        <Segmented value={gender} onChange={(g) => { setGender(g); setCategory('') }} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
      </div>

      <TrendSection data={trends.data} loading={trends.isLoading} error={trends.error} onRetry={trends.refetch} onPick={(t) => toIdeas(t.category)} activeCat={category} onFilter={(c) => setCategory((x) => (x === c ? '' : c))} />

      <Card className="mt-6 overflow-hidden">
        <CardHeader
          divider
          title={category || '全部题材'}
          action={<Segmented size="sm" value={view} onChange={setView} options={[{ value: 'table', label: <Rows3 className="h-3.5 w-3.5" /> }, { value: 'grid', label: <LayoutGrid className="h-3.5 w-3.5" /> }]} />}
        />
        <div className="flex flex-wrap gap-1.5 border-b px-5 py-3">
          <Chip active={!category} onClick={() => setCategory('')}>全部<span className="num opacity-55">{items.length}</span></Chip>
          {cats.map(([c, n]) => <Chip key={c} active={category === c} onClick={() => setCategory(c)}>{c}<span className="num opacity-55">{n}</span></Chip>)}
        </div>

        {latest.isLoading ? (
          <div className="space-y-2 p-5">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-11" />)}</div>
        ) : latest.error ? (
          <ErrorState className="m-5" error={latest.error} onRetry={() => latest.refetch()} />
        ) : !shown.length ? (
          <EmptyState className="m-5 border-0" kind="radar" title="还没有榜单数据" action={<Button variant="primary" loading={!!job} onClick={refresh}>刷新榜单</Button>} />
        ) : view === 'table' ? (
          <RankTable items={shown} byBoard={!!category} onIdea={(i) => toIdeas(i.category, i.gender)} />
        ) : (
          <div className="grid gap-4 p-5 sm:grid-cols-2 xl:grid-cols-3">
            {shown.map((i, k) => <RankCard key={`${i.category}-${i.book_id_ext}`} item={i} n={category ? i.rank : k + 1} onIdea={() => toIdeas(i.category, i.gender)} />)}
          </div>
        )}
        {filtered.length > shown.length && (
          <div className="border-t p-3 text-center">
            <Button variant="ghost" size="sm" onClick={() => setLimit((l) => l + PAGE)}>显示更多（{filtered.length - shown.length}）</Button>
          </div>
        )}
      </Card>

    </div>
  )
}

function Chip({ active, children, onClick }: { active?: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-[13px] transition', active ? 'bg-foreground text-background' : 'bg-muted/70 text-foreground/75 hover:bg-muted hover:text-foreground')}>
      {children}
    </button>
  )
}

function Diff({ v }: { v?: number }) {
  if (!v) return <span className="text-muted-foreground/50">–</span>
  return v > 0
    ? <span className="num inline-flex items-center gap-0.5 text-danger"><ArrowUp className="h-3 w-3" strokeWidth={2.5} />{v}</span>
    : <span className="num inline-flex items-center gap-0.5 text-success"><ArrowDown className="h-3 w-3" strokeWidth={2.5} />{-v}</span>
}

function TrendSection({ data, loading, error, onRetry, onPick, onFilter, activeCat }: {
  data?: TrendTopic[]; loading: boolean; error: unknown; onRetry: () => void; onPick: (t: TrendTopic) => void; onFilter: (c: string) => void; activeCat: string
}) {
  const top = (data ?? []).slice(0, 10)
  const max = Math.max(1, ...top.map((t) => t.heat))
  const [sel, setSel] = useState(0)
  const cur = top[Math.min(sel, top.length - 1)]
  return (
    <Card>
      <CardHeader divider title="题材热度" />
      <div className="p-5">
        {loading ? (
          <div className="grid gap-6 md:grid-cols-[1fr_300px]"><Skeleton className="h-[340px]" /><Skeleton className="h-[340px]" /></div>
        ) : error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : !top.length ? (
          <div className="flex h-[200px] items-center justify-center text-sm text-muted-foreground">暂无数据</div>
        ) : (
          <div className="grid gap-6 md:grid-cols-[1fr_300px]">
            <div className="flex flex-col justify-between gap-1">
              {top.map((t, i) => (
                <button key={t.category} onMouseEnter={() => setSel(i)} onFocus={() => setSel(i)} onClick={() => onFilter(t.category)}
                  className={cn('flex h-[34px] w-full items-center gap-3 rounded-lg px-2.5 text-left transition', sel === i ? 'bg-subtle' : 'hover:bg-subtle', activeCat === t.category && 'ring-1 ring-inset ring-primary/40')}>
                  <span className="num w-5 shrink-0 text-right text-[12px] text-muted-foreground">{i + 1}</span>
                  <span className="w-[76px] shrink-0 truncate text-[13.5px] font-medium">{t.category}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${(t.heat / max) * 100}%` }} transition={{ duration: 0.6, delay: i * 0.03, ease: [0.2, 0.8, 0.2, 1] }}
                      className="h-full rounded-full bg-primary" style={{ opacity: 0.45 + (1 - i / 10) * 0.55 }} />
                  </div>
                  <span className="num w-12 shrink-0 text-right text-[12.5px] font-medium">{fmtNum(Math.round(t.heat))}</span>
                  <span className="flex w-9 shrink-0 justify-end text-[12px]"><Diff v={t.rising} /></span>
                </button>
              ))}
            </div>
            {cur && (
              <div className="flex flex-col rounded-xl border bg-subtle/50 p-5">
                <div className="flex items-center justify-between gap-2">
                  <div className="truncate text-[17px] font-semibold">{cur.category}</div>
                  {cur.rising > 0 && <Badge tone="danger">{cur.rising} 本上升</Badge>}
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3">
                  <div className="rounded-lg border bg-surface px-3 py-2.5"><div className="text-[12px] text-muted-foreground">热度</div><div className="num mt-0.5 text-[18px] font-semibold">{fmtNum(Math.round(cur.heat))}</div></div>
                  <div className="rounded-lg border bg-surface px-3 py-2.5"><div className="text-[12px] text-muted-foreground">上榜</div><div className="num mt-0.5 text-[18px] font-semibold">{cur.books}</div></div>
                </div>
                <ul className="mt-4 flex-1 space-y-2">
                  {cur.sample_titles.slice(0, 3).map((s, k) => (
                    <li key={s} className="flex items-center gap-2 text-[13px]"><span className="num w-4 shrink-0 text-muted-foreground">{k + 1}</span><span className="truncate">{s}</span></li>
                  ))}
                </ul>
                <Button className="mt-5 w-full" variant="primary" icon={<Lightbulb className="h-4 w-4" />} onClick={() => onPick(cur)}>用这个题材出选题</Button>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

function RankTable({ items, byBoard, onIdea }: { items: RankItem[]; byBoard: boolean; onIdea: (i: RankItem) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[780px] text-[13.5px]">
        <thead>
          <tr className="border-b bg-subtle/40 text-left text-[12px] text-muted-foreground">
            <th className="h-10 w-16 pl-5 font-medium">排名</th>
            <th className="h-10 font-medium">书名</th>
            <th className="h-10 w-[150px] font-medium">作者</th>
            <th className="h-10 w-[110px] font-medium">题材</th>
            <th className="h-10 w-[96px] text-right font-medium">在读</th>
            <th className="h-10 w-[96px] text-right font-medium">字数</th>
            <th className="h-10 w-[64px] text-right font-medium">变化</th>
            <th className="h-10 w-[96px] pr-5" />
          </tr>
        </thead>
        <tbody>
          {items.map((i, k) => (
            <tr key={`${i.category}-${i.book_id_ext}`} className="group h-[52px] border-b border-border/60 last:border-0 hover:bg-subtle/60">
              <td className="pl-5"><RankNo n={byBoard ? i.rank : k + 1} /></td>
              <td className="max-w-0 pr-4">
                <Tip content={i.abstract || null}><span className="block truncate font-medium">{i.title}</span></Tip>
              </td>
              <td className="max-w-[150px] truncate pr-3 text-muted-foreground">{i.author}</td>
              <td><Badge>{i.category}</Badge></td>
              <td className="num text-right">{fmtNum(i.read_count)}</td>
              <td className="num text-right text-muted-foreground">{fmtNum(i.word_count)}</td>
              <td className="text-right text-[12.5px]"><Diff v={i.rank_diff} /></td>
              <td className="pr-5 text-right">
                <Button size="xs" variant="soft" className="opacity-0 transition group-hover:opacity-100 focus:opacity-100" onClick={() => onIdea(i)}>出选题</Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RankNo({ n }: { n: number }) {
  const top = n <= 3
  return (
    <span className={cn('num inline-flex h-6 min-w-6 items-center justify-center rounded-md px-1 text-[12px] font-semibold', top ? 'text-white' : 'text-muted-foreground')}
      style={top ? { background: ['#9b3a2c', '#5e5a52', '#8a5a2b'][n - 1] } : undefined}>
      {n}
    </span>
  )
}

function RankCard({ item: i, n, onIdea }: { item: RankItem; n: number; onIdea: () => void }) {
  return (
    <div className="card-hover group flex h-[176px] flex-col rounded-xl border bg-surface p-4">
      <div className="flex items-start gap-3">
        <RankNo n={n} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14.5px] font-semibold">{i.title}</div>
          <div className="mt-1 truncate text-[12.5px] text-muted-foreground">{i.author} · {i.category}</div>
        </div>
        <span className="text-[12px]"><Diff v={i.rank_diff} /></span>
      </div>
      <p className="mt-3 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">{i.abstract}</p>
      <div className="mt-auto flex items-center justify-between pt-3 text-[12.5px] text-muted-foreground">
        <span className="num">在读 {fmtNum(i.read_count)} · {fmtNum(i.word_count)} 字</span>
        <Button size="xs" variant="soft" onClick={onIdea}>出选题</Button>
      </div>
    </div>
  )
}
