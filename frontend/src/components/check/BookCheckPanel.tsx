import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowUpRight, Brain, CheckCircle2, Clock, FileText, FlagCheckered, Stethoscope, Waypoints, Wand2 } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Sheet } from '@/components/ui/dialog'
import { ScoreRing, Skeleton } from '@/components/ui/misc'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Segmented } from '@/components/ui/tabs'
import { EmptyState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { DiffView } from '@/components/chapter/DiffView'
import { SevBadge, Tile } from '@/components/wanben/bits'
import { useKindJob } from '@/hooks/useKindJob'
import { api, checkApi, qk, wqk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { BookCheckIssue, BookCheckReport, BookCheckVerdict, Job, Severity } from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

const VERDICT: Record<BookCheckVerdict, { tone: 'success' | 'warning' | 'danger'; ring: string }> = {
  ready: { tone: 'success', ring: 'bg-success-soft text-success' },
  fix_first: { tone: 'warning', ring: 'bg-warning-soft text-warning' },
  not_ready: { tone: 'danger', ring: 'bg-danger-soft text-danger' },
}
const VERDICT_LABEL: Record<BookCheckVerdict, string> = { ready: '可以收尾', fix_first: '先修再收尾', not_ready: '还需大修' }
const FIX_LABEL: Record<string, string> = { set_title: '改标题', humanize: '去 AI 腔', thicken: '描写增厚', rewrite: '按建议改写' }
const isJob = (r: any): r is Job => !!r && typeof r.id === 'number' && typeof r.status === 'string' && typeof r.kind === 'string'

export function BookCheckPanel({ bookId }: { bookId: number }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const [llm, setLlm] = useState(true)
  const [jobId, setJobId] = useState<number | undefined>(undefined)
  const key = `book-check:${bookId}`
  const { active } = useKindJob(bookId, 'book_check', key, '整书体检')
  const rep = useQuery({ queryKey: wqk.bookCheck(bookId, jobId), queryFn: () => checkApi.bookCheck(bookId, jobId) })
  const hist = useQuery({ queryKey: wqk.bookCheckHistory(bookId), queryFn: () => checkApi.bookCheckHistory(bookId) })
  const run = () => start(checkApi.startBookCheck(bookId, llm), {
    key, label: '整书体检',
    successMsg: (j) => `体检完成：${j.result?.verdict_label ?? ''} ${j.result?.score ?? ''} 分`,
    onSuccess: () => { setJobId(undefined); qc.invalidateQueries({ queryKey: ['book-check', bookId] }) },
  })
  const r = rep.data?.report

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader icon={<Stethoscope />} title="整书体检" desc="只看内容质量：字数、短章、重复章、水化、数值、伏笔、断档、结局与主线" />
        <CardBody className="space-y-3 p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex min-h-[44px] flex-1 basis-[240px] cursor-pointer items-center justify-between gap-3 rounded-xl px-3.5 py-2 hairline">
              <span className="min-w-0"><span className="flex items-center gap-1.5 text-[13.5px] font-medium"><Brain className="h-4 w-4 text-primary" />用模型查连续性与结局</span><span className="block text-[12px] text-muted-foreground">人物状态、战力、时间线、主线、结局是否仓促；关掉只跑规则层（不调模型）</span></span>
              <Switch checked={llm} onCheckedChange={setLlm} />
            </label>
            <Button variant="primary" className="h-11 px-6" loading={!!active} icon={<Stethoscope className="h-4 w-4" />} onClick={() => void run()}>{r ? '重新体检' : '开始体检'}</Button>
          </div>
          {active && <JobInline job={active} />}
          {!!hist.data?.items.length && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <span className="flex items-center gap-1 text-[12px] text-muted-foreground"><Clock className="h-3.5 w-3.5" />历史</span>
              <div className="w-full min-w-0 sm:w-[340px]">
                <Select value={String(jobId ?? hist.data.items[0].job_id)} onChange={(v) => setJobId(v && Number(v) !== hist.data!.items[0].job_id ? Number(v) : undefined)}
                  options={hist.data.items.map((h, i) => ({ value: String(h.job_id), label: `${fmtDateTime(h.updated_at)} · ${h.verdict ? VERDICT_LABEL[h.verdict] : '—'} ${h.score ?? ''} 分${h.llm_used ? '' : ' · 仅规则'}${i === 0 ? '（最新）' : ''}` }))} />
              </div>
            </div>
          )}
        </CardBody>
      </Card>

      {rep.isLoading ? <Skeleton className="h-64 rounded-xl" /> : !r ? (
        <EmptyState kind="book" title="还没有体检过" desc="写完（或写到一半）点「开始体检」，会给出结论、统计和可一键修的问题清单。" />
      ) : <ReportView bookId={bookId} r={r} />}
    </div>
  )
}

