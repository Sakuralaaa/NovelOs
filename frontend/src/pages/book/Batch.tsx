import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Check, ChartBar, Search, StackSimple, StopSquare, TextAa } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Segmented } from '@/components/ui/tabs'
import { PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { IterationList } from '@/components/wanben/IterateCard'
import { parseRanges } from '@/components/wanben/bits'
import { SearchReplaceSheet, FreqList } from '@/components/chapter/ChapterTools'
import { useKindJob } from '@/hooks/useKindJob'
import { api, qk, v013Api } from '@/lib/api'
import { useJobs } from '@/lib/jobs'
import type { BatchOp, BatchResult, BatchRow } from '@/lib/types'
import { cn } from '@/lib/utils'

const OPS: { value: BatchOp; label: string }[] = [
  { value: 'humanize', label: '去 AI 味' }, { value: 'polish', label: '语感重塑' }, { value: 'format', label: '排版' },
  { value: 'review', label: '审稿' }, { value: 'aigc', label: 'AI 率检测' }, { value: 'titles', label: '起章名' },
]
const REWRITE: BatchOp[] = ['humanize', 'polish', 'format']
const KEY = (id: number) => `book-batch:${id}`
const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`)

export default function BatchPage() {
  const bookId = Number(useParams().bookId)
  const qc = useQueryClient()
  const { start } = useJobs()
  const chapters = useQuery({ queryKey: qk.chapters(bookId), queryFn: () => api.chapters(bookId) })
  const written = (chapters.data ?? []).filter((c) => c.words > 0)
  const maxN = written.reduce((m, c) => Math.max(m, c.number), 0)
  const [op, setOp] = useState<BatchOp>('humanize')
  const [range, setRange] = useState('')
  const [recheck, setRecheck] = useState(false)
  const [target, setTarget] = useState('50')
  const [rounds, setRounds] = useState(2)
  const [searchOpen, setSearchOpen] = useState(false)
  const { active, latest } = useKindJob(bookId, 'book_batch', KEY(bookId), '批量处理')
  const zq = useQuery({ queryKey: qk.zhuque, queryFn: api.zhuqueSettings, retry: false })
  const zqOk = !!zq.data?.zhuque_configured
  const rangeText = range.trim() || (maxN ? `1-${maxN}` : '')
  const ranges = parseRanges(rangeText)
  const n = ranges.reduce((k, [a, b]) => k + (b - a + 1), 0)
  const result = latest?.status === 'succeeded' ? (latest.result as BatchResult | null) : null
  const run = () => start(v013Api.batch(bookId, { op, ranges, options: REWRITE.includes(op) ? { recheck: recheck && zqOk, aigc_target: Number(target) / 100, max_rounds: recheck ? rounds : 1 } : {} }), {
    key: KEY(bookId), label: `批量${OPS.find((o) => o.value === op)?.label}`,
    successMsg: (j) => { const r = j.result as BatchResult | null; return r ? `完成 ${r.summary.ok ?? 0} 章${r.summary.failed ? `，失败 ${r.summary.failed} 章` : ''}${r.stopped ? '（已停止）' : ''}` : '完成' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['wanben', bookId] }); qc.invalidateQueries({ queryKey: qk.chapters(bookId) }) },
  })
  const stop = useMutation({ mutationFn: () => v013Api.stopBatch(bookId), meta: { errorTitle: '停止失败' }, onSuccess: (r) => toast.success(r.message) })
  const freq = useQuery({ queryKey: ['book-freq', bookId, rangeText], queryFn: () => { const [a, b] = ranges[0] ?? [undefined, undefined]; return v013Api.bookFreq(bookId, a, ranges.length === 1 ? b : undefined) }, enabled: false })

  return (
    <div className="page max-w-[1080px]">
      <PageHeader title="批量处理" actions={<Button icon={<Search className="h-4 w-4" />} onClick={() => setSearchOpen(true)}>查找替换</Button>} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-5">
          <Card>
            <CardHeader divider icon={<StackSimple />} title="按章节区间批量处理" />
            <CardBody className="space-y-4 p-4 sm:p-5">
              <Field label="操作"><Segmented block value={op} onChange={setOp} options={OPS} className="max-md:grid max-md:grid-cols-3" /></Field>
              <Field label="章节范围" hint={n ? `${n} 章` : undefined}>
                <Input value={range} onChange={(e) => setRange(e.target.value)} placeholder={maxN ? `1-${maxN}` : '如 1-20, 25'} className="h-10 num" />
              </Field>
              {REWRITE.includes(op) && (
                <div className="space-y-3 rounded-xl bg-subtle/60 p-3.5">
                  <label className="flex min-h-[40px] cursor-pointer items-center justify-between gap-3">
                    <span className="text-[13.5px] font-medium">改完自动复检 AI 率{!zqOk && <span className="ml-2 text-[12px] font-normal text-muted-foreground">未配置朱雀</span>}</span>
                    <Switch checked={recheck && zqOk} onCheckedChange={(v) => zqOk && setRecheck(v)} />
                  </label>
                  {recheck && zqOk && (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Field label="高于多少再改一轮（%）"><Input type="number" min={5} max={95} value={target} onChange={(e) => setTarget(e.target.value)} className="h-10 num" /></Field>
                      <Field label="最多轮数"><Segmented block value={String(rounds)} onChange={(v) => setRounds(Number(v))} options={[1, 2, 3].map((k) => ({ value: String(k), label: String(k) }))} /></Field>
                    </div>
                  )}
                </div>
              )}
              <div className="flex flex-wrap items-center justify-end gap-2">
                {active && <Button icon={<StopSquare className="h-4 w-4" />} loading={stop.isPending} onClick={() => stop.mutate()}>停止</Button>}
                <Button variant="primary" className="h-10" loading={!!active} disabled={!n || (op === 'aigc' && !zqOk)} onClick={() => void run()}>开始</Button>
              </div>
              {active && <JobInline job={active} />}
            </CardBody>
          </Card>

          {result && <ResultCard r={result} bookId={bookId} />}

          <Card>
            <CardBody className="p-4 sm:p-5"><IterationList bookId={bookId} methods={REWRITE} active={!!active} /></CardBody>
          </Card>
        </div>

        <Card className="h-fit">
          <CardHeader divider icon={<ChartBar />} title="高频词" action={<Button size="sm" variant="ghost" loading={freq.isFetching} onClick={() => void freq.refetch()}>统计</Button>} />
          <CardBody className="p-4">
            {freq.data ? <FreqList items={freq.data.items} /> : <p className="py-6 text-center text-[12.5px] text-muted-foreground">还没统计</p>}
          </CardBody>
        </Card>
      </div>
      <SearchReplaceSheet bookId={bookId} open={searchOpen} onOpenChange={setSearchOpen} />
    </div>
  )
}

function ResultCard({ r, bookId }: { r: BatchResult; bookId: number }) {
  const s = r.summary
  const qc = useQueryClient()
  const setTitle = useMutation({
    mutationFn: async ({ row, title }: { row: BatchRow; title: string }) => { const ch = await api.chapter(row.chapter_id); return api.saveChapter(row.chapter_id, { title, content: ch.content ?? "" }) },
    meta: { errorTitle: '改章名失败' },
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: qk.chapters(bookId) }); toast.success(`第 ${c.number} 章已改名`) },
  })
  const [used, setUsed] = useState<Record<number, string>>({})
  return (
    <Card>
      <CardHeader divider icon={<Check />} title={`上次：${r.op_label}`} desc={`${r.chapters} 章${r.stopped ? '（中途停止）' : ''}`} />
      <CardBody className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap gap-2 text-[12.5px]">
          <Badge tone="success">完成 {s.ok ?? 0}</Badge>
          {!!s.unchanged && <Badge tone="neutral">无改动 {s.unchanged}</Badge>}
          {!!s.failed && <Badge tone="danger">失败 {s.failed}</Badge>}
          {s.ai_before != null && <Badge tone="outline">AI 味 {s.ai_before} → {s.ai_after}</Badge>}
          {s.aigc_before != null && <Badge tone="outline">AI 率 {pct(s.aigc_before)} → {pct(s.aigc_after)}</Badge>}
          {s.avg_aigc != null && <Badge tone="outline">平均 AI 率 {pct(s.avg_aigc)}</Badge>}
          {!!s.pending && <Badge tone="primary">待采纳 {s.pending}</Badge>}
        </div>
        <div className="max-h-[420px] divide-y overflow-auto rounded-xl hairline">
          {r.rows.map((row) => (
            <div key={row.chapter_id} className={cn('px-3.5 py-2.5 text-[13px]', row.status === 'failed' && 'bg-danger-soft/40')}>
              <div className="flex flex-wrap items-center gap-2">
                <span className="num font-medium">第 {row.number} 章</span>
                {row.status === 'failed' && <span className="min-w-0 flex-1 truncate text-danger">{row.error}</span>}
                {row.status === 'unchanged' && <span className="text-muted-foreground">没有需要改的</span>}
                {row.aigc != null && <span className="num">AI 率 {pct(row.aigc)}</span>}
                {row.ai_before != null && <span className="num text-muted-foreground">AI 味 {row.ai_before} → {row.ai_after}</span>}
                {row.aigc_before != null && <span className="num text-muted-foreground">AI 率 {pct(row.aigc_before)} → {pct(row.aigc_after)}</span>}
                {row.adopted && <Badge tone="success">已采纳</Badge>}
              </div>
              {row.titles && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {row.titles.map((t) => (
                    <button key={t.title} type="button" disabled={setTitle.isPending}
                      onClick={() => { setUsed((u) => ({ ...u, [row.chapter_id]: t.title })); setTitle.mutate({ row, title: t.title }) }}
                      className={cn('inline-flex h-8 items-center gap-1 rounded-full border px-2.5 text-[12.5px] transition hover:border-primary/50',
                        used[row.chapter_id] === t.title && 'border-primary bg-primary-soft text-primary')}>
                      <TextAa className="h-3.5 w-3.5" />{t.title}<span className="num text-[11px] text-muted-foreground">{t.score}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </CardBody>
    </Card>
  )
}
