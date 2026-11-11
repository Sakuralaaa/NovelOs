import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Flame, LayoutGrid, Lightbulb, RefreshCw, Rows3, ShieldCheck, TrendingUp } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Tip } from '@/components/ui/tooltip'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Gender, RankItem, TrendTopic } from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

const SOURCE: Record<string, string> = { app: '番茄 App 榜单', web: '番茄 Web 榜单', mock: '示例数据' }

export default function RadarPage() {
  const [gender, setGender] = useState<Gender>('male')
  const [category, setCategory] = useState<string>('')
  const [view, setView] = useState<'table' | 'grid'>('table')
  const nav = useNavigate()
  const { start } = useJobs()
  const job = useActiveJob('radar-refresh')

  const latest = useQuery({ queryKey: qk.radarLatest(gender), queryFn: () => api.radarLatest({ gender }) })
  const trends = useQuery({ queryKey: qk.radarTrends, queryFn: api.radarTrends })

  const items = latest.data?.items ?? []
  const cats = useMemo(() => {
    const m = new Map<string, number>()
    items.forEach((i) => m.set(i.category, (m.get(i.category) ?? 0) + 1))
    return [...m.entries()].sort((a, b) => b[1] - a[1])
  }, [items])
  const shown = category ? items.filter((i) => i.category === category) : items
  const snap = latest.data?.snapshot

  const toIdeas = (genre: string, g: Gender = gender) => nav(`/ideas?genre=${encodeURIComponent(genre)}&gender=${g}&from_trends=1`)

  return (
    <div className="page">
      <PageHeader
        title="热点雷达"
        desc="每天看一眼番茄榜单：哪些题材在涨、头部书写了什么。挑中题材后一键生成选题。"
        actions={
          <>
            {snap && (
              <div className="mr-1 text-right text-xs leading-relaxed text-muted-foreground">
                <div>上次更新 {fmtDateTime(snap.taken_at)}</div>
                <div>来源：{SOURCE[snap.source] ?? snap.source} · {snap.items_count} 本</div>
              </div>
            )}
            <Button variant="primary" loading={!!job} icon={<RefreshCw className="h-4 w-4" />} onClick={() => start(api.radarRefresh(), { key: 'radar-refresh', label: '刷新热点榜单', successMsg: '榜单已更新' })}>
              {job ? '刷新中' : '刷新榜单'}
            </Button>
          </>
        }
      />

      {job && <JobInline job={job} className="mb-5" />}

      <div className="mb-6 flex items-start gap-2.5 rounded-xl bg-subtle px-4 py-3 text-[12.5px] leading-relaxed text-muted-foreground hairline">
        <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-success" />
        <span>合规提示：雷达只读取番茄<b className="font-medium text-foreground/80">公开榜单</b>的公开字段（书名、分类、在读数等），<b className="font-medium text-foreground/80">每日最多一次</b>，仅用于个人选题参考，不抓取正文。可在「设置」中随时关闭。</span>
      </div>

      <TrendSection data={trends.data} loading={trends.isLoading} error={trends.error} onRetry={trends.refetch} onPick={(t) => toIdeas(t.category)} activeCat={category} onFilter={(c) => setCategory((x) => (x === c ? '' : c))} />

      <Card className="mt-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3.5">
          <div className="flex items-center gap-3">
            <h3 className="text-[15px] font-semibold">榜单</h3>
            <Segmented size="sm" value={gender} onChange={(g) => { setGender(g); setCategory('') }} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
          </div>
          <Segmented size="sm" value={view} onChange={setView} options={[{ value: 'table', label: <><Rows3 className="h-3.5 w-3.5" />列表</> }, { value: 'grid', label: <><LayoutGrid className="h-3.5 w-3.5" />卡片</> }]} />
        </div>
        <div className="flex gap-1.5 overflow-x-auto border-b px-5 py-2.5">
          <Chip active={!category} onClick={() => setCategory('')}>全部 <span className="opacity-60">{items.length}</span></Chip>
          {cats.map(([c, n]) => <Chip key={c} active={category === c} onClick={() => setCategory(c)}>{c} <span className="opacity-60">{n}</span></Chip>)}
        </div>

        {latest.isLoading ? (
          <div className="space-y-2 p-5">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-11" />)}</div>
        ) : latest.error ? (
          <ErrorState className="m-5" error={latest.error} onRetry={() => latest.refetch()} />
        ) : !shown.length ? (
          <EmptyState className="m-5" kind="radar" title="还没有榜单数据" desc="点右上角「刷新榜单」，拉取今天的番茄公开榜单。" action={<Button variant="primary" loading={!!job} onClick={() => start(api.radarRefresh(), { key: 'radar-refresh', label: '刷新热点榜单' })}>刷新榜单</Button>} />
        ) : view === 'table' ? (
          <RankTable items={shown} onIdea={(i) => toIdeas(i.category, i.gender)} />
        ) : (
          <div className="grid gap-3 p-5 sm:grid-cols-2 xl:grid-cols-3">
            {shown.map((i) => <RankCard key={i.book_id_ext} item={i} onIdea={() => toIdeas(i.category, i.gender)} />)}
          </div>
        )}
      </Card>
    </div>
  )
}