function ReportView({ bookId, r }: { bookId: number; r: BookCheckReport }) {
  const v = VERDICT[r.verdict] ?? VERDICT.fix_first
  const st = r.stats
  const end = st.ending
  const llmEnd = r.llm?.ending
  return (
    <>
      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-5 p-4 sm:p-5">
          <ScoreRing value={r.score} size={76} stroke={6} label="分" />
          <div className="min-w-0 flex-1 basis-[220px]">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn('inline-flex h-8 items-center rounded-full px-3.5 text-[14px] font-semibold', v.ring)}>{r.verdict_label || VERDICT_LABEL[r.verdict]}</span>
              {!r.llm?.used && <Badge tone="outline">仅规则层</Badge>}
            </div>
            <p className="num mt-1.5 text-[12.5px] text-muted-foreground">
              严重 {st.by_severity.high} · 中等 {st.by_severity.mid} · 轻微 {st.by_severity.low}{st.fixable ? ` · 可一键修 ${st.fixable}` : ''} · {fmtDateTime(r.checked_at)}
            </p>
            {r.llm?.summary && <p className="mt-2 text-[13px] leading-relaxed text-foreground/85">{r.llm.summary}</p>}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2.5 border-t bg-subtle/40 p-4 sm:grid-cols-3 sm:p-5">
          <Tile label="总字数" value={fmtNum(st.total_words)} sub={st.word_tier?.label?.replace(/^字数参考档位：/, '参考档位 ')} />
          <Tile label="章节" value={st.chapters} sub={`均 ${fmtNum(st.avg_words)} 字 · ${fmtNum(st.min_words)}–${fmtNum(st.max_words)}`} />
          <Tile label="短章" value={st.short_chapters} tone={st.short_chapters ? 'warning' : undefined} sub="少于 1000 字" />
          <Tile label="重复/近似章" value={st.duplicate_pairs?.length ?? 0} tone={st.duplicate_pairs?.length ? 'warning' : undefined} sub={st.duplicate_pairs?.[0] ? `如第 ${st.duplicate_pairs[0].chapters.join('/')} 章` : '没有'} />
          <Tile label="伏笔未回收" value={st.open_foreshadows} tone={st.open_foreshadows ? 'warning' : undefined} sub={<Link to={`/books/${bookId}/foreshadows`} className="text-primary hover:underline">去伏笔面板</Link>} />
          <Tile label="结局" value={end?.closed ? '已收束' : end?.cliff ? '停在悬念' : '未见收束'} tone={end?.closed ? 'success' : end?.cliff ? 'danger' : 'warning'}
            sub={llmEnd ? `${llmEnd.rushed ? '模型：结局仓促' : '模型：结局完整'} ${llmEnd.score}/10` : end?.last_chapter ? `末章第 ${end.last_chapter} 章` : undefined} />
        </div>
        {(llmEnd?.comment || r.llm?.mainline?.comment) && (
          <div className="grid gap-2.5 border-t p-4 sm:grid-cols-2 sm:p-5">
            {llmEnd?.comment && <p className="rounded-lg bg-subtle px-3 py-2.5 text-[12.5px] leading-relaxed"><span className="mr-1 inline-flex items-center gap-1 font-medium"><FlagCheckered className="h-3.5 w-3.5" />结局</span>{llmEnd.comment}</p>}
            {r.llm?.mainline?.comment && <p className="rounded-lg bg-subtle px-3 py-2.5 text-[12.5px] leading-relaxed"><span className="mr-1 inline-flex items-center gap-1 font-medium"><Waypoints className="h-3.5 w-3.5" />主线{r.llm.mainline.drift ? '（跑偏）' : ''}</span>{r.llm.mainline.comment}</p>}
          </div>
        )}
      </Card>
      <IssueList bookId={bookId} r={r} />
    </>
  )
}

