import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  ArrowRight, BookOpenCheck, Check, CircleDashed, Download, FileText, Layers, Lightbulb, ListTree, Package, Pencil, PenLine, Waypoints, X,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Dialog, DialogContent } from '@/components/ui/dialog'
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
import type { Book, BookStatus } from '@/lib/types'
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
            <h1 className="text-[26px] font-semibold tracking-tight">{book.title}</h1>
            <StageBadge status={book.status} />
          </div>
          <div className="mt-1 text-[13px] text-muted-foreground">{book.genre} · {book.gender === 'male' ? '男频' : '女频'} · 创建于 {fmtTime(book.created_at)}</div>
          {book.tagline && <p className="mt-3 max-w-2xl text-[14px] leading-relaxed text-foreground/85">{book.tagline}</p>}
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
                  <div className="mt-0.5 hidden text-[11.5px] text-muted-foreground lg:block">{s.desc}</div>
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
        <Link to={`/books/${id}/foreshadows`}><Stat className="transition hover:shadow-lift" label="开放伏笔" icon={<Waypoints className="h-3.5 w-3.5" />} value={book.stats.foreshadow_open} sub="埋下待回收的线索" /></Link>
        <Stat label="最近更新" icon={<CircleDashed className="h-3.5 w-3.5" />} value={<span className="text-[18px]">{fmtTime(book.updated_at)}</span>} sub={STAGES[cur].label + '阶段'} />
      </div>

      <Card className="mt-6">
        <CardHeader title="本书任务" desc="生成类任务的历史与进度" />
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
      secondary: <Link to={`/books/${id}/package`}><Button>发布前须知</Button></Link>,
    },
  ]
  const c = cfg[stage]
  return (
    <motion.div key={stage} initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mt-4 border-t bg-subtle/60 px-5 py-5 md:px-6">
      <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div className="max-w-xl">
          <div className="text-[15px] font-semibold">{c.title}</div>
          <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{c.desc}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">{c.main}{c.secondary}</div>
      </div>
      {c.job && <JobInline job={c.job} className="mt-4" />}
      {advanceBtn && <div className="mt-3 flex justify-end">{advanceBtn}</div>}
    </motion.div>
  )
}

function EditBookDialog({ book, open, onOpenChange }: { book: Book; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [f, setF] = useState({ title: book.title, tagline: book.tagline, target_words: book.target_words, chapter_words: book.chapter_words })
  useEffect(() => { if (open) setF({ title: book.title, tagline: book.tagline, target_words: book.target_words, chapter_words: book.chapter_words }) }, [open, book])
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: () => api.updateBook(book.id, f),
    meta: { errorTitle: '保存失败' },
    onSuccess: (b) => { qc.setQueryData(qk.book(book.id), b); qc.invalidateQueries({ queryKey: ['books'] }); toast.success('已保存'); onOpenChange(false) },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="编辑作品信息" footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>取消</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>保存</Button></>}>
        <div className="space-y-4">
          <Field label="书名"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="一句话简介"><Textarea value={f.tagline} onChange={(e) => setF({ ...f, tagline: e.target.value })} className="min-h-[64px]" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="目标总字数"><Input type="number" step={10000} value={f.target_words} onChange={(e) => setF({ ...f, target_words: Number(e.target.value) })} /></Field>
            <Field label="每章字数"><Input type="number" step={100} value={f.chapter_words} onChange={(e) => setF({ ...f, chapter_words: Number(e.target.value) })} /></Field>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
