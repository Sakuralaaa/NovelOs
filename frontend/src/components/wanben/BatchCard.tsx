import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, ArrowUpRight, Check, CheckCircle2, ChevronRight, FlagCheckered, Hourglass, Pause, Play, RotateCw, Stethoscope, X, Zap,
} from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Sheet } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/misc'
import { JobInline } from '@/components/common/JobInline'
import { useKindJob } from '@/hooks/useKindJob'
import { wanbenApi, wqk } from '@/lib/api'
import { useJobPolling, useJobs, useResumeJob } from '@/lib/jobs'
import type { BatchChapterCheck, WanbenBatch, WanbenProgress } from '@/lib/types'
import { cn, fmtDateTime, fmtNum, fmtTime } from '@/lib/utils'
import { BATCH_STATUS, Tile, stopReasonLabel } from './bits'

const KEY = (id: number) => `wanben-batch:${id}`

/** 分批连写：开始 / 暂停 / 续跑、停止原因、批次列表与抽检报告 */
export function BatchCard({ bookId, progress, enabled, onGoRefine, className }: {
  bookId: number; progress: WanbenProgress; enabled: boolean; onGoRefine: () => void; className?: string
}) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const resume = useResumeJob()
  const { active, latest } = useKindJob(bookId, 'wanben_batch', KEY(bookId), '完本连写')
  const batches = useQuery({ queryKey: wqk.batches(bookId), queryFn: () => wanbenApi.batches(bookId), refetchInterval: active ? 4000 : false })
  const [open, setOpen] = useState<number | null>(null)
  const last = progress.last_batch
  const lastJob = useJobPolling(last?.status === 'failed' && last.job_id ? last.job_id : null)
  const canResume = !active && last?.status === 'failed' && lastJob.data && (lastJob.data.status === 'failed' || lastJob.data.status === 'interrupted') && lastJob.data.resumable !== false

  const refresh = () => qc.invalidateQueries({ queryKey: ['wanben', bookId] })
  const run = (force = false) => start(wanbenApi.batch(bookId, force), {
    key: KEY(bookId), label: '完本连写',
    successMsg: (j) => (j.result?.message as string) || '本批连写完成',
    onSuccess: refresh, onError: refresh,
  }).then(refresh)
  const pause = useMutation({
    mutationFn: () => wanbenApi.pause(bookId),
    meta: { errorTitle: '暂停失败' },
    onSuccess: (r) => { toast.success('已请求暂停', { description: r.message }); refresh() },
  })
  const doResume = async () => {
    if (!last?.job_id) return
    const j = await resume(last.job_id, '完本连写')
    if (j) { await start(Promise.resolve(j), { key: KEY(bookId), label: '完本连写', successMsg: (x) => (x.result?.message as string) || '本批连写完成', onSuccess: refresh }); refresh() }
  }

  const done = progress.chapters_remaining <= 0 && progress.chapters_total > 0
  const running = !!active || !!progress.running_batch_id
  // 发起后立刻停下（没开新批次）的情况：只有任务结果里有原因
  const quick = !running && latest?.status === 'succeeded' && latest.result?.stopped && !(latest.result?.batches as unknown[] | undefined)?.length
    && (!last || new Date(latest.updated_at).getTime() > new Date(last.finished_at ?? last.created_at ?? 0).getTime()) ? latest.result : null

  return (
    <Card className={className}>
      <CardHeader icon={<Zap />} title="分批连写" desc={`每批写完做一次抽检${last ? ` · 最近第 ${last.seq} 批` : ''}`}
        action={running ? (
          <Button size="sm" icon={<Pause className="h-3.5 w-3.5" />} loading={pause.isPending} disabled={progress.paused && running} onClick={() => pause.mutate()}>{progress.paused ? '暂停中…' : '暂停'}</Button>
        ) : canResume ? (
          <Button size="sm" variant="primary" icon={<RotateCw className="h-3.5 w-3.5" />} onClick={() => void doResume()}>续跑</Button>
        ) : (
          <Button size="sm" variant="primary" icon={<Play className="h-3.5 w-3.5" />} disabled={!enabled || done} title={!enabled ? '先开启完本模式' : done ? '已写满目标' : undefined} onClick={() => void run()}>
            {batches.data?.length ? '继续连写' : '开始连写'}
          </Button>
        )} />
      <CardBody className="space-y-3 p-4 sm:p-5">
        {active && <JobInline job={active} />}
        {!active && running && <p className="flex items-center gap-2 rounded-lg bg-primary-soft/60 px-3 py-2 text-[12.5px] text-primary"><Hourglass className="h-3.5 w-3.5" />第 {last?.start_no}–{last?.end_no} 章正在连写</p>}

        {quick && quick.reason !== last?.stop_reason && (
          <p className="flex gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] leading-relaxed text-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words"><b className="mr-1">{stopReasonLabel(quick.reason as string)}</b>{quick.message as string}</span></p>
        )}
        {!running && last && <StopNotice bookId={bookId} batch={last} canResume={!!canResume} onForce={() => void run(true)} onGoRefine={onGoRefine} />}
        {!running && !last && enabled && !done && (
          <p className="rounded-lg bg-subtle px-3 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">还没开始。没有规划时会先按字数目标倒推卷纲，再从第 {progress.chapters_written + 1} 章写起，按「每批章数」一批一批写。</p>
        )}
        {done && !running && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl bg-success-soft px-3.5 py-3 text-[13px] text-success">
            <FlagCheckered className="h-4 w-4 shrink-0" /><span className="min-w-0 flex-1 font-medium">已写满目标 {progress.chapters_total} 章</span>
            <Link to={`/books/${bookId}/check`}><Button size="sm" variant="secondary" icon={<Stethoscope className="h-3.5 w-3.5" />}>整书体检</Button></Link>
          </div>
        )}

        {batches.isLoading ? <Skeleton className="h-24 rounded-xl" /> : !!batches.data?.length && (
          <div>
            <div className="mb-1.5 text-[12px] font-medium text-muted-foreground">批次记录</div>
            <div className="divide-y overflow-hidden rounded-xl hairline">
              {batches.data.map((b) => <BatchRow key={b.id} b={b} onOpen={() => setOpen(b.id)} />)}
            </div>
          </div>
        )}
      </CardBody>
      <BatchReportSheet bookId={bookId} batchId={open} onClose={() => setOpen(null)} />
    </Card>
  )
}