function IssueList({ bookId, r }: { bookId: number; r: BookCheckReport }) {
  const [sev, setSev] = useState<'all' | Severity>('all')
  const [type, setType] = useState<string | null>(null)
  const [fixed, setFixed] = useState<Set<number>>(new Set())
  const types = useMemo(() => {
    const m = new Map<string, { label: string; n: number }>()
    for (const i of r.issues) m.set(i.type, { label: i.type_label, n: (m.get(i.type)?.n ?? 0) + 1 })
    return [...m.entries()].sort((a, b) => b[1].n - a[1].n)
  }, [r.issues])
  const list = r.issues.filter((i) => (sev === 'all' || i.severity === sev) && (!type || i.type === type))
  const cnt = (s: Severity) => r.issues.filter((i) => i.severity === s).length
  return (
    <Card>
      <CardHeader icon={<AlertTriangle />} title="问题清单" desc={`${r.issues.length} 条${r.stats.issues_truncated ? `（另有 ${r.stats.issues_truncated} 条未列出）` : ''}`} />
      <CardBody className="space-y-3 p-4 sm:p-5">
        <div className="flex flex-wrap items-center gap-2">
          <Segmented value={sev} onChange={setSev} options={[
            { value: 'all', label: `全部 ${r.issues.length}` }, { value: 'high', label: `严重 ${cnt('high')}` }, { value: 'mid', label: `中等 ${cnt('mid')}` }, { value: 'low', label: `轻微 ${cnt('low')}` },
          ]} />
          <div className="w-full min-w-0 sm:w-[220px]">
            <Select value={type} onChange={setType} allowEmpty emptyLabel="全部类型" placeholder="全部类型" options={types.map(([k, v]) => ({ value: k, label: `${v.label}（${v.n}）` }))} />
          </div>
        </div>
        {!list.length ? <p className="flex items-center justify-center gap-1.5 py-10 text-[13px] text-success"><CheckCircle2 className="h-4 w-4" />这个筛选下没有问题</p> : (
          <div className="space-y-2.5">{list.map((i) => <IssueCard key={i.id} bookId={bookId} i={i} fixed={fixed.has(i.id)} onFixed={() => setFixed((s) => new Set(s).add(i.id))} />)}</div>
        )}
      </CardBody>
    </Card>
  )
}

function IssueCard({ bookId, i, fixed, onFixed }: { bookId: number; i: BookCheckIssue; fixed: boolean; onFixed: () => void }) {
  const weak = i.layer === 'llm' && i.verified === false
  return (
    <div className={cn('rounded-xl bg-surface p-3.5 hairline transition', weak && 'border-dashed bg-subtle/40 opacity-70', fixed && 'opacity-60')}>
      <div className="flex flex-wrap items-center gap-1.5">
        <SevBadge s={i.severity} />
        <span className="text-[13.5px] font-semibold">{i.type_label}</span>
        {i.chapter != null && (i.chapter_id ? <Link to={`/books/${bookId}/chapters/${i.chapter_id}`} className="inline-flex h-7 items-center gap-0.5 rounded-md px-1.5 text-[12.5px] text-primary hover:bg-primary-soft/60">第{i.chapter}章<ArrowUpRight className="h-3 w-3" /></Link> : <span className="text-[12.5px] text-muted-foreground">第{i.chapter}章</span>)}
        {!!i.related_chapters.length && <span className="text-[12px] text-muted-foreground">关联第 {i.related_chapters.join('、')} 章</span>}
        <Badge tone="outline" className="ml-auto">{i.layer === 'llm' ? '模型' : '规则'}</Badge>
        {weak && <Badge tone="neutral" title="证据没能在正文或摘要里找到">证据未核实</Badge>}
        {fixed && <Badge tone="success">已处理</Badge>}
      </div>
      {i.evidence && <p className="mt-2 break-words border-l-2 border-border pl-2.5 font-serif text-[13px] leading-relaxed text-foreground/75">{i.evidence}</p>}
      <div className="mt-2 flex flex-wrap items-end gap-x-3 gap-y-2">
        <p className="min-w-0 flex-1 basis-[240px] break-words text-[12.5px] leading-relaxed"><span className="mr-1 font-medium text-primary">建议</span>{i.suggestion}</p>
        {i.fixable && i.fix && !fixed && <div className="ml-auto flex shrink-0 justify-end"><FixButton bookId={bookId} issue={i} onFixed={onFixed} /></div>}
      </div>
    </div>
  )
}

