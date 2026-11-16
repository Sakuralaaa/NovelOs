import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, Check, CircleDashed, FileText, Hourglass, Lightbulb, Plus, Radar, RotateCw, X } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card, CardHeader } from '@/components/ui/card'
import { Progress, Skeleton } from '@/components/ui/misc'
import { OnboardingCard } from '@/components/common/OnboardingCard'
import { BookCover, QuickCreateDialog, StageBadge } from '@/components/common/BookBits'
import { useBooks, useJobsList } from '@/hooks/queries'
import { cn, fmtNum, fmtTime, jobLabel } from '@/lib/utils'
import { useResumeJob } from '@/lib/jobs'

function greeting() {
  const h = new Date().getHours()
  if (h < 5) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 13) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

const BOOK_ROWS = 4
const JOB_ROWS = 6

export default function Home() {
  const { data: books, isLoading: booksLoading } = useBooks()
  const { data: jobs } = useJobsList()
  const resume = useResumeJob()
  const [createOpen, setCreateOpen] = useState(false)
  const nav = useNavigate()

  const hasBooks = (books?.length ?? 0) > 0
  const recentJobs = (jobs ?? []).slice(0, JOB_ROWS)
  const latest = books?.[0]

  const quick = [
    { to: '/radar', icon: Radar, t: '热点雷达', tone: 'bg-orange-500/10 text-orange-600 dark:text-orange-400' },
    { to: '/ideas', icon: Lightbulb, t: '选题工坊', tone: 'bg-amber-500/10 text-amber-600 dark:text-amber-400' },
    { to: latest ? `/books/${latest.id}/chapters` : '/books', icon: FileText, t: latest ? '继续写作' : '我的书', tone: 'bg-primary/10 text-primary' },
  ]

  return (
    <div className="page">
      <div className="mb-7 flex min-h-[40px] flex-wrap items-center justify-between gap-4">
        <h1 className="text-[22px] font-semibold tracking-tight">{greeting()}，今天写点什么？</h1>
        <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>新建作品</Button>
      </div>

      <OnboardingCard latestBookId={latest?.id} onCreate={() => setCreateOpen(true)} onNavigate={(to) => nav(to)} />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        {quick.map((q) => (
          <Link key={q.t} to={q.to} className="card-hover group flex h-[72px] items-center gap-3.5 rounded-xl border bg-surface px-4 shadow-card">
            <span className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px]', q.tone)}><q.icon className="h-[18px] w-[18px]" strokeWidth={1.9} /></span>
            <span className="flex-1 truncate text-[14.5px] font-medium">{q.t}</span>
            <ArrowUpRight className="h-4 w-4 text-muted-foreground/60 transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-foreground" />
          </Link>
        ))}
      </div>

      <div className="grid items-stretch gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Card className="flex flex-col">
          <CardHeader
            divider
            title="最近的书"
            action={hasBooks && <Link to="/books" className="flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">全部<ArrowRight className="h-3.5 w-3.5" /></Link>}
          />
          <div className="flex-1 p-2">
            {booksLoading ? (
              Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="m-1 h-[76px] rounded-lg" />)
            ) : !hasBooks ? (
              <div className="flex h-full min-h-[260px] flex-col items-center justify-center gap-4 text-center">
                <div className="text-[14px] text-muted-foreground">书架还是空的</div>
                <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>新建作品</Button>
              </div>
            ) : (
              books!.slice(0, BOOK_ROWS).map((b) => (
                <Link key={b.id} to={`/books/${b.id}`} className="group flex h-[84px] items-center gap-4 rounded-lg px-3 transition-colors hover:bg-subtle">
                  <BookCover book={b} mini className="w-[46px] shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[14.5px] font-medium group-hover:text-primary">{b.title}</div>
                    <div className="mt-1 truncate text-[12.5px] text-muted-foreground">{b.genre} · {b.gender === 'male' ? '男频' : '女频'}</div>
                  </div>
                  <div className="hidden w-[96px] shrink-0 sm:block"><StageBadge status={b.status} /></div>
                  <div className="num hidden w-[110px] shrink-0 text-right text-[13px] md:block">
                    <div>{fmtNum(b.stats.words)} 字</div>
                    <div className="mt-1 text-[12px] text-muted-foreground">{b.stats.chapters} 章</div>
                  </div>
                  <div className="w-[72px] shrink-0 text-right text-[12.5px] text-muted-foreground">{fmtTime(b.updated_at)}</div>
                </Link>
              ))
            )}
          </div>
        </Card>

        <Card className="flex flex-col">
          <CardHeader divider title="最近任务" />
          <div className="flex-1 p-2">
            {recentJobs.length === 0 ? (
              <div className="flex h-full min-h-[200px] items-center justify-center text-[13.5px] text-muted-foreground">暂无任务</div>
            ) : recentJobs.map((j) => {
              const active = j.status === 'running' || j.status === 'queued'
              return (
                <div key={j.id} className="flex min-h-[48px] flex-col justify-center rounded-lg px-3 py-2 hover:bg-subtle">
                  <div className="flex items-center gap-2.5">
                    <span className={cn('flex h-5 w-5 shrink-0 items-center justify-center rounded-full',
                      j.status === 'succeeded' ? 'bg-success-soft text-success' : j.status === 'failed' ? 'bg-danger-soft text-danger' : j.status === 'interrupted' ? 'bg-warning-soft text-warning' : 'bg-primary-soft text-primary')}>
                      {j.status === 'succeeded' ? <Check className="h-3 w-3" strokeWidth={3} /> : j.status === 'interrupted' ? <Hourglass className="h-3 w-3" /> : j.status === 'failed' ? <X className="h-3 w-3" strokeWidth={3} /> : <CircleDashed className="h-3 w-3 animate-spin" strokeWidth={2.5} />}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-[13.5px]">{jobLabel(j.kind)}</span>
                    {j.status === 'interrupted' && <span className="shrink-0 text-[12px] font-medium text-warning">已中断</span>}
                    {j.status === 'interrupted' && j.resumable !== false && (
                      <button onClick={() => resume(j.id)} className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md bg-primary-soft px-2 text-[12px] font-medium text-primary hover:bg-primary-soft/70">
                        <RotateCw className="h-3 w-3" />继续
                      </button>
                    )}
                    <span className="shrink-0 text-[12px] text-muted-foreground">{fmtTime(j.updated_at)}</span>
                  </div>
                  {active && <Progress className="ml-[30px] mt-2 w-auto" value={j.progress} />}
                  {j.status === 'failed' && j.error && <p className="ml-[30px] mt-1 truncate text-[12px] text-danger">{j.error}</p>}
                </div>
              )
            })}
          </div>
        </Card>
      </div>

      <QuickCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