function StopNotice({ bookId, batch, canResume, onForce, onGoRefine }: { bookId: number; batch: WanbenBatch; canResume: boolean; onForce: () => void; onGoRefine: () => void }) {
  const r = batch.stop_reason
  if (batch.status === 'done' && !r) {
    return <p className="flex items-center gap-2 rounded-lg bg-success-soft/70 px-3 py-2 text-[12.5px] text-success"><CheckCircle2 className="h-3.5 w-3.5 shrink-0" />{batch.message || `第 ${batch.start_no}–${batch.end_no} 章写完`}，点「继续连写」写下一批</p>
  }
  if (r === 'target_reached') return null
  const tone = batch.status === 'failed' ? 'danger' : r === 'paused' ? 'neutral' : 'warning'
  return (
    <div className={cn('rounded-xl px-3.5 py-3 text-[12.5px] leading-relaxed', tone === 'danger' ? 'bg-danger-soft text-danger' : tone === 'neutral' ? 'bg-subtle text-foreground/80' : 'bg-warning-soft text-warning')}>
      <div className="flex items-start gap-2">
        {tone === 'neutral' ? <Pause className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}
        <div className="min-w-0 flex-1">
          <div className="font-semibold">停下了：{stopReasonLabel(r) || BATCH_STATUS[batch.status]?.label}</div>
          {batch.message && <div className="mt-0.5 break-words opacity-90">{batch.message}</div>}
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-2">
        {r === 'refine_pending' && <>
          <Button size="sm" variant="secondary" onClick={onGoRefine}>去审批精修章</Button>
          <Button size="sm" variant="ghost" onClick={onForce}>先不审，继续写</Button>
        </>}
        {(r === 'pending_chapter' || r === 'review_failed' || r === 'awaiting_adopt') && (
          <Link to={`/books/${bookId}/chapters`}><Button size="sm" variant="secondary" icon={<ArrowUpRight className="h-3.5 w-3.5" />}>去章节处理</Button></Link>
        )}
        {batch.status === 'failed' && !canResume && <span className="text-[12px] opacity-80">这个任务不能续跑，点「继续连写」会从下一章重新发起。</span>}
      </div>
    </div>
  )
}

