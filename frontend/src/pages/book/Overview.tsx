import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  AlertTriangle, ArrowRight, BookOpenCheck, Check, CircleDashed, Download, FileText, Layers, Lightbulb, ListTree, Package, Pencil, PenLine, RotateCcw, Waypoints, Wand2, X,
} from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { TagInput } from '@/components/ui/tag-input'
import { Badge } from '@/components/ui/badge'
import { AskBox, CompareRow, TropeAlert, useModelRoute } from '@/components/common/AiAsk'
import { ConflictReview } from '@/components/common/ConflictReview'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Progress, Skeleton, Stat } from '@/components/ui/misc'
import { BookCover, StageBadge } from '@/components/common/BookBits'
import { ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { BatchWriteButton, WriteNextButton } from '@/components/common/WriteActions'
import { BookCrumb } from './_shared'
import { useBook, useJobsList } from '@/hooks/queries'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Book, BookInfo, BookRevision, BookStatus, Impact, SyncResult } from '@/lib/types'
import { STAGES, cn, fmtNum, fmtTime, jobLabel, stageIndex } from '@/lib/utils'

const ICONS = [Lightbulb, Layers, ListTree, PenLine, Package, BookOpenCheck]

export default function BookOverview() {
  const id = useBookId()
  const { data: book, isLoading, error, refetch } = useBook(id)
  const { data: jobs } = useJobsList(id)
  const [sel, setSel] = useState<number | null>(null)
  const [edit, setEdit] = useState(false)

  useEffect(() => setSel(null), [book?.status])
  if (isLoading) return <div className="page"><Skeleton className="h-40 rounded-2xl" /><Skeleton className="mt-6 h-48 rounded-2xl" /></div>
  if (error || !book) return <div className="page"><ErrorState error={error} onRetry={refetch} /></div>

  const cur = stageIndex(book.status)
  const active = sel ?? cur
  const pct = Math.min(100, (book.stats.words / Math.max(1, book.target_words)) * 100)

  return (
    <div className="page">
      <BookCrumb bookId={id} />
      <div className="mt-3 flex flex-col gap-6 md:flex-row md:items-start">
        <BookCover book={book} className="w-[112px] shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="break-words text-[26px] font-semibold tracking-tight">{book.title}</h1>
            <StageBadge status={book.status} />
          </div>
          <div className="mt-1 text-[13px] text-muted-foreground">{book.genre} · {book.gender === 'male' ? '男频' : '女频'} · 创建于 {fmtTime(book.created_at)}</div>
          {book.tagline && <p className="mt-3 max-w-2xl break-words text-[14px] leading-relaxed text-foreground/85">{book.tagline}</p>}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" icon={<Pencil className="h-3.5 w-3.5" />} onClick={() => setEdit(true)}>编辑信息</Button>
            <Link to={`/books/${id}/chapters`}><Button size="sm" icon={<FileText className="h-3.5 w-3.5" />}>打开章节</Button></Link>
          </div>
        </div>
      </div>

      {/* 流水线 */}
      <Card className="mt-8 overflow-hidden">
        <div className="relative px-4 pb-2 pt-6 md:px-6">
          <div className="grid grid-cols-3 gap-y-5 md:grid-cols-6">
            {STAGES.map((s, i) => {
              const Icon = ICONS[i]
              const done = i < cur || book.status === 'done'
              const isCur = i === cur && book.status !== 'done'
              return (
                <button key={s.key} onClick={() => setSel(i)} className="group relative flex flex-col items-center px-1 text-center focus:outline-none">
                  {i > 0 && <div className={cn('absolute right-1/2 top-[19px] -z-0 hidden h-[2px] w-full md:block', i <= cur ? 'bg-primary/50' : 'bg-border')} />}
                  <div className={cn(
                    'relative z-10 flex h-10 w-10 items-center justify-center rounded-full border-2 transition',
                    done ? 'border-primary bg-primary text-primary-foreground' : isCur ? 'border-primary bg-surface text-primary shadow-glow' : 'border-border bg-surface text-muted-foreground',
                    active === i && 'ring-4 ring-primary/15',
                  )}>
                    {done ? <Check className="h-4.5 w-4.5" style={{ width: 18, height: 18 }} /> : <Icon className="h-[18px] w-[18px]" />}
                    {isCur && <span className="absolute -inset-1 animate-ping rounded-full border border-primary/30 [animation-duration:2.4s]" />}
                  </div>
                  <div className={cn('mt-2 text-[13px] font-medium', isCur ? 'text-primary' : active === i ? 'text-foreground' : 'text-foreground/75')}>{s.label}</div>
                </button>
              )
            })}
          </div>
        </div>
        <StageAction book={book} stage={active} isCurrent={active === cur} onDone={() => setSel(null)} />
      </Card>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="已写章节" icon={<FileText className="h-3.5 w-3.5" />} value={book.stats.chapters} sub={`每章约 ${fmtNum(book.chapter_words)} 字`} />
        <Stat label="总字数" icon={<PenLine className="h-3.5 w-3.5" />} value={fmtNum(book.stats.words)} sub={<span className="flex items-center gap-2"><Progress value={pct} className="h-1 w-16" />目标 {fmtNum(book.target_words)}</span>} />
        <Link to={`/books/${id}/foreshadows`} className="block h-full"><Stat className="card-hover" label="开放伏笔" icon={<Waypoints className="h-3.5 w-3.5" />} value={book.stats.foreshadow_open} /></Link>
        <Stat label="最近更新" icon={<CircleDashed className="h-3.5 w-3.5" />} value={<span className="text-[18px]">{fmtTime(book.updated_at)}</span>} sub={STAGES[cur].label + '阶段'} />
      </div>

      <Card className="mt-6">
        <CardHeader title="本书任务" />
        <CardBody className="px-3">
          {!jobs?.length ? <p className="py-8 text-center text-[13px] text-muted-foreground">还没有任务</p> : (
            <div className="divide-y divide-border/60">
              {jobs.slice(0, 8).map((j) => (
                <div key={j.id} className="flex items-center gap-3 px-2 py-2.5">
                  {j.status === 'succeeded' ? <Check className="h-4 w-4 shrink-0 text-success" /> : j.status === 'failed' ? <X className="h-4 w-4 shrink-0 text-danger" /> : <CircleDashed className="h-4 w-4 shrink-0 animate-spin text-primary" />}
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium">{jobLabel(j.kind)}</div>
                    <div className={cn('truncate text-xs', j.error ? 'text-danger' : 'text-muted-foreground')}>{j.error || j.message}</div>
                  </div>
                  {(j.status === 'running' || j.status === 'queued') && <Progress value={j.progress} className="w-28" />}
                  <span className="shrink-0 text-xs text-muted-foreground">{fmtTime(j.updated_at)}</span>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      <EditBookDialog book={book} open={edit} onOpenChange={setEdit} />
    </div>
  )
}

function StageAction({ book, stage, isCurrent, onDone }: { book: Book; stage: number; isCurrent: boolean; onDone: () => void }) {
  const id = book.id
  const nav = useNavigate()
  const qc = useQueryClient()
  const { start } = useJobs()
  const bibleJob = useActiveJob(`bible:${id}`)
  const outlineJob = useActiveJob(`outline:${id}`)
  const pkgJob = useActiveJob(`package:${id}`)
  const wj1 = useActiveJob(`write-next:${id}`)
  const wj2 = useActiveJob(`write-batch:${id}`)
  const writeJob = wj1 ?? wj2
  const [exporting, setExporting] = useState(false)

  const advance = useMutation({
    mutationFn: (status: BookStatus) => api.updateBook(id, { status }),
    meta: { errorTitle: '更新阶段失败' },
    onSuccess: (b) => { qc.setQueryData(qk.book(id), b); qc.invalidateQueries({ queryKey: ['books'] }); toast.success(`进入「${STAGES[stageIndex(b.status)].label}」阶段`); onDone() },
  })
  const nextStatus = STAGES[Math.min(stage + 1, STAGES.length - 1)].key
  const advanceBtn = isCurrent && stage < 5 && (
    <Button variant="ghost" onClick={() => advance.mutate(nextStatus)} loading={advance.isPending}>
      满意了，进入「{STAGES[stage + 1].label}」<ArrowRight className="h-4 w-4" />
    </Button>
  )

  const cfg: { title: string; desc: string; job?: ReturnType<typeof useActiveJob>; main: React.ReactNode; secondary?: React.ReactNode }[] = [
    {
      title: '选题已确定', desc: '这本书的题材与卖点已经定下来了。可以去选题页再看看其他点子。',
      main: <Button variant="primary" onClick={() => nav('/ideas')} icon={<Lightbulb className="h-4 w-4" />}>查看选题</Button>,
    },
    {
      title: '下一步：生成设定库', desc: 'AI 会根据选题生成世界观、力量体系、主要人物和势力。生成后可以逐张修改。',
      job: bibleJob,
      main: <Button variant="primary" loading={!!bibleJob} icon={<Layers className="h-4 w-4" />} onClick={() => start(api.generateBible(id), { key: `bible:${id}`, label: '生成设定' })}>生成设定</Button>,
      secondary: <Link to={`/books/${id}/bible`}><Button>打开设定库</Button></Link>,
    },
    {
      title: '下一步：生成大纲', desc: '先出总纲和分卷，再展开前两段剧情弧和章细纲。没有细纲不会写正文。',
      job: outlineJob,
      main: <Button variant="primary" loading={!!outlineJob} icon={<ListTree className="h-4 w-4" />} onClick={() => start(api.generateOutline(id), { key: `outline:${id}`, label: '生成大纲' })}>生成大纲</Button>,
      secondary: <Link to={`/books/${id}/outline`}><Button>打开大纲</Button></Link>,
    },
    {
      title: '下一步：写正文', desc: '每章自动经过：细纲 → 写作 → 一致性检查 → 审稿 → 人味修整。写完你可以再改。',
      job: writeJob,
      main: <WriteNextButton bookId={id} />,
      secondary: <><BatchWriteButton bookId={id} /><Link to={`/books/${id}/chapters`}><Button variant="ghost">打开章节</Button></Link></>,
    },
    {
      title: '下一步：包装', desc: '生成书名候选、简介、标签和封面。好的包装能显著提升点击率。',
      job: pkgJob,
      main: <Button variant="primary" loading={!!pkgJob} icon={<Package className="h-4 w-4" />} onClick={() => start(api.generatePackage(id), { key: `package:${id}`, label: '生成包装' })}>生成包装</Button>,
      secondary: <Link to={`/books/${id}/package`}><Button>打开包装页</Button></Link>,
    },
    {
      title: '最后一步：导出发布包', desc: '下载建书资料、分章 txt、封面和 AI 申报提示，然后在番茄作者后台人工上架，并如实勾选 AI 申报。',
      main: <Button variant="primary" loading={exporting} icon={<Download className="h-4 w-4" />} onClick={async () => {
        setExporting(true)
        try { await api.exportBook(id, `${book.title}-发布包.zip`); toast.success('发布包已开始下载') } catch (e: any) { toast.error('导出失败', { description: e.message }) } finally { setExporting(false) }
      }}>导出发布包</Button>,
      secondary: <Link to={`/books/${id}/package`}><Button>打开包装页</Button></Link>,
    },
  ]
  const c = cfg[stage]
  return (
    <motion.div key={stage} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 border-t bg-subtle/50 px-5 py-4 md:px-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="max-w-xl">
          <div className="break-words text-[15px] font-semibold">{c.title}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">{c.main}{c.secondary}{advanceBtn}</div>
      </div>
      {c.job && <JobInline job={c.job} className="mt-4" />}
    </motion.div>
  )
}

function EditBookDialog({ book, open, onOpenChange }: { book: Book; open: boolean; onOpenChange: (o: boolean) => void }) {
  const init = () => ({ title: book.title, tagline: book.tagline, premise: book.premise ?? '', target_words: book.target_words, chapter_words: book.chapter_words,
    tropes: (book.banned_tropes ?? []).map((t) => t.name) })
  const [f, setF] = useState(init)
  const [aiOpen, setAiOpen] = useState(false)
  useEffect(() => { if (open) setF(init()) }, [open, book]) // eslint-disable-line react-hooks/exhaustive-deps
  const qc = useQueryClient()
  const done = (b: Book, msg: string) => { qc.setQueryData(qk.book(book.id), b); qc.invalidateQueries({ queryKey: ['books'] }); toast.success(msg) }
  const m = useMutation({
    mutationFn: () => api.updateBook(book.id, {
      title: f.title, tagline: f.tagline, premise: f.premise, target_words: f.target_words, chapter_words: f.chapter_words,
      banned_tropes: f.tropes.map((t) => (book.banned_tropes ?? []).find((x) => x.name === t) ?? { name: t, keywords: [t] }),
    }),
    meta: { errorTitle: '保存失败' },
    onSuccess: (b) => { done(b, '已保存'); onOpenChange(false) },
  })
  const undo = useMutation({
    mutationFn: () => api.undoBook(book.id), meta: { errorTitle: '撤回失败' },
    onSuccess: (b) => { done(b, '已退回上一版'); setF({ ...f, title: b.title, tagline: b.tagline, premise: b.premise ?? '' }) },
  })
  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent wide title="编辑作品信息" footer={<>
          {!!book.versions && <Button variant="ghost" className="mr-auto" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={undo.isPending} onClick={() => undo.mutate()} title={book.last_instruction ? `撤回：${book.last_instruction}` : undefined}>撤回上一版</Button>}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>取消</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>保存</Button>
        </>}>
          <div className="space-y-4">
            <button type="button" onClick={() => { onOpenChange(false); setAiOpen(true) }}
              className="flex w-full items-center gap-3 rounded-xl bg-primary-soft/50 px-3.5 py-3 text-left transition hairline hover:bg-primary-soft">
              <Wand2 className="h-5 w-5 shrink-0 text-primary" />
              <span className="min-w-0 flex-1"><span className="block text-[13.5px] font-semibold">让 AI 改书名和简介</span><span className="block text-xs text-muted-foreground">写要求，预览对比后再采纳；会告诉你设定、大纲、正文里哪些地方受影响，可一键同步。</span></span>
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
            </button>
            <Field label="书名"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
            <Field label="一句话简介"><Textarea value={f.tagline} onChange={(e) => setF({ ...f, tagline: e.target.value })} className="min-h-[64px]" /></Field>
            <Field label="核心设定" hint="生成设定库、大纲时都会读它"><Textarea value={f.premise} onChange={(e) => setF({ ...f, premise: e.target.value })} className="min-h-[110px]" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="目标总字数"><Input type="number" step={10000} value={f.target_words} onChange={(e) => setF({ ...f, target_words: Number(e.target.value) })} /></Field>
              <Field label="每章字数"><Input type="number" step={100} value={f.chapter_words} onChange={(e) => setF({ ...f, chapter_words: Number(e.target.value) })} /></Field>
            </div>
            <Field label="本书额外禁用的套路" hint="全局列表在「设置」里改"><TagInput value={f.tropes} onChange={(v) => setF({ ...f, tropes: v })} placeholder="例如：赘婿、系统签到（回车添加，生成时避开，命中会标黄）" /></Field>
          </div>
        </DialogContent>
      </Dialog>
      <BookAiSheet book={book} open={aiOpen} onOpenChange={setAiOpen} />
    </>
  )
}

const LEVEL_LABEL: Record<string, string> = { book: '总纲', volume: '卷', arc: '弧', chapter: '章细纲' }

/** 作品信息让 AI 改：要求 → 对比预览 → 采纳（可撤回）→ 下游影响 → 跳过或交给 AI 同步到设定/大纲 */
function BookAiSheet({ book, open, onOpenChange }: { book: Book; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const storage = useModelRoute('novelos.book-route')
  const [ask, setAsk] = useState('')
  const [rev, setRev] = useState<BookRevision | null>(null)
  const [draft, setDraft] = useState<BookInfo | null>(null)
  const [step, setStep] = useState<'ask' | 'preview' | 'impact' | 'sync'>('ask')
  const [impact, setImpact] = useState<Impact | null>(null)
  const [targets, setTargets] = useState({ bible: true, outline: true })
  const [sync, setSync] = useState<SyncResult | null>(null)
  const [nodePick, setNodePick] = useState<Set<number>>(new Set())
  const [bibleDone, setBibleDone] = useState(false)
  const job = useActiveJob(`book-revise:${book.id}`)
  const syncJob = useActiveJob(`book-sync:${book.id}`)
  const reset = () => { setStep('ask'); setRev(null); setDraft(null); setImpact(null); setSync(null); setBibleDone(false) }

  const go = () => start(api.reviseBook(book.id, { instruction: ask.trim(), route: storage.model }), {
    key: `book-revise:${book.id}`, label: 'AI 改作品信息', silent: true,
    onSuccess: (j) => { const r = j.result as BookRevision; setRev(r); setDraft({ ...r.proposal }); setStep('preview') },
  })
  const adopt = useMutation({
    mutationFn: () => api.applyBookInfo(book.id, { ...draft!, instruction: rev!.instruction }),
    meta: { errorTitle: '采纳失败' },
    onSuccess: async (b) => {
      qc.setQueryData(qk.book(book.id), b); qc.invalidateQueries({ queryKey: ['books'] })
      toast.success('作品信息已更新', { description: '旧版本已保留，可在「编辑信息」里撤回' })
      const imp = rev!.terms.length ? await api.bookImpact(book.id, rev!.terms).catch(() => rev!.impact) : rev!.impact
      setImpact(imp); setStep('impact')
    },
  })
  const undo = useMutation({
    mutationFn: () => api.undoBook(book.id), meta: { errorTitle: '撤回失败' },
    onSuccess: (b) => { qc.setQueryData(qk.book(book.id), b); toast.success('已撤回这次修改'); reset() },
  })
  const runSync = () => start(api.syncBook(book.id, {
    instruction: rev!.instruction, terms: impact!.terms, replacements: rev!.replacements, route: storage.model,
    targets: (Object.keys(targets) as ('bible' | 'outline')[]).filter((k) => targets[k]),
  }), {
    key: `book-sync:${book.id}`, label: '同步到设定/大纲', silent: true,
    onSuccess: (j) => { const r = j.result as SyncResult; setSync(r); setNodePick(new Set(r.outline.items.map((x) => x.node_id))); setStep('sync') },
  })
  const applyNodes = useMutation({
    mutationFn: () => api.applyOutline(book.id, { instruction: rev!.instruction, items: sync!.outline.items.filter((x) => nodePick.has(x.node_id)).map((x) => ({ node_id: x.node_id, ...x.new })) }),
    meta: { errorTitle: '采纳失败' },
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: qk.outline(book.id) }); toast.success(`大纲已更新 ${r.updated} 处`, { description: '每个节点的旧版本都保留了，可在大纲里撤回' }); setSync((s) => s && { ...s, outline: { items: [] } }) },
  })

  const hasImpact = !!impact && impact.total > 0
  return (
    <Sheet open={open} onOpenChange={(o) => { onOpenChange(o); if (!o && step !== 'ask' && step !== 'preview') reset() }} width={820} title="让 AI 改作品信息"
      desc={step === 'ask' ? '写下你想怎么改，AI 给出新的书名、一句话简介和核心设定，你对比后再决定。' : step === 'preview' ? '还没有写入：可以再手改，满意了点「采纳」。' : step === 'impact' ? '已采纳。下面是还写着旧说法的地方。' : '同步建议：逐条确认后才写入。'}>
      {step === 'ask' && (
        <AskBox title="修改要求" storage={storage} value={ask} onChange={setAsk} onSubmit={go} job={job} submitLabel="生成修改"
          placeholder="例如：不要强调拳法，不要非叫『碎星神通』；简介突出主角当码头账房的反差" />
      )}

      {step === 'preview' && rev && draft && (
        <div className="space-y-4">
          {rev.change && <p className="rounded-lg bg-subtle px-3 py-2 text-[13px]">{rev.change}</p>}
          <CompareRow label="书名" before={rev.current.title} after={draft.title} onChange={(v) => setDraft({ ...draft, title: v })} />
          <CompareRow label="一句话简介" before={rev.current.tagline} after={draft.tagline} onChange={(v) => setDraft({ ...draft, tagline: v })} multiline />
          <CompareRow label="核心设定" before={rev.current.premise} after={draft.premise} onChange={(v) => setDraft({ ...draft, premise: v })} multiline />
          <TropeAlert hits={rev.trope_hits} />
          {rev.impact.total > 0 && (
            <div className="flex gap-2 rounded-lg bg-warning-soft px-3 py-2.5 text-[12.5px] leading-relaxed text-warning">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>改掉的说法（{rev.terms.map((t) => `「${t}」`).join('')}）在 {rev.impact.cards.length} 张设定卡、{rev.impact.outline.length} 个大纲节点、{rev.impact.chapters.length} 章正文里还在用。采纳后可以选择跳过，或者交给 AI 按同一要求同步设定和大纲。</span>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setStep('ask')}>重新提要求</Button>
            <Button variant="primary" icon={<Check className="h-4 w-4" />} loading={adopt.isPending} onClick={() => adopt.mutate()}>采纳</Button>
          </div>
        </div>
      )}

      {step === 'impact' && impact && (
        <div className="space-y-4">
          {!hasImpact ? (
            <p className="rounded-lg bg-success-soft px-3 py-3 text-[13px] text-success">设定库、大纲和正文里都没有用到被改掉的说法，不需要同步。</p>
          ) : <ImpactList impact={impact} bookId={book.id} />}
          {hasImpact && (impact.cards.length > 0 || impact.outline.length > 0) && (
            <div className="space-y-2.5 rounded-xl bg-primary-soft/40 p-3 hairline">
              <div className="text-[13px] font-semibold">交给 AI 按同一要求同步</div>
              <div className="flex flex-wrap gap-4 text-[13px]">
                <label className="flex items-center gap-1.5"><input type="checkbox" className="h-4 w-4 accent-primary" checked={targets.bible} disabled={!impact.cards.length} onChange={() => setTargets({ ...targets, bible: !targets.bible })} />设定库（{impact.cards.length} 张，走冲突审阅）</label>
                <label className="flex items-center gap-1.5"><input type="checkbox" className="h-4 w-4 accent-primary" checked={targets.outline} disabled={!impact.outline.length} onChange={() => setTargets({ ...targets, outline: !targets.outline })} />大纲（{impact.outline.length} 个节点，逐条勾选）</label>
              </div>
              {impact.chapters.length > 0 && <p className="text-xs text-muted-foreground">已写的正文不会自动改，可以到对应章节用「按要求改写」。</p>}
              {syncJob && <JobInline job={syncJob} />}
            </div>
          )}
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={undo.isPending} onClick={() => undo.mutate()}>撤回这次修改</Button>
            <Button variant={hasImpact ? 'ghost' : 'primary'} onClick={() => { onOpenChange(false); reset() }}>{hasImpact ? '跳过，以后再说' : '完成'}</Button>
            {hasImpact && (impact.cards.length > 0 || impact.outline.length > 0) && (
              <Button variant="primary" icon={<Wand2 className="h-4 w-4" />} loading={!!syncJob} disabled={!(targets.bible && impact.cards.length) && !(targets.outline && impact.outline.length)} onClick={runSync}>交给 AI 同步</Button>
            )}
          </div>
        </div>
      )}

      {step === 'sync' && sync && (
        <div className="space-y-8">
          {sync.bible && !bibleDone && sync.bible.items.length > 0 && (
            <section>
              <h3 className="mb-3 text-[15px] font-semibold">设定库</h3>
              <ConflictReview bookId={book.id} proposal={sync.bible} applyMode="sync" onDone={() => setBibleDone(true)} onCancel={() => setBibleDone(true)} />
            </section>
          )}
          {sync.outline.items.length > 0 && (
            <section>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-[15px] font-semibold">大纲 <span className="text-xs font-normal text-muted-foreground">勾选要采纳的</span></h3>
                <Button size="xs" variant="ghost" onClick={() => setNodePick(nodePick.size === sync.outline.items.length ? new Set() : new Set(sync.outline.items.map((x) => x.node_id)))}>{nodePick.size === sync.outline.items.length ? '全不选' : '全选'}</Button>
              </div>
              <div className="space-y-2.5">
                {sync.outline.items.map((x) => (
                  <label key={x.node_id} className={cn('flex cursor-pointer gap-2.5 rounded-xl bg-surface p-3 shadow-card hairline', !nodePick.has(x.node_id) && 'opacity-55')}>
                    <input type="checkbox" className="mt-1 h-4 w-4 accent-primary" checked={nodePick.has(x.node_id)} onChange={() => setNodePick((s) => { const n = new Set(s); n.has(x.node_id) ? n.delete(x.node_id) : n.add(x.node_id); return n })} />
                    <div className="min-w-0 flex-1 space-y-1.5 text-[13px]">
                      <div className="flex items-center gap-1.5"><Badge tone="outline" className="h-5 text-[11px]">{LEVEL_LABEL[x.level] ?? x.level}</Badge><span className="font-medium">{x.new.title}</span>{x.beats_changed && <span className="text-[11px] text-muted-foreground">（细纲节拍里的旧名也一起换）</span>}</div>
                      <div className="grid gap-2 md:grid-cols-2">
                        <p className="rounded-md bg-danger-soft/50 px-2.5 py-1.5 text-foreground/60">{x.old.summary || '（空）'}</p>
                        <p className="rounded-md bg-success-soft/60 px-2.5 py-1.5">{x.new.summary || '（空）'}</p>
                      </div>
                      {x.reason && <p className="text-xs text-muted-foreground">{x.reason}</p>}
                    </div>
                  </label>
                ))}
              </div>
              <div className="mt-3 flex justify-end"><Button variant="primary" loading={applyNodes.isPending} disabled={!nodePick.size} onClick={() => applyNodes.mutate()}>采纳 {nodePick.size} 处大纲修改</Button></div>
            </section>
          )}
          {sync.chapters.length > 0 && (
            <section>
              <h3 className="mb-2 text-[15px] font-semibold">正文 <span className="text-xs font-normal text-muted-foreground">不会自动改，点进去用「按要求改写」</span></h3>
              <div className="space-y-1.5">
                {sync.chapters.map((c) => (
                  <Link key={c.id} to={`/books/${book.id}/chapters/${c.id}`} onClick={() => onOpenChange(false)} className="flex items-center gap-2 rounded-lg bg-surface px-3 py-2 text-[13px] hairline hover:text-primary">
                    <span className="num shrink-0 text-muted-foreground">第{c.number}章</span><span className="min-w-0 flex-1 truncate">{c.title}</span><span className="shrink-0 text-xs text-muted-foreground">出现 {c.count} 次</span>
                  </Link>
                ))}
              </div>
            </section>
          )}
          {(!sync.bible || bibleDone || !sync.bible.items.length) && !sync.outline.items.length && (
            <div className="flex items-center justify-between rounded-lg bg-success-soft px-3 py-3 text-[13px] text-success">
              <span>同步处理完了{sync.chapters.length ? '，正文按需逐章改写即可' : ''}。</span>
              <Button size="sm" variant="ghost" onClick={() => { onOpenChange(false); reset() }}>完成</Button>
            </div>
          )}
        </div>
      )}
    </Sheet>
  )
}

function ImpactList({ impact, bookId }: { impact: Impact; bookId: number }) {
  const chip = (ts: string[]) => ts.map((t) => <span key={t} className="rounded bg-warning-soft px-1 text-[11px] text-warning">{t}</span>)
  return (
    <div className="space-y-4 text-[13px]">
      {impact.cards.length > 0 && (
        <div>
          <div className="mb-1.5 font-semibold">设定卡（{impact.cards.length}）</div>
          <div className="space-y-1.5">{impact.cards.map((c) => (
            <Link key={c.id} to={`/books/${bookId}/bible`} className="block rounded-lg bg-surface px-3 py-2 hairline hover:text-primary">
              <div className="flex items-center gap-1.5"><span className="font-medium">{c.name}</span>{chip(c.terms)}</div>
              <p className="truncate text-xs text-muted-foreground">{c.snippet}</p>
            </Link>))}</div>
        </div>
      )}
      {impact.outline.length > 0 && (
        <div>
          <div className="mb-1.5 font-semibold">大纲（{impact.outline.length}）</div>
          <div className="space-y-1.5">{impact.outline.map((n) => (
            <Link key={n.id} to={`/books/${bookId}/outline`} className="block rounded-lg bg-surface px-3 py-2 hairline hover:text-primary">
              <div className="flex items-center gap-1.5"><Badge tone="outline" className="h-5 text-[11px]">{LEVEL_LABEL[n.level] ?? n.level}</Badge><span className="truncate font-medium">{n.title}</span>{chip(n.terms)}</div>
              <p className="truncate text-xs text-muted-foreground">{n.snippet}</p>
            </Link>))}</div>
        </div>
      )}
      {impact.chapters.length > 0 && (
        <div>
          <div className="mb-1.5 font-semibold">已写章节（{impact.chapters.length}）</div>
          <div className="space-y-1.5">{impact.chapters.map((c) => (
            <Link key={c.id} to={`/books/${bookId}/chapters/${c.id}`} className="block rounded-lg bg-surface px-3 py-2 hairline hover:text-primary">
              <div className="flex items-center gap-1.5"><span className="num text-muted-foreground">第{c.number}章</span><span className="truncate font-medium">{c.title}</span>{chip(c.terms)}<span className="ml-auto shrink-0 text-xs text-muted-foreground">{c.count} 处</span></div>
              <p className="truncate text-xs text-muted-foreground">{c.snippet}</p>
            </Link>))}</div>
        </div>
      )}
    </div>
  )
}
