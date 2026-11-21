import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Brain, Check, Clock, FilmSlate, Lightbulb, X } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { EmptyState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { Tile } from '@/components/wanben/bits'
import { useKindJob } from '@/hooks/useKindJob'
import { checkApi, wqk } from '@/lib/api'
import { useJobs } from '@/lib/jobs'
import type { AdaptDim, AdaptReport } from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

const DIMS: AdaptDim[] = ['persona', 'conflict', 'reversal', 'shootability', 'dialogue', 'episodes']
const pct = (v: number) => `${Math.round(v * 100)}%`

/** 短剧可改编度：章号范围发起；六维定性评语、每章可切集数、改编建议与历史 */
export function AdaptPanel({ bookId, maxChapter }: { bookId: number; maxChapter: number }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const [a, setA] = useState('')
  const [b, setB] = useState('')
  const [llm, setLlm] = useState(true)
  const [jobId, setJobId] = useState<number | undefined>()
  const key = `adapt:${bookId}`
  const { active } = useKindJob(bookId, 'adaptability', key, '短剧可改编度')
  const rep = useQuery({ queryKey: wqk.adapt(bookId, jobId), queryFn: () => checkApi.adapt(bookId, jobId) })
  const hist = useQuery({ queryKey: wqk.adaptHistory(bookId), queryFn: () => checkApi.adaptHistory(bookId) })
  const sa = Number(a) || undefined, sb = Number(b) || undefined
  const bad = !!(sa && sb && sa > sb)
  const run = () => start(checkApi.startAdapt(bookId, { start: sa, end: sb, llm }), {
    key, label: '短剧可改编度', successMsg: () => '短剧可改编度审读完成',
    onSuccess: () => { setJobId(undefined); qc.invalidateQueries({ queryKey: ['adaptability', bookId] }) },
  })
  const r = rep.data?.report

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader icon={<FilmSlate />} title="短剧可改编度" desc="人设、冲突、反转、可拍性、对白、每章可切集数六维审读" />
        <CardBody className="space-y-3 p-4 sm:p-5">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="章号范围" hint="留空为全书" className="min-w-0">
              <div className="flex items-center gap-1.5">
                <Input type="number" min={1} inputMode="numeric" value={a} onChange={(e) => setA(e.target.value)} placeholder="1" className="h-10 w-20 text-center num" aria-label="起始章号" />
                <span className="text-muted-foreground">–</span>
                <Input type="number" min={1} inputMode="numeric" value={b} onChange={(e) => setB(e.target.value)} placeholder={String(Math.max(1, maxChapter))} className="h-10 w-20 text-center num" aria-label="结束章号" />
              </div>
            </Field>
            <label className="flex min-h-[44px] flex-1 basis-[200px] cursor-pointer items-center justify-between gap-3 rounded-xl px-3.5 py-2 hairline">
              <span className="flex items-center gap-1.5 text-[13.5px] font-medium"><Brain className="h-4 w-4 text-primary" />模型审读（关掉只用规则）</span>
              <Switch checked={llm} onCheckedChange={setLlm} />
            </label>
            <Button variant="primary" className="h-11 px-6" loading={!!active} disabled={bad} onClick={() => void run()}>开始审读</Button>
          </div>
          {bad && <p className="text-[12.5px] text-danger">起始章号不能大于结束章号</p>}
          {active && <JobInline job={active} />}
          {!!hist.data?.items.length && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="flex items-center gap-1 text-[12px] text-muted-foreground"><Clock className="h-3.5 w-3.5" />历史</span>
              <div className="w-full min-w-0 sm:w-[340px]">
                <Select value={String(jobId ?? hist.data.items[0].job_id)} onChange={(v) => setJobId(v && Number(v) !== hist.data!.items[0].job_id ? Number(v) : undefined)}
                  options={hist.data.items.map((h, i) => ({ value: String(h.job_id), label: `${fmtDateTime(h.updated_at)}${h.range ? ` · 第${h.range.start}–${h.range.end}章` : ''}${i === 0 ? '（最新）' : ''}` }))} />
              </div>
            </div>
          )}
        </CardBody>
      </Card>
      {rep.isLoading ? <Skeleton className="h-72 rounded-xl" /> : !r ? (
        <EmptyState kind="book" title="还没有审读过" desc="选一段章节（例如开篇 10 章）看看改编竖屏短剧的潜力。" />
      ) : <AdaptView bookId={bookId} r={r} />}
    </div>
  )
}