function BatchRow({ b, onOpen }: { b: WanbenBatch; onOpen: () => void }) {
  const st = BATCH_STATUS[b.status] ?? { label: b.status, tone: 'neutral' as const }
  const s = b.summary
  return (
    <button type="button" onClick={onOpen} className="focus-ring flex min-h-[56px] w-full items-center gap-3 bg-surface px-3.5 py-2.5 text-left transition hover:bg-subtle">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-muted text-[12px] font-semibold num">{b.seq}</span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="num text-[13.5px] font-semibold">第 {b.start_no}–{b.end_no} 章</span>
          <Badge tone={st.tone}>{st.label}</Badge>
          {b.stop_reason && b.stop_reason !== 'paused' && <Badge tone="outline">{stopReasonLabel(b.stop_reason)}</Badge>}
        </span>
        <span className="num mt-0.5 block truncate text-[12px] text-muted-foreground">
          {s ? `${s.count} 章 · ${fmtNum(s.words)} 字 · 抽检通过 ${s.passed}/${s.count}${s.reader_avg != null ? ` · 读者均分 ${s.reader_avg}` : ''}` : b.message || '—'} · {fmtTime(b.finished_at ?? b.created_at)}
        </span>
      </span>
      {s && s.failed > 0 && <span className="num shrink-0 rounded-full bg-danger-soft px-2 py-0.5 text-[11.5px] font-medium text-danger">{s.failed} 未过</span>}
      <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
    </button>
  )
}

function BatchReportSheet({ bookId, batchId, onClose }: { bookId: number; batchId: number | null; onClose: () => void }) {
  const q = useQuery({ queryKey: wqk.batch(bookId, batchId ?? 0), queryFn: () => wanbenApi.batchDetail(bookId, batchId!), enabled: !!batchId })
  const b = q.data
  const rep = b?.report
  const th = rep?.reader_threshold ?? 7
  return (
    <Sheet open={!!batchId} onOpenChange={(o) => !o && onClose()} width={760}
      title={b ? `第 ${b.seq} 批抽检 · 第 ${b.start_no}–${b.end_no} 章` : '批次抽检'}
      desc={b ? `${BATCH_STATUS[b.status]?.label ?? b.status}${b.stop_reason ? ` · ${stopReasonLabel(b.stop_reason)}` : ''}${b.finished_at ? ` · ${fmtDateTime(b.finished_at)}` : ''}` : undefined}>
      {q.isLoading || !b ? <div className="space-y-3"><Skeleton className="h-20 rounded-xl" /><Skeleton className="h-48 rounded-xl" /></div> : (
        <div className="space-y-4">
          {b.message && <p className="rounded-lg bg-subtle px-3 py-2 text-[12.5px] text-foreground/80">{b.message}</p>}
          {rep ? (
            <>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <Tile label="本批字数" value={fmtNum(rep.summary.words)} sub={`${rep.summary.count} 章`} />
                <Tile label="抽检通过" value={`${rep.summary.passed}/${rep.summary.count}`} tone={rep.summary.failed ? 'warning' : 'success'} />
                <Tile label="读者均分" value={rep.summary.reader_avg ?? '—'} sub={`阈值 ${th}`} tone={rep.summary.reader_avg != null && rep.summary.reader_avg < th ? 'danger' : undefined} />
                <Tile label="一致性问题" value={rep.summary.consistency_issues} tone={rep.summary.consistency_issues ? 'warning' : undefined} />
              </div>
              {!!rep.summary.awaiting_approval.length && <p className="rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning">精修待审批：第 {rep.summary.awaiting_approval.join('、')} 章</p>}
              <div className="space-y-3">{rep.chapters.map((c) => <ChapterCheckCard key={c.chapter_id} bookId={bookId} c={c} th={th} />)}</div>
            </>
          ) : <p className="py-10 text-center text-[13px] text-muted-foreground">这一批还没有抽检报告（批次结束后生成）</p>}
        </div>
      )}
    </Sheet>
  )
}

function Ok({ ok, children }: { ok: boolean; children: React.ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1 text-[12px] font-medium', ok ? 'text-success' : 'text-danger')}>
      {ok ? <Check className="h-3.5 w-3.5" /> : <X className="h-3.5 w-3.5" />}{children}
    </span>
  )
}

