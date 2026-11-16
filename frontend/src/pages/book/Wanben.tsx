import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Download, FlagCheckered, Gauge, Stethoscope } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Progress, Skeleton } from '@/components/ui/misc'
import { Switch } from '@/components/ui/switch'
import { ErrorState, PageHeader } from '@/components/common/States'
import { BookCrumb } from './_shared'
import { SettingsCard } from '@/components/wanben/SettingsCard'
import { PlanCard } from '@/components/wanben/PlanCard'
import { BatchCard } from '@/components/wanben/BatchCard'
import { RefineCard } from '@/components/wanben/RefineCard'
import { IterateCard } from '@/components/wanben/IterateCard'
import { Tile, wan } from '@/components/wanben/bits'
import { HomogeneityButton } from '@/components/check/Homogeneity'
import { useBook } from '@/hooks/queries'
import { useBookId } from '@/hooks/useBookId'
import { useKindJob } from '@/hooks/useKindJob'
import { qk, wanbenApi, wqk } from '@/lib/api'
import type { BookMode, WanbenProgress } from '@/lib/types'
import { cn, fmtNum } from '@/lib/utils'

export default function WanbenPage() {
  const id = useBookId()
  const qc = useQueryClient()
  const { data: book } = useBook(id)
  const settings = useQuery({ queryKey: wqk.settings(id), queryFn: () => wanbenApi.settings(id) })
  const batchJob = useKindJob(id, 'wanben_batch', `wanben-batch:${id}`, '完本连写')
  const progress = useQuery({ queryKey: wqk.progress(id), queryFn: () => wanbenApi.progress(id), refetchInterval: batchJob.busy ? 4000 : false })
  const refineRef = useRef<HTMLDivElement>(null)
  const [exporting, setExporting] = useState(false)

  const mode = useMutation({
    mutationFn: (m: BookMode) => wanbenApi.saveSettings(id, { mode: m }),
    meta: { errorTitle: '切换模式失败' },
    onSuccess: (s) => {
      qc.setQueryData(wqk.settings(id), s)
      qc.invalidateQueries({ queryKey: ['wanben', id] })
      qc.invalidateQueries({ queryKey: qk.book(id) })
      toast.success(s.mode === 'wanben' ? '已开启完本模式' : '已切回连载模式', { description: s.mode === 'wanben' ? `目标 ${wan(s.target_words)}字，约 ${s.total_chapters} 章；先规划卷纲，再分批连写` : '完本设置和批次记录都保留着' })
    },
  })
  const doExport = async () => {
    setExporting(true)
    try { await wanbenApi.exportTxt(id, `${book?.title ?? '作品'}.txt`); toast.success('整书 TXT 已开始下载') }
    catch (e: any) { toast.error('导出失败', { description: e?.message }) } finally { setExporting(false) }
  }

  if (settings.isLoading) return <div className="page"><Skeleton className="h-8 w-48" /><Skeleton className="mt-6 h-40 rounded-xl" /><div className="mt-6 grid gap-6 lg:grid-cols-2"><Skeleton className="h-80 rounded-xl" /><Skeleton className="h-80 rounded-xl" /></div></div>
  if (settings.error || !settings.data) return <div className="page"><ErrorState error={settings.error} onRetry={() => settings.refetch()} /></div>
  const s = settings.data
  const on = s.mode === 'wanben'
  const p = progress.data

  return (
    <div className="page">
      <BookCrumb bookId={id} page="完本" />
      <PageHeader className="mt-3" title="完本模式" desc="按字数目标倒推卷纲，分批连写到完结；精修章停下等你审批，任何一章都能反复迭代。"
        actions={<>
          <HomogeneityButton target="book" id={id} />
          <Link to={`/books/${id}/check`}><Button icon={<Stethoscope className="h-4 w-4" />}>整书体检</Button></Link>
          <Button icon={<Download className="h-4 w-4" />} loading={exporting} onClick={() => void doExport()}>导出整书 TXT</Button>
        </>} />

      {/* 模式开关 */}
      <Card className={cn('flex flex-wrap items-center gap-4 p-4 sm:p-5', on && 'ring-1 ring-primary/25')}>
        <div className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-xl', on ? 'bg-primary text-primary-foreground' : 'bg-muted text-foreground/60')}><FlagCheckered className="h-5 w-5" /></div>
        <div className="min-w-0 flex-1 basis-[220px]">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold">{on ? '完本模式已开启' : '这本书是连载模式'}</span>
            <Badge tone={on ? 'primary' : 'neutral'}>{on ? '完本' : '连载'}</Badge>
          </div>
          <p className="mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">
            {on ? `目标 ${wan(s.target_words)}字 · 每章约 ${fmtNum(s.chapter_words)} 字 · 约 ${s.total_chapters} 章 · 每批 ${s.batch_size} 章` : '开启后会用下面的字数目标规划卷纲、按批连写，最后一卷写出完整结局。随时可以切回连载。'}
          </p>
        </div>
        <label className="flex min-h-[44px] shrink-0 cursor-pointer items-center gap-2.5 rounded-lg px-1">
          <span className="text-[13.5px] font-medium">{on ? '完本' : '开启完本模式'}</span>
          <Switch checked={on} onCheckedChange={(v) => mode.mutate(v ? 'wanben' : 'serial')} />
        </label>
      </Card>

      {/* 进度看板 */}
      {on && (p ? <ProgressBoard p={p} /> : <Skeleton className="mt-6 h-40 rounded-xl" />)}

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="space-y-6 lg:order-2">
          <SettingsCard bookId={id} settings={s} />
          <PlanCard bookId={id} plan={s.plan} enabled={on} />
        </div>
        <div className="min-w-0 space-y-6 lg:order-1">
          {p && <BatchCard bookId={id} progress={p} enabled={on} onGoRefine={() => refineRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })} />}
          <RefineCard ref={refineRef} bookId={id} />
          <IterateCard bookId={id} maxChapter={p?.chapters_written ?? book?.stats.chapters ?? 1} />
        </div>
      </div>
    </div>
  )
}