function AdaptView({ bookId, r }: { bookId: number; r: AdaptReport }) {
  const notes = new Map(r.chapter_notes.map((n) => [n.chapter, n]))
  return (
    <>
      <Card className="overflow-hidden">
        <div className="space-y-4 p-4 sm:p-5">
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3">
            <Tile label="每章可切" value={`${r.episodes_per_chapter} 集`} sub={`共约 ${r.episodes_total} 集`} />
            <Tile label="审读范围" value={`${r.range.chapters} 章`} sub={`第${r.range.start}–${r.range.end}章`} />
            <Tile label="改编建议" value={`${r.suggestions.length} 条`} sub="见下方明细" />
          </div>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {DIMS.map((d) => {
              const x = r.dimensions[d]
              if (!x) return null
              return (
                <div key={d} className="rounded-xl bg-subtle/50 px-3.5 py-2.5">
                  <div className="text-[12.5px] font-medium">{x.label}</div>
                  {x.comment && <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{x.comment}</p>}
                </div>
              )
            })}
          </div>
          {!!r.persona_tags.length && <div className="flex flex-wrap gap-1.5">{r.persona_tags.map((t) => <Badge key={t} tone="primary">{t}</Badge>)}</div>}
        </div>
        {!!r.suggestions.length && (
          <div className="space-y-1.5 border-t bg-subtle/40 p-4 sm:p-5">
            <div className="mb-1 text-[12.5px] font-medium text-muted-foreground">改编建议</div>
            {r.suggestions.map((s, i) => <p key={i} className="flex gap-2 text-[13px] leading-relaxed"><Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" /><span className="min-w-0 break-words">{s}</span></p>)}
          </div>
        )}
      </Card>
      <Card>
        <CardHeader title="每章可切集数" desc="竖屏短剧每集 1–2 分钟，约 500–800 字原文的戏量" />
        <CardBody className="p-0">
          <div className="divide-y">
            {r.chapters.map((m) => {
              const n = notes.get(m.chapter)
              return (
                <div key={m.chapter} className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-4 py-2.5 sm:px-5">
                  <Link to={`/books/${bookId}/chapters/${m.chapter_id}`} className="num w-16 shrink-0 text-[13px] font-semibold hover:text-primary">第{m.chapter}章</Link>
                  <span className="num inline-flex h-7 shrink-0 items-center rounded-full bg-primary-soft px-2.5 text-[12.5px] font-semibold text-primary">{m.episodes} 集</span>
                  <span className="num flex min-w-0 flex-1 flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-muted-foreground">
                    <span>{fmtNum(m.words)} 字</span><span>对白 {pct(m.dialogue_ratio)}</span><span>冲突 {m.conflict_per_k}/千字</span><span>反转 {m.reversal_per_k}/千字</span><span>{m.scenes} 场</span>
                  </span>
                  <span className="flex shrink-0 gap-2 text-[12px]">
                    <span className={cn('inline-flex items-center gap-0.5', m.opening_ok ? 'text-success' : 'text-danger')}>{m.opening_ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}开场</span>
                    <span className={cn('inline-flex items-center gap-0.5', m.ending_cliff ? 'text-success' : 'text-danger')}>{m.ending_cliff ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}卡点</span>
                  </span>
                  {n?.note && <p className="w-full text-[12px] leading-relaxed text-foreground/75">{n.note}</p>}
                </div>
              )
            })}
          </div>
        </CardBody>
      </Card>
    </>
  )
}