function Chip({ active, children, onClick }: { active?: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} className={cn('h-7 shrink-0 whitespace-nowrap rounded-full px-3 text-[12.5px] transition', active ? 'bg-foreground text-background' : 'bg-muted text-foreground/75 hover:text-foreground')}>
      {children}
    </button>
  )
}

function TrendSection({ data, loading, error, onRetry, onPick, onFilter, activeCat }: {
  data?: TrendTopic[]; loading: boolean; error: unknown; onRetry: () => void; onPick: (t: TrendTopic) => void; onFilter: (c: string) => void; activeCat: string
}) {
  const top = (data ?? []).slice(0, 10)
  const max = Math.max(1, ...top.map((t) => t.heat))
  const [sel, setSel] = useState(0)
  const cur = top[sel]
  return (
    <Card>
      <CardHeader title="题材热度" desc="按在读人数与上榜数量综合计算，箭头表示上升中的书数" icon={<Flame className="h-4 w-4 text-warning" />} />
      <CardBody>
        {loading ? (
          <div className="grid gap-6 md:grid-cols-[1fr_280px]"><Skeleton className="h-[220px]" /><Skeleton className="h-[220px]" /></div>
        ) : error ? (
          <ErrorState error={error} onRetry={onRetry} />
        ) : !top.length ? (
          <p className="py-10 text-center text-sm text-muted-foreground">暂无热度数据，刷新榜单后生成。</p>
        ) : (
          <div className="grid gap-6 md:grid-cols-[1fr_290px]">
            <div className="space-y-1.5">
              {top.map((t, i) => (
                <button key={t.category} onMouseEnter={() => setSel(i)} onFocus={() => setSel(i)} onClick={() => onFilter(t.category)}
                  className={cn('group flex w-full items-center gap-3 rounded-md px-2 py-1 text-left transition', sel === i ? 'bg-subtle' : 'hover:bg-subtle', activeCat === t.category && 'ring-1 ring-primary/40')}>
                  <span className="num w-5 shrink-0 text-right text-xs text-muted-foreground">{i + 1}</span>
                  <span className="w-[72px] shrink-0 truncate text-[13px] font-medium">{t.category}</span>
                  <div className="relative h-5 flex-1 overflow-hidden rounded bg-muted/60">
                    <motion.div initial={{ width: 0 }} animate={{ width: `${(t.heat / max) * 100}%` }} transition={{ duration: 0.6, delay: i * 0.03, ease: [0.2, 0.8, 0.2, 1] }}
                      className="h-full rounded" style={{ background: `linear-gradient(90deg, hsl(var(--primary) / ${0.35 + (1 - i / 10) * 0.5}), hsl(${260 - i * 6} 80% 66% / ${0.45 + (1 - i / 10) * 0.45}))` }} />
                  </div>
                  <span className="num w-10 shrink-0 text-right text-xs font-medium">{fmtNum(t.heat)}</span>
                  <span className={cn('flex w-8 shrink-0 items-center justify-end gap-0.5 text-xs', t.rising > 0 ? 'text-danger' : 'text-muted-foreground/60')}>
                    {t.rising > 0 ? <><TrendingUp className="h-3 w-3" />{t.rising}</> : '—'}
                  </span>
                </button>
              ))}
            </div>
            {cur && (
              <div className="flex flex-col rounded-xl bg-gradient-to-br from-primary-soft to-transparent p-4 hairline">
                <div className="flex items-center justify-between">
                  <div className="text-lg font-semibold">{cur.category}</div>
                  <Badge tone={cur.rising > 0 ? 'danger' : 'neutral'}>{cur.rising > 0 ? `${cur.rising} 本上升中` : '平稳'}</Badge>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <div className="rounded-lg bg-surface/80 p-2.5 hairline"><div className="text-[11.5px] text-muted-foreground">热度</div><div className="num text-lg font-semibold">{fmtNum(cur.heat)}</div></div>
                  <div className="rounded-lg bg-surface/80 p-2.5 hairline"><div className="text-[11.5px] text-muted-foreground">上榜书</div><div className="num text-lg font-semibold">{cur.books}</div></div>
                </div>
                <div className="mt-3 text-[11.5px] font-medium text-muted-foreground">代表作</div>
                <ul className="mt-1 flex-1 space-y-1">
                  {cur.sample_titles.slice(0, 3).map((s) => <li key={s} className="truncate text-[13px]">《{s}》</li>)}
                </ul>
                <Button className="mt-4" variant="primary" size="sm" icon={<Lightbulb className="h-3.5 w-3.5" />} onClick={() => onPick(cur)}>用这个题材出选题</Button>
              </div>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  )
}

function RankTable({ items, onIdea }: { items: RankItem[]; onIdea: (i: RankItem) => void }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-[13px]">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="w-14 py-2.5 pl-5 font-medium">排名</th>
            <th className="py-2.5 font-medium">书名</th>
            <th className="py-2.5 font-medium">作者</th>
            <th className="py-2.5 font-medium">分类</th>
            <th className="py-2.5 text-right font-medium">在读</th>
            <th className="py-2.5 text-right font-medium">字数</th>
            <th className="py-2.5 pl-6 font-medium">标签</th>
            <th className="w-28 py-2.5 pr-5" />
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.book_id_ext} className="group border-b border-border/60 last:border-0 hover:bg-subtle/70">
              <td className="py-2.5 pl-5"><RankNo n={i.rank} /></td>
              <td className="max-w-[260px] py-2.5">
                <Tip content={i.abstract}><span className="block truncate font-medium">{i.title}</span></Tip>
              </td>
              <td className="py-2.5 text-muted-foreground">{i.author}</td>
              <td className="py-2.5"><Badge>{i.category}</Badge></td>
              <td className="num py-2.5 text-right">{fmtNum(i.read_count)}</td>
              <td className="num py-2.5 text-right text-muted-foreground">{fmtNum(i.word_count)}</td>
              <td className="py-2.5 pl-6"><div className="flex gap-1">{i.tags.slice(0, 3).map((t) => <span key={t} className="whitespace-nowrap rounded bg-muted px-1.5 py-0.5 text-[11.5px] text-muted-foreground">{t}</span>)}</div></td>
              <td className="py-2.5 pr-5 text-right">
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
    <span className={cn('num inline-flex h-6 w-6 items-center justify-center rounded-md text-xs font-semibold', top ? 'text-white' : 'text-muted-foreground')}
      style={top ? { background: ['linear-gradient(135deg,#f59e0b,#ef4444)', 'linear-gradient(135deg,#94a3b8,#64748b)', 'linear-gradient(135deg,#d97706,#92400e)'][n - 1] } : undefined}>
      {n}
    </span>
  )
}

function RankCard({ item: i, onIdea }: { item: RankItem; onIdea: () => void }) {
  return (
    <div className="group flex flex-col rounded-xl bg-background p-4 hairline transition hover:shadow-lift">
      <div className="flex items-start gap-3">
        <RankNo n={i.rank} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold">{i.title}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">{i.author} · {i.category}</div>
        </div>
      </div>
      <p className="mt-2.5 line-clamp-2 text-[12.5px] leading-relaxed text-muted-foreground">{i.abstract}</p>
      <div className="mt-3 flex flex-wrap gap-1">{i.tags.map((t) => <span key={t} className="rounded bg-muted px-1.5 py-0.5 text-[11.5px] text-muted-foreground">{t}</span>)}</div>
      <div className="mt-auto flex items-center justify-between pt-3 text-xs text-muted-foreground">
        <span className="num">在读 {fmtNum(i.read_count)} · {fmtNum(i.word_count)} 字</span>
        <Button size="xs" variant="soft" onClick={onIdea}>出选题</Button>
      </div>
    </div>
  )
}
