import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ChevronDown, Quote, RefreshCw, ShieldCheck, Sparkles } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/misc'
import { JobInline } from '@/components/common/JobInline'
import { LEVEL_LABEL, LEVEL_TONE, OVERLAP_LABEL, OVERLAP_TONE } from '@/components/fanfic/bits'
import { fanficApi, fqk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { FanficOverlap, OocCharacter, OocResult } from '@/lib/types'
import { cn, fmtDateTime } from '@/lib/utils'

const SEV: Record<string, { label: string; cls: string }> = {
  high: { label: '严重', cls: 'bg-danger-soft text-danger' },
  mid: { label: '中等', cls: 'bg-warning-soft text-warning' },
  low: { label: '轻微', cls: 'bg-muted text-muted-foreground' },
}

/**
 * v0.10 同人章节检查面板：OOC 检查（任务）+ 原著重合检查（同步）。
 * 只在同人书（book.fanfic 非空）的章节里挂载；原创书调用接口会 400。
 * onLocate：点问题原句时回调（可用于在编辑器里定位/高亮），不传则不显示定位按钮。
 */
export function FanficChapterPanel({ chapterId, bookId, onLocate, className }: {
  chapterId: number; bookId?: number; onLocate?: (quote: string) => void; className?: string
}) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const key = `fanfic-ooc:${chapterId}`
  const running = useActiveJob(key)
  const q = useQuery({ queryKey: fqk.chapter(chapterId), queryFn: () => fanficApi.chapterOoc(chapterId), enabled: chapterId > 0 })
  const overlap = useMutation({
    mutationFn: () => fanficApi.overlap(chapterId),
    meta: { errorTitle: '重合检查失败' },
    onSuccess: (r) => {
      qc.setQueryData(fqk.chapter(chapterId), (old: any) => ({ chapter_id: chapterId, ooc: old?.ooc ?? null, overlap: { ...r.overlap, stale: false } }))
      toast.success(r.overlap.level === 'ok' ? '没有发现与原著重合的片段' : `重合检查完成：${OVERLAP_LABEL[r.overlap.level]}`)
    },
  })
  const runOoc = () => start(fanficApi.oocCheck(chapterId), {
    label: 'OOC 检查', key,
    successMsg: (j) => { const o = j.result?.ooc as OocResult | undefined; return o ? `OOC 检查完成：${o.overall} 分 · ${LEVEL_LABEL[o.verdict]}` : 'OOC 检查完成' },
    onSuccess: () => qc.invalidateQueries({ queryKey: fqk.chapter(chapterId) }),
  })
  void bookId

  const ooc = q.data?.ooc ?? null
  const ov = q.data?.overlap ?? null
  return (
    <div className={cn('min-w-0 space-y-3', className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <h3 className="flex min-w-0 flex-1 items-center gap-1.5 text-[14px] font-semibold"><ShieldCheck className="h-4 w-4 shrink-0 text-primary" />同人检查</h3>
        <Button variant="soft" className="h-10" disabled={!!running} icon={<Sparkles className="h-4 w-4" />} onClick={() => void runOoc()}>{ooc ? '重新 OOC 检查' : 'OOC 检查'}</Button>
        <Button className="h-10" loading={overlap.isPending} icon={<RefreshCw className="h-4 w-4" />} onClick={() => overlap.mutate()}>原著重合</Button>
      </div>
      {running && <JobInline job={running} />}
      {q.isLoading ? <Skeleton className="h-24 rounded-xl" /> : q.isError ? (
        <p className="rounded-lg bg-subtle px-3 py-2 text-[12.5px] text-muted-foreground">{(q.error as any)?.message ?? '读取检查结果失败'}</p>
      ) : (
        <>
          {ooc ? <OocView ooc={ooc} onLocate={onLocate} onRerun={() => void runOoc()} rerunDisabled={!!running} /> : (
            <p className="rounded-xl border border-dashed px-3 py-4 text-center text-[12.5px] text-muted-foreground">还没做过 OOC 检查。会逐个比对本章出场的原著角色：言行、口癖、关系、能力边界、时间线。</p>
          )}
          {ov && <OverlapView ov={ov} onLocate={onLocate} />}
        </>
      )}
    </div>
  )
}

function OocView({ ooc, onLocate, onRerun, rerunDisabled }: { ooc: OocResult; onLocate?: (q: string) => void; onRerun: () => void; rerunDisabled: boolean }) {
  return (
    <div className="min-w-0 rounded-xl border bg-surface">
      {ooc.stale && (
        <div className="flex flex-wrap items-center gap-2 rounded-t-xl border-b bg-warning-soft px-3 py-2 text-[12.5px] text-warning">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" /><span className="min-w-0 flex-1">正文在检查后改过，结果可能已过期</span>
          <button type="button" disabled={rerunDisabled} onClick={onRerun} className="focus-ring inline-flex h-10 items-center rounded-md px-2 font-medium underline-offset-2 hover:underline disabled:opacity-50">重新检查</button>
        </div>
      )}
      <div className="flex min-w-0 items-center gap-3 px-3 py-3">
        <div className={cn('num flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-[17px] font-semibold',
          ooc.verdict === 'pass' ? 'bg-success-soft text-success' : ooc.verdict === 'warn' ? 'bg-warning-soft text-warning' : 'bg-danger-soft text-danger')}>{ooc.overall}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={LEVEL_TONE[ooc.verdict]}>{LEVEL_LABEL[ooc.verdict]}</Badge>
            <span className="text-[12px] text-muted-foreground">{ooc.fidelity_label} · 通过线 {ooc.pass_score}</span>
          </div>
          <div className="mt-0.5 text-[11.5px] text-muted-foreground">{fmtDateTime(ooc.checked_at)}{ooc.ignored_issues > 0 && ` · 按遵循度忽略 ${ooc.ignored_issues} 条`}</div>
        </div>
      </div>
      {ooc.summary && <p className="border-t px-3 py-2 text-[12.5px] leading-relaxed text-foreground/85">{ooc.summary}</p>}
      {ooc.characters.length ? (
        <ul className="divide-y border-t">{ooc.characters.map((c) => <CharRow key={c.name} c={c} onLocate={onLocate} />)}</ul>
      ) : <p className="border-t px-3 py-3 text-[12.5px] text-muted-foreground">本章没有出场的原著角色</p>}
    </div>
  )
}

function CharRow({ c, onLocate }: { c: OocCharacter; onLocate?: (q: string) => void }) {
  const [open, setOpen] = useState(c.level !== 'pass' && c.issues.length > 0)
  return (
    <li className="min-w-0">
      <button type="button" onClick={() => setOpen((x) => !x)} aria-expanded={open} disabled={!c.issues.length}
        className="focus-ring flex min-h-[48px] w-full min-w-0 items-center gap-2 px-3 py-2 text-left disabled:cursor-default">
        <span className="min-w-0 flex-1">
          <span className="flex min-w-0 items-center gap-1.5"><span className="truncate text-[13.5px] font-semibold">{c.name}</span><Badge tone={LEVEL_TONE[c.level]}>{LEVEL_LABEL[c.level]}</Badge></span>
          {c.verdict && <span className="mt-0.5 block truncate text-[12px] text-muted-foreground">{c.verdict}</span>}
        </span>
        <span className="num shrink-0 text-[15px] font-semibold">{c.score}</span>
        {c.issues.length > 0 && <span className="flex shrink-0 items-center gap-0.5 text-[12px] text-muted-foreground">{c.issues.length}<ChevronDown className={cn('h-3.5 w-3.5 transition', open && 'rotate-180')} /></span>}
      </button>
      {open && c.issues.length > 0 && (
        <ul className="space-y-2 px-3 pb-3">
          {c.issues.map((it, i) => (
            <li key={i} className="min-w-0 rounded-lg bg-subtle px-3 py-2 text-[12.5px] leading-relaxed">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className={cn('rounded px-1.5 text-[11px] leading-[18px]', SEV[it.severity]?.cls)}>{SEV[it.severity]?.label ?? it.severity}</span>
                <span className="font-medium">{it.type_label}</span>
                {it.source === 'program' && <span className="text-[11px] text-muted-foreground">程序检查</span>}
              </div>
              {it.quote && (
                onLocate ? (
                  <button type="button" onClick={() => onLocate(it.quote)} className="focus-ring mt-1 flex min-h-[40px] w-full min-w-0 items-start gap-1 rounded-md px-1 text-left text-foreground/75 hover:bg-background">
                    <Quote className="mt-1 h-3 w-3 shrink-0" /><span className="min-w-0 break-words">{it.quote}</span>
                  </button>
                ) : <p className="mt-1 flex gap-1 break-words text-foreground/75"><Quote className="mt-1 h-3 w-3 shrink-0" /><span className="min-w-0">{it.quote}</span></p>
              )}
              {it.problem && <p className="mt-1 break-words">{it.problem}</p>}
              {it.suggestion && <p className="mt-0.5 break-words text-primary">建议：{it.suggestion}</p>}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}

function OverlapView({ ov, onLocate }: { ov: FanficOverlap; onLocate?: (q: string) => void }) {
  return (
    <div className="min-w-0 rounded-xl border bg-surface p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[13px] font-semibold">原著重合</span>
        <Badge tone={OVERLAP_TONE[ov.level]}>{OVERLAP_LABEL[ov.level]}</Badge>
        {ov.stale && <Badge tone="warning">正文已改，可能过期</Badge>}
        <span className="num ml-auto text-[11.5px] text-muted-foreground">{fmtDateTime(ov.checked_at)}</span>
      </div>
      <div className="num mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-muted-foreground">
        <span>占比 {(ov.ratio * 100).toFixed(2)}%</span><span>重合片段 {ov.segments}</span><span>最长 {ov.longest} 字</span><span>按 {ov.ngram} 字比对</span>
      </div>
      {ov.warning && <p className="mt-2 flex gap-1.5 text-[12.5px] text-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words">{ov.warning}</span></p>}
      {ov.samples?.length > 0 && (
        <ul className="mt-2 space-y-1">
          {ov.samples.map((s, i) => (
            <li key={i}>
              {onLocate ? (
                <button type="button" onClick={() => onLocate(s)} className="focus-ring flex min-h-[40px] w-full min-w-0 items-start gap-1 rounded-md bg-subtle px-2 py-1.5 text-left text-[12.5px] hover:bg-muted"><Quote className="mt-1 h-3 w-3 shrink-0" /><span className="min-w-0 break-words">{s}</span></button>
              ) : <p className="flex gap-1 rounded-md bg-subtle px-2 py-1.5 text-[12.5px]"><Quote className="mt-1 h-3 w-3 shrink-0" /><span className="min-w-0 break-words">{s}</span></p>}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground">口癖与角色名不计入；只比对指纹，不保存原文。</p>
    </div>
  )
}

export default FanficChapterPanel