function ChapterCheckCard({ bookId, c, th }: { bookId: number; c: BatchChapterCheck; th: number }) {
  return (
    <div className={cn('rounded-xl bg-surface p-3.5 hairline', !c.passed && 'ring-1 ring-danger/25')}>
      <div className="flex flex-wrap items-center gap-2">
        <Link to={`/books/${bookId}/chapters/${c.chapter_id}`} className="min-w-0 truncate text-[13.5px] font-semibold hover:text-primary">第{c.number}章 {c.title}</Link>
        {c.in_refine && <Badge tone="primary">精修</Badge>}
        <Badge tone={c.status === 'committed' ? 'success' : 'warning'}>{c.status === 'committed' ? '已提交' : '待处理'}</Badge>
        <span className="ml-auto flex items-center gap-2 text-[12px]">
          {c.review_overall != null && <span className="num text-muted-foreground">审稿 {c.review_overall}</span>}
          {c.reader_score != null && <span title={`读者分阈值 ${th}`} className={cn('num rounded-full px-2 py-0.5 font-semibold', c.reader_below_threshold ? 'bg-danger-soft text-danger' : 'bg-success-soft text-success')}>读者 {c.reader_score}</span>}
        </span>
      </div>
      <div className="mt-2.5 grid gap-2.5 text-[12.5px] leading-relaxed sm:grid-cols-2">
        <div className="rounded-lg bg-subtle/80 px-3 py-2">
          <div className="flex items-center justify-between gap-2"><span className="text-muted-foreground">字数</span><Ok ok={c.words_ok}><span className="num">{fmtNum(c.words)} / {fmtNum(c.words_target)}</span></Ok></div>
          <div className="mt-1.5 flex items-center justify-between gap-2"><span className="text-muted-foreground">开头切冲突</span><Ok ok={c.opening.conflict}>{c.opening.conflict ? '有' : '没有'}</Ok></div>
          <p className="mt-1 line-clamp-2 break-words font-serif text-foreground/75">{c.opening.head}</p>
        </div>
        <div className="rounded-lg bg-subtle/80 px-3 py-2">
          <div className="flex items-center justify-between gap-2"><span className="text-muted-foreground">高潮点</span><Ok ok={c.climax.found}>{c.climax.found ? (c.climax.position != null ? `在 ${Math.round(c.climax.position * 100)}% 处` : '找到') : '没找到'}</Ok></div>
          {c.climax.quote && <p className="mt-1 line-clamp-2 break-words font-serif text-foreground/75">{c.climax.quote}</p>}
          {c.climax.planned && <p className="mt-1 text-[11.5px] text-muted-foreground">细纲：{c.climax.planned}</p>}
        </div>
        <div className="rounded-lg bg-subtle/80 px-3 py-2 sm:col-span-2">
          <div className="flex items-center justify-between gap-2"><span className="text-muted-foreground">章末钩子</span><Ok ok={c.hook.ok}>{c.hook.ok ? '有' : '落空'}</Ok></div>
          <p className="mt-1 line-clamp-2 break-words font-serif text-foreground/75">…{c.hook.tail}</p>
          {c.hook.comment && <p className="mt-1 text-[11.5px] text-danger">{c.hook.comment}</p>}
          {c.hook.planned && <p className="mt-1 text-[11.5px] text-muted-foreground">细纲：{c.hook.planned}</p>}
        </div>
      </div>
      {!!c.consistency.length && (
        <div className="mt-2.5 space-y-1">
          <div className="text-[12px] font-medium text-muted-foreground">一致性</div>
          {c.consistency.map((x, i) => (
            <p key={i} className="flex gap-2 text-[12.5px] leading-relaxed">
              <span className={cn('mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full', x.severity === 'high' ? 'bg-danger' : x.severity === 'mid' ? 'bg-warning' : 'bg-muted-foreground/60')} />
              <span className="min-w-0 break-words">{x.comment}{x.quote && <span className="text-muted-foreground">「{x.quote}」</span>}</span>
            </p>
          ))}
        </div>
      )}
      {c.failed.length > 0 ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">{c.failed.map((f, i) => <span key={i} className="rounded-md bg-danger-soft px-2 py-1 text-[11.5px] text-danger">{f}</span>)}</div>
      ) : <p className="mt-2.5 text-[12px] font-medium text-success">抽检全部通过</p>}
    </div>
  )
}
