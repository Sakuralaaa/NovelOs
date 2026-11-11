import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowRight, Check, CircleDashed, Clock, FileText, Lightbulb, Plus, Radar, Settings2, Sparkles, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Progress, Skeleton } from '@/components/ui/misc'
import { BookCover, QuickCreateDialog, StageBadge, StageDots } from '@/components/common/BookBits'
import { EmptyState } from '@/components/common/States'
import { useBooks, useChannels, useJobsList, useStatus } from '@/hooks/queries'
import { cn, fmtNum, fmtTime, jobLabel } from '@/lib/utils'

function greeting() {
  const h = new Date().getHours()
  if (h < 5) return '夜深了'
  if (h < 11) return '早上好'
  if (h < 13) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
}

export default function Home() {
  const { data: status } = useStatus()
  const { data: channels } = useChannels()
  const { data: books, isLoading: booksLoading } = useBooks()
  const { data: jobs } = useJobsList()
  const [createOpen, setCreateOpen] = useState(false)
  const [demoAck, setDemoAck] = useState(() => localStorage.getItem('novelos-demo-ack') === '1')
  const [hideGuide, setHideGuide] = useState(() => localStorage.getItem('novelos-hide-guide') === '1')
  const nav = useNavigate()

  const noChannel = (channels?.length ?? 0) === 0 || !!status?.mock_mode
  const step1 = !noChannel || demoAck
  const hasBooks = (books?.length ?? 0) > 0
  const showGuide = (noChannel || !hasBooks) && !hideGuide
  const running = (jobs ?? []).filter((j) => j.status === 'running' || j.status === 'queued')
  const recentJobs = (jobs ?? []).slice(0, 6)

  const steps = [
    {
      n: 1, done: step1, icon: Settings2, title: '接入写作模型',
      desc: '填入 OpenAI 兼容的 Base URL 和 Key。还没有？先用演示模式体验全流程。',
      actions: (
        <>
          <Button size="sm" variant="primary" onClick={() => nav('/settings')}>去设置</Button>
          {!step1 && <Button size="sm" variant="ghost" onClick={() => { localStorage.setItem('novelos-demo-ack', '1'); setDemoAck(true) }}>先用演示模式</Button>}
        </>
      ),
    },
    {
      n: 2, done: hasBooks, icon: Radar, title: '从热点雷达找选题',
      desc: '看看番茄榜单上什么题材正在涨，一键生成 3 个选题卡。',
      actions: <Button size="sm" variant={step1 ? 'primary' : 'secondary'} onClick={() => nav('/radar')}>打开雷达</Button>,
    },
    {
      n: 3, done: hasBooks, icon: Sparkles, title: '一键开写',
      desc: '已有点子？直接建书，自动生成设定 → 大纲 → 正文。',
      actions: <Button size="sm" variant={step1 ? 'primary' : 'secondary'} onClick={() => setCreateOpen(true)}>一键开写</Button>,
    },
  ]
  const curStep = steps.findIndex((s) => !s.done)

  return (
    <div className="page">
      <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-[13px] text-muted-foreground">{new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}</div>
          <h1 className="mt-1 text-[26px] font-semibold tracking-tight">{greeting()}，今天写点什么？</h1>
        </div>
        <div className="flex gap-2">
          <Button icon={<Radar className="h-4 w-4" />} onClick={() => nav('/radar')}>看热点</Button>
          <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreateOpen(true)}>新建作品</Button>
        </div>
      </div>

      {showGuide && (
        <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="relative mb-8 overflow-hidden rounded-2xl bg-surface p-6 hairline shadow-card md:p-7">
          <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-gradient-to-br from-primary/20 to-violet-400/10 blur-2xl" />
          <div className="pointer-events-none absolute inset-0 bg-dots opacity-60 [mask-image:linear-gradient(to_left,black,transparent_60%)]" />
          <div className="relative flex items-start justify-between gap-4">
            <div>
              <Badge tone="primary" className="mb-2">新手引导</Badge>
              <h2 className="text-lg font-semibold tracking-tight">三步，从零到第一章</h2>
              <p className="mt-1 text-[13.5px] text-muted-foreground">不懂写作流程也没关系，跟着点就行。每一步都可以回头改。</p>
            </div>
            {hasBooks && (
              <button onClick={() => { localStorage.setItem('novelos-hide-guide', '1'); setHideGuide(true) }} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted" aria-label="隐藏引导"><X className="h-4 w-4" /></button>
            )}
          </div>
          <div className="relative mt-5 grid gap-3 md:grid-cols-3">
            {steps.map((s, i) => (
              <div key={s.n} className={cn('flex flex-col rounded-xl border bg-background/60 p-4 transition', i === curStep && 'border-primary/40 bg-primary-soft/40 shadow-glow')}>
                <div className="flex items-center gap-2.5">
                  <div className={cn('flex h-7 w-7 items-center justify-center rounded-full text-[13px] font-semibold', s.done ? 'bg-success text-white' : i === curStep ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>
                    {s.done ? <Check className="h-4 w-4" /> : s.n}
                  </div>
                  <div className="text-[14px] font-semibold">{s.title}</div>
                </div>
                <p className="mt-2 flex-1 text-[13px] leading-relaxed text-muted-foreground">{s.desc}</p>
                <div className="mt-3.5 flex flex-wrap gap-2">{s.actions}</div>
              </div>
            ))}
          </div>
          {noChannel && demoAck && (
            <p className="relative mt-4 flex items-center gap-1.5 text-[12.5px] text-warning"><Sparkles className="h-3.5 w-3.5" />演示模式下生成的是示例内容，接入模型后即可写出真正的小说。</p>
          )}
        </motion.div>
      )}

      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-[15px] font-semibold">最近的书</h2>
            {hasBooks && <Link to="/books" className="flex items-center gap-1 text-[13px] text-muted-foreground hover:text-foreground">全部 <ArrowRight className="h-3.5 w-3.5" /></Link>}
          </div>
          {booksLoading ? (
            <div className="grid gap-3 sm:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-[132px] rounded-xl" />)}</div>
          ) : !hasBooks ? (
            <EmptyState kind="book" title="还没有作品" desc="从热点雷达挑个题材，或者直接一键开写。" action={<><Button onClick={() => nav('/radar')}>看热点</Button><Button variant="primary" onClick={() => setCreateOpen(true)}>一键开写</Button></>} />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {books!.slice(0, 4).map((b) => (
                <Link key={b.id} to={`/books/${b.id}`} className="group flex gap-4 rounded-xl bg-surface p-3.5 hairline shadow-card transition hover:-translate-y-0.5 hover:shadow-lift">
                  <BookCover book={b} className="w-[74px] shrink-0" />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="truncate font-semibold group-hover:text-primary">{b.title}</div>
                        <div className="mt-0.5 truncate text-xs text-muted-foreground">{b.genre} · {b.gender === 'male' ? '男频' : '女频'}</div>
                      </div>
                    </div>
                    <div className="mt-2"><StageBadge status={b.status} /></div>
                    <div className="mt-auto pt-3">
                      <StageDots status={b.status} />
                      <div className="mt-2 flex items-center justify-between text-xs text-muted-foreground">
                        <span className="num">{b.stats.chapters} 章 · {fmtNum(b.stats.words)} 字</span>
                        <span>{fmtTime(b.updated_at)}</span>
                      </div>
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          )}

          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            {[
              { to: '/radar', icon: Radar, t: '热点雷达', d: '今日榜单与题材热度' },
              { to: '/ideas', icon: Lightbulb, t: '选题工坊', d: '一次生成 3 个选题卡' },
              { to: hasBooks ? `/books/${books![0].id}/chapters` : '/books', icon: FileText, t: '继续写作', d: hasBooks ? `回到《${books![0].title}》` : '打开我的书' },
            ].map((q) => (
              <Link key={q.t} to={q.to} className="group flex items-center gap-3 rounded-xl bg-surface p-3.5 hairline shadow-card transition hover:shadow-lift">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-primary"><q.icon className="h-4 w-4" /></div>
                <div className="min-w-0">
                  <div className="text-[13.5px] font-medium">{q.t}</div>
                  <div className="truncate text-xs text-muted-foreground">{q.d}</div>
                </div>
              </Link>
            ))}
          </div>
        </section>

        <Card className="h-fit">
          <CardHeader title="任务" desc={running.length ? `${running.length} 个进行中` : '最近的生成任务'} icon={<Clock className="h-4 w-4" />} />
          <CardBody className="space-y-1 px-3">
            {recentJobs.length === 0 && <p className="px-2 py-6 text-center text-[13px] text-muted-foreground">暂无任务。生成类操作会在这里显示进度。</p>}
            {recentJobs.map((j) => (
              <div key={j.id} className="rounded-lg px-2 py-2 hover:bg-subtle">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    {j.status === 'succeeded' ? <Check className="h-3.5 w-3.5 shrink-0 text-success" /> : j.status === 'failed' ? <X className="h-3.5 w-3.5 shrink-0 text-danger" /> : <CircleDashed className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />}
                    <span className="truncate text-[13px] font-medium">{jobLabel(j.kind)}</span>
                  </div>
                  <span className="shrink-0 text-xs text-muted-foreground">{fmtTime(j.updated_at)}</span>
                </div>
                {(j.status === 'running' || j.status === 'queued') && <Progress className="mt-2" value={j.progress} />}
                {(j.message || j.error) && <p className={cn('mt-1 truncate pl-5.5 text-xs', j.error ? 'text-danger' : 'text-muted-foreground')} style={{ paddingLeft: 22 }}>{j.error || j.message}</p>}
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      <QuickCreateDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