function ProgressBoard({ p }: { p: WanbenProgress }) {
  const pct = Math.round((p.ratio || 0) * 1000) / 10
  const chPct = p.chapters_total ? (p.chapters_written / p.chapters_total) * 100 : 0
  const v = p.current_volume
  const lb = p.last_batch
  return (
    <Card className="mt-6 overflow-hidden">
      <div className="grid gap-5 p-4 sm:p-5 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground"><Gauge className="h-3.5 w-3.5" />字数进度</div>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2">
            <span className="num font-serif text-[34px] font-semibold leading-none tracking-tight">{fmtNum(p.words)}</span>
            <span className="num text-[14px] text-muted-foreground">/ {fmtNum(p.target_words)} 字</span>
            <span className="num ml-auto text-[15px] font-semibold text-primary">{pct}%</span>
          </div>
          <Progress value={pct} className="mt-3 h-2.5" tone={pct >= 100 ? 'success' : 'primary'} />
          <div className="mt-4 flex items-center justify-between text-[12.5px] text-muted-foreground"><span>章节</span><span className="num">已写 {p.chapters_written} / {p.chapters_total} 章</span></div>
          <Progress value={chPct} className="mt-1.5 h-1.5" />
          {p.pending_words > 0 && <p className="num mt-2 text-[12px] text-muted-foreground">另有 {fmtNum(p.pending_words)} 字写好未提交（待审批或待处理）</p>}
          {!p.planned && <p className="mt-2 text-[12px] text-warning">还没有完本规划：第一次连写会先倒推卷纲</p>}
        </div>
        <div className="grid min-w-0 grid-cols-2 gap-2.5">
          <Tile label="当前卷" value={v ? `第${v.order}卷` : '—'} sub={v ? `${v.title || ''}${v.start && v.end ? ` · 第${v.start}–${v.end}章` : ''}` : '规划后显示'} />
          <Tile label="剩余章" value={p.chapters_remaining} sub={p.chapters_remaining ? `约 ${wan(p.chapters_remaining * Math.max(1, Math.round((p.target_words || 0) / Math.max(1, p.chapters_total))))}字` : '已写满目标'} tone={p.chapters_remaining ? undefined : 'success'} />
          <Tile label="已提交" value={`${p.chapters_committed} 章`} sub={`写到第 ${p.chapters_written} 章`} />
          <Tile label="最近批次" value={lb ? `第 ${lb.seq} 批` : '—'}
            sub={lb ? `第${lb.start_no}–${lb.end_no}章 · ${p.running_batch_id ? '连写中' : p.paused ? '已暂停' : lb.summary ? `通过 ${lb.summary.passed}/${lb.summary.count}` : lb.message || ''}` : '还没开始连写'}
            tone={lb?.status === 'failed' ? 'danger' : undefined} />
        </div>
      </div>
    </Card>
  )
}