type Draft = { chapterId: number; before: string; after: string; label: string }

function FixButton({ bookId, issue, onFixed }: { bookId: number; issue: BookCheckIssue; onFixed: () => void }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const key = `check-fix:${issue.chapter_id}:${issue.fix?.action}`
  const job = useActiveJob(key)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [calling, setCalling] = useState(false)
  const cid = issue.chapter_id!
  const label = FIX_LABEL[issue.fix!.action] ?? '一键修'
  const after = async (res: Record<string, any> | null | undefined) => {
    const d = (res?.draft ?? res) as Record<string, any> | undefined
    if (d && typeof d.after === 'string') {
      if (d.changed === false || d.after === d.before) { toast.info('这一章没有需要改的地方'); onFixed(); return }
      let before = typeof d.before === 'string' ? d.before : ''
      if (!before) before = (await api.chapter(cid)).content ?? ''
      setDraft({ chapterId: cid, before, after: d.after, label: (typeof d.label === 'string' && d.label) || `整书体检·${label}前` })
      return
    }
    qc.invalidateQueries({ queryKey: qk.chapter(cid) })
    toast.success(`第 ${issue.chapter} 章已${label}`, { description: '可在章节页撤回' })
    onFixed()
  }
  const go = async () => {
    setCalling(true)
    try {
      const res = await checkApi.runFix(issue.fix!)
      if (isJob(res)) {
        await start(Promise.resolve(res), { key, label: `${label}（第${issue.chapter}章）`, silent: true, onSuccess: (j) => void after(j.result) })
      } else if (issue.fix!.action === 'set_title') {
        qc.invalidateQueries({ queryKey: qk.chapters(bookId) }); qc.invalidateQueries({ queryKey: qk.chapter(cid) })
        toast.success(`标题已改为「${res?.title ?? issue.fix!.body?.title ?? ''}」`); onFixed()
      } else await after(res)
    } catch (e: any) {
      toast.error(`${label}失败`, { description: e?.message })
    } finally { setCalling(false) }
  }
  const apply = useMutation({
    mutationFn: (c: string) => api.applyRewrite(draft!.chapterId, { content: c, label: draft!.label }),
    meta: { errorTitle: '写入失败' },
    onSuccess: (c) => { qc.setQueryData(qk.chapter(c.id), c); qc.invalidateQueries({ queryKey: qk.chapters(bookId) }); toast.success(`第 ${c.number} 章已更新`, { description: '旧正文进了历史，可在章节页撤回' }); setDraft(null); onFixed() },
  })
  return (
    <>
      {job ? <JobInline job={job} className="w-full" /> : (
        <Button size="sm" variant="soft" icon={issue.fix!.action === 'set_title' ? <FileText className="h-3.5 w-3.5" /> : <Wand2 className="h-3.5 w-3.5" />} loading={calling} onClick={() => void go()}>{label}</Button>
      )}
      <Sheet open={!!draft} onOpenChange={(o) => !o && setDraft(null)} width={1000} title={`第 ${issue.chapter} 章 · ${label}`} desc="逐段对比，确定后才写入正文">
        {draft && <div className="-mx-6 -my-5"><DiffView title={`${issue.type_label} · ${label}`} before={draft.before} after={draft.after} applying={apply.isPending} onApply={(c) => apply.mutate(c)} onClose={() => setDraft(null)} /></div>}
      </Sheet>
    </>
  )
}
