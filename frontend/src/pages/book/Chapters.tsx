import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCheck, ChevronLeft, CloudCheck, CloudUpload, Loader2, PanelRightClose, PanelRightOpen, PenLine, RotateCcw, RotateCw, Sparkles, Trash2, Type, Wand2, AlertCircle, Copy, Rows3,
} from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { Kbd, Skeleton } from '@/components/ui/misc'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Segmented } from '@/components/ui/tabs'
import { AskBox, useModelRoute } from '@/components/common/AiAsk'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tip } from '@/components/ui/tooltip'
import { EmptyState, ErrorState } from '@/components/common/States'
import { BatchWriteButton, WriteNextButton } from '@/components/common/WriteActions'
import { HighlightEditor, type EditorHandle, type Range } from '@/components/chapter/HighlightEditor'
import { ReviewPanel } from '@/components/chapter/ReviewPanel'
import { LintPanel, type LocalStats } from '@/components/chapter/LintPanel'
import { ChangesPanel } from '@/components/chapter/ChangesPanel'
import { DiffView } from '@/components/chapter/DiffView'
import { useBook } from '@/hooks/queries'
import { useBookId } from '@/hooks/useBookId'
import { useDebouncedCallback } from '@/hooks/useDebounced'
import { modKey, useHotkey } from '@/hooks/useHotkey'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import { analyzeText } from '@/lib/textAnalysis'
import type { Chapter, ChapterVariant } from '@/lib/types'
import { cn, countWords, fmtNum, fmtTime } from '@/lib/utils'

const STATUS: Record<Chapter['status'], { l: string; dot: string; tone: 'neutral' | 'warning' | 'success' }> = {
  draft: { l: '草稿', dot: 'bg-muted-foreground/50', tone: 'neutral' },
  reviewing: { l: '待提交', dot: 'bg-warning', tone: 'warning' },
  committed: { l: '已提交', dot: 'bg-success', tone: 'success' },
}

export default function Chapters() {
  const bookId = useBookId()
  const { chapterId } = useParams()
  const nav = useNavigate()
  const { data: book } = useBook(bookId)
  const list = useQuery({ queryKey: qk.chapters(bookId), queryFn: () => api.chapters(bookId) })
  const chapters = useMemo(() => [...(list.data ?? [])].sort((a, b) => a.number - b.number), [list.data])
  const cid = Number(chapterId) || 0

  useEffect(() => {
    if (!cid && chapters.length) {
      const pick = chapters.find((c) => c.status !== 'committed') ?? chapters[chapters.length - 1]
      nav(`/books/${bookId}/chapters/${pick.id}`, { replace: true })
    }
  }, [cid, chapters, bookId, nav])

  return (
    <div className="flex h-full min-h-0">
      {/* 章节列表 */}
      <aside className="hidden w-[216px] shrink-0 flex-col border-r bg-subtle/40 lg:flex">
        <div className="border-b px-3 py-3">
          <Link to={`/books/${bookId}`} className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ChevronLeft className="h-3.5 w-3.5" /><span className="truncate">{book?.title ?? '返回'}</span></Link>
          <div className="mt-2 flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold">章节</h2>
            <span className="num text-xs text-muted-foreground">{chapters.length} 章 · {fmtNum(chapters.reduce((n, c) => n + c.words, 0))} 字</span>
          </div>
          <WriteNextButton bookId={bookId} size="sm" className="mt-3 flex w-full [&>button:first-child]:flex-1" />
          <div className="mt-2 [&>button]:w-full"><BatchWriteButton bookId={bookId} size="sm" /></div>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {list.isLoading ? Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="mb-1.5 h-12" />) : chapters.map((c) => (
            <Link key={c.id} to={`/books/${bookId}/chapters/${c.id}`}
              className={cn('mb-0.5 flex items-start gap-2.5 rounded-lg px-2.5 py-2 transition', c.id === cid ? 'bg-surface shadow-card hairline' : 'hover:bg-foreground/[0.04]')}>
              <span className={cn('mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full', STATUS[c.status].dot)} />
              <div className="min-w-0 flex-1">
                <div className={cn('truncate text-[13px]', c.id === cid ? 'font-semibold' : 'font-medium text-foreground/85')}>
                  <span className="num mr-1 text-muted-foreground">{c.number}</span>{c.title.replace(/^第\d+章\s*/, '')}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className="num">{fmtNum(c.words)} 字</span>
                  {c.review && <span className="num">· {c.review.scores.overall} 分</span>}
                  {!!c.variants?.length && <span className="rounded bg-primary-soft px-1 text-primary">{c.variants.length} 版</span>}
                </div>
              </div>
            </Link>
          ))}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {list.error ? <div className="p-8"><ErrorState error={list.error} onRetry={() => list.refetch()} /></div>
          : !list.isLoading && !chapters.length ? (
            <div className="flex flex-1 items-center justify-center p-8">
              <EmptyState kind="chapter" className="w-full max-w-lg" title="还没有正文"
                action={<><WriteNextButton bookId={bookId} /><BatchWriteButton bookId={bookId} /></>} />
            </div>
          ) : cid ? <ChapterWorkspace key={cid} id={cid} bookId={bookId} chapters={chapters} />
          : <div className="p-8"><Skeleton className="h-10 w-72" /><Skeleton className="mt-6 h-[60vh]" /></div>}
      </div>
    </div>
  )
}

function ChapterWorkspace({ id, bookId, chapters }: { id: number; bookId: number; chapters: Chapter[] }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const { start } = useJobs()
  const q = useQuery({ queryKey: qk.chapter(id), queryFn: () => api.chapter(id) })
  const ch = q.data

  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [saveState, setSaveState] = useState<'saved' | 'dirty' | 'saving' | 'error'>('saved')
  const [savedAt, setSavedAt] = useState<string | null>(null)
  const dirty = useRef(false)
  const latest = useRef({ title: '', content: '' })
  latest.current = { title, content }

  const [serif, setSerif] = useState(() => localStorage.getItem('novelos-serif') === '1')
  const [panelOpen, setPanelOpen] = useState(() => localStorage.getItem('novelos-panel') !== '0')
  const [sheetOpen, setSheetOpen] = useState(false)
  const [tab, setTab] = useState('review')
  const [focusQuote, setFocusQuote] = useState<{ q: string; start: number; end: number } | null>(null)
  const [showBare, setShowBare] = useState(false)
  const [showSummary, setShowSummary] = useState(false)
  const [variantId, setVariantId] = useState<number | null>(null)
  const [diff, setDiff] = useState<{ title: string; before: string; after: string; kind?: 'rewrite' } | null>(null)
  const [rwOpen, setRwOpen] = useState(false)
  const [rwSel, setRwSel] = useState<{ start: number; end: number; text: string } | null>(null)
  const [confirmUndo, setConfirmUndo] = useState(false)

  const scroller = useRef<HTMLDivElement>(null)
  const editor = useRef<EditorHandle>(null)

  // 服务端数据 → 本地（未编辑时）
  useEffect(() => {
    if (!ch || dirty.current) return
    setTitle(ch.title)
    setContent(ch.content ?? '')
    setSavedAt(ch.updated_at)
  }, [ch])

  const variants = ch?.variants?.filter(Boolean) ?? []
  const hasVariants = variants.length > 0 && ch?.status === 'draft'
  useEffect(() => {
    if (hasVariants && variantId === null) {
      const best = [...variants].sort((a, b) => (b.review_overall ?? 0) - (a.review_overall ?? 0))[0]
      setVariantId(best?.id ?? null)
    }
  }, [hasVariants, variants, variantId])
  const curVariant: ChapterVariant | undefined = hasVariants ? variants.find((v) => v.id === variantId) : undefined

  const saveMut = useMutation({
    mutationFn: (b: { title: string; content: string }) => api.saveChapter(id, b),
    meta: { silent: true },
  })
  const save = useCallback(async () => {
    if (!dirty.current) return true
    const snap = { ...latest.current }
    setSaveState('saving')
    try {
      const res = await saveMut.mutateAsync(snap)
      if (latest.current.content === snap.content && latest.current.title === snap.title) { dirty.current = false; setSaveState('saved') } else setSaveState('dirty')
      setSavedAt(res?.updated_at ?? new Date().toISOString())
      qc.setQueryData(qk.chapter(id), (old: Chapter | undefined) => (old ? { ...old, ...res, content: snap.content, title: snap.title } : res))
      qc.invalidateQueries({ queryKey: qk.chapters(bookId) })
      return true
    } catch (e: any) {
      setSaveState('error')
      toast.error('自动保存失败', { description: e?.message ?? '稍后会重试，请勿关闭页面' })
      return false
    }
  }, [id, bookId, qc, saveMut])
  const debounced = useDebouncedCallback(() => { void save() }, 1500)

  const edit = (p: { title?: string; content?: string }) => {
    if (p.title !== undefined) setTitle(p.title)
    if (p.content !== undefined) { setContent(p.content); if (focusQuote) setFocusQuote(null) }
    dirty.current = true
    setSaveState('dirty')
    debounced()
  }

  useHotkey('mod+s', () => { debounced.cancel(); save().then((ok) => ok && toast.success('已保存', { duration: 1200 })) })
  // 离开章节时立即落盘
  useEffect(() => () => { if (dirty.current) void api.saveChapter(id, latest.current).then(() => qc.invalidateQueries({ queryKey: qk.chapters(bookId) })) }, [id, bookId, qc])
  useEffect(() => {
    const fn = (e: BeforeUnloadEvent) => { if (dirty.current) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', fn)
    return () => window.removeEventListener('beforeunload', fn)
  }, [])

  const reviewJob = useActiveJob(`review:${id}`)
  const humanizeJob = useActiveJob(`humanize:${id}`)
  const thickenJob = useActiveJob(`thicken:${id}`)
  const rewriteJob = useActiveJob(`rewrite:${id}`)
  const busy = !!(reviewJob || humanizeJob || thickenJob || rewriteJob)
  const rewriting = !!(humanizeJob || thickenJob || rewriteJob)

  const runRewrite = async (kind: 'humanize' | 'thicken') => {
    if (!(await save())) return
    const before = latest.current.content
    const label = kind === 'thicken' ? '描写增厚' : '人味修整'
    start(kind === 'thicken' ? api.thickenChapter(id) : api.humanizeChapter(id), {
      key: `${kind}:${id}`, label, silent: true,
      onSuccess: async () => {
        try {
          const fresh = await api.chapter(id)
          qc.setQueryData(qk.chapter(id), fresh)
          dirty.current = false
          setContent(fresh.content ?? '')
          setSaveState('saved')
          if ((fresh.content ?? '') !== before) setDiff({ title: `${label}完成 · 逐段对比`, before, after: fresh.content ?? '' })
          else toast.info(`${label}完成，这一章没有需要改的地方`)
        } catch { toast.success(`${label}完成`) }
      },
    })
  }
  const runReview = async () => {
    if (!(await save())) return
    start(api.reviewChapter(id), { key: `review:${id}`, label: '审稿', successMsg: '审稿完成', onSuccess: () => setTab('review') })
  }

  const openRewrite = () => {
    const sel = editor.current?.getSelection()
    const text = sel && sel.end > sel.start ? latest.current.content.slice(sel.start, sel.end) : ''
    setRwSel(text.trim() ? { start: sel!.start, end: sel!.end, text } : null)
    setRwOpen(true)
  }
  const runCustomRewrite = async (o: { instruction: string; scope: 'all' | 'selection'; route: string | null; autoReview: boolean }) => {
    if (!(await save())) return
    const sel = o.scope === 'selection' ? rwSel : null
    if (o.scope === 'selection' && (!sel || latest.current.content.slice(sel.start, sel.end) !== sel.text)) { toast.error('选中的文字变了，请重新选择'); return }
    setRwOpen(false)
    start(api.rewriteChapter(id, { instruction: o.instruction, route: o.route, scope: o.scope, ...(sel ? { start: sel.start, end: sel.end } : {}) }), {
      key: `rewrite:${id}`, label: '按要求改写', silent: true,
      onSuccess: (j) => {
        const r = j.result as any
        if (!r?.changed) { toast.info('改写稿和原文一样，没有可采纳的改动'); return }
        if (latest.current.content !== r.before) { toast.error('改写期间正文被改过，为免覆盖已丢弃这次改写稿，请重试'); return }
        autoReviewRef.current = o.autoReview
        setDiff({ title: `按要求改写${o.scope === 'selection' ? '（选中的文字）' : ''} · 逐段对比，确定后才写入`, before: r.before, after: r.after, kind: 'rewrite' })
      },
    })
  }
  const autoReviewRef = useRef(true)
  const applyRewrite = useMutation({
    mutationFn: (c: string) => api.applyRewrite(id, { content: c, label: '按要求改写前' }),
    meta: { errorTitle: '采纳改写失败' },
  })
  const undoMut = useMutation({
    mutationFn: () => api.undoChapter(id),
    meta: { errorTitle: '撤回失败' },
    onSuccess: (c) => {
      qc.setQueryData(qk.chapter(id), c); qc.invalidateQueries({ queryKey: qk.chapters(bookId) })
      dirty.current = false; setContent(c.content ?? ''); setTitle(c.title); setSaveState('saved'); setConfirmUndo(false)
      toast.success('已撤回到上一版正文')
    },
  })

  const applyDiff = useMutation({
    mutationFn: (c: string) => api.saveChapter(id, { title: latest.current.title, content: c }),
    meta: { errorTitle: '应用修改失败' },
  })
  const [confirmDel, setConfirmDel] = useState(false)
  const rmDraft = useMutation({
    mutationFn: () => api.deleteChapter(id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => {
      dirty.current = false
      setConfirmDel(false)
      qc.removeQueries({ queryKey: qk.chapter(id) })
      qc.invalidateQueries({ queryKey: qk.chapters(bookId) })
      qc.invalidateQueries({ queryKey: qk.outline(bookId) })
      toast.success('草稿已删除')
      nav(`/books/${bookId}/chapters`, { replace: true })
    },
  })
  // v0.7.1：提交要调一次模型生成摘要，改为后台任务（避免代理超时）；完成后刷新章节、伏笔
  const committing = !!useActiveJob(`commit:${id}`)
  const commit = useMutation({
    mutationFn: async () => {
      await save()
      return start(api.commitChapter(id), {
        key: `commit:${id}`, label: '提交入账',
        successMsg: (j) => `第 ${j.result?.number ?? ''} 章已提交入账`,
        onSuccess: (j) => {
          const c = j.result?.chapter as Chapter | undefined
          if (c) qc.setQueryData(qk.chapter(id), (old: Chapter | undefined) => ({ ...(old ?? c), ...c, content: old?.content ?? c.content }))
          qc.invalidateQueries({ queryKey: qk.chapters(bookId) }); qc.invalidateQueries({ queryKey: qk.book(bookId) }); qc.invalidateQueries({ queryKey: qk.foreshadows(bookId) })
        },
      })
    },
    meta: { errorTitle: '提交失败' },
  })
  const adopt = useMutation({
    mutationFn: (vid: number) => api.adoptVariant(id, vid),
    meta: { errorTitle: '采纳失败' },
    onSuccess: (c) => {
      qc.setQueryData(qk.chapter(id), c)
      qc.invalidateQueries({ queryKey: qk.chapters(bookId) })
      dirty.current = false
      setContent(c.content ?? ''); setTitle(c.title); setVariantId(null)
      toast.success('已采纳此版本，现在可以编辑了')
    },
  })

  // 文本分析 & 高亮
  const shown = curVariant ? curVariant.content || '' : content
  const analysis = useMemo(() => analyzeText(shown), [shown])
  const local: LocalStats = {
    avg_sentence_len: analysis.avg_sentence_len, short_sentence_ratio: analysis.short_sentence_ratio, bare_dialogue_ratio: analysis.bare_dialogue_ratio,
    summary_ratio: analysis.summary_ratio, dialogue_ratio: analysis.dialogue_ratio,
    bareCount: analysis.paras.filter((p) => p.kind === 'bare-dialogue').length, summaryCount: analysis.paras.filter((p) => p.kind === 'summary').length,
  }
  const ranges = useMemo<Range[]>(() => {
    const r: Range[] = []
    if (showBare) analysis.paras.filter((p) => p.kind === 'bare-dialogue').forEach((p) => r.push({ start: p.start, end: p.end, kind: 'bare' }))
    if (showSummary) analysis.paras.filter((p) => p.kind === 'summary').forEach((p) => r.push({ start: p.start, end: p.end, kind: 'summary' }))
    if (focusQuote) { const f = { start: focusQuote.start, end: focusQuote.end, kind: 'focus' as const }; return [...r.filter((x) => x.end <= f.start || x.start >= f.end), f] }
    return r
  }, [analysis, showBare, showSummary, focusQuote])

  const locateQuote = (quote: string) => {
    if (!quote) return
    const text = shown
    let idx = text.indexOf(quote), len = quote.length
    if (idx < 0) { const head = quote.replace(/[…。！？\s]+$/, '').slice(0, 14); idx = head ? text.indexOf(head) : -1; len = head.length }
    if (idx < 0) { toast.info('没在正文里找到这句', { description: '可能已经被修改过了' }); return }
    setFocusQuote({ q: quote, start: idx, end: idx + len })
    setSheetOpen(false)
    setTimeout(() => editor.current?.reveal(idx, idx + len), 30)
  }

  const words = countWords(shown)
  const lintForPanel = curVariant ? curVariant.lint : ch?.lint ?? null

  if (q.isLoading) return <div className="mx-auto w-full max-w-[720px] p-10"><Skeleton className="h-9 w-80" /><div className="mt-8 space-y-3">{Array.from({ length: 10 }).map((_, i) => <Skeleton key={i} className="h-5" />)}</div></div>
  if (q.error || !ch) return <div className="p-8"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>

  const panel = (
    <Tabs value={tab} onValueChange={setTab} className="flex h-full flex-col">
      <div className="border-b px-4 py-3"><TabsList className="w-full"><TabsTrigger value="review">审稿</TabsTrigger><TabsTrigger value="lint">人味</TabsTrigger><TabsTrigger value="changes">变更</TabsTrigger></TabsList></div>
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <TabsContent value="review" className="focus:outline-none"><ReviewPanel review={ch.review} onQuote={locateQuote} onReview={runReview} reviewing={!!reviewJob} activeQuote={focusQuote?.q} /></TabsContent>
        <TabsContent value="lint" className="focus:outline-none">
          <LintPanel lint={lintForPanel} local={local} showBare={showBare} showSummary={showSummary} onToggleBare={setShowBare} onToggleSummary={setShowSummary}
            onHumanize={() => runRewrite('humanize')} onThicken={() => runRewrite('thicken')} busy={busy || hasVariants} thickening={!!thickenJob} humanizing={!!humanizeJob} />
        </TabsContent>
        <TabsContent value="changes" className="focus:outline-none"><ChangesPanel changes={ch.changes} /></TabsContent>
      </div>
    </Tabs>
  )

  const runningJob = rewriteJob ?? thickenJob ?? humanizeJob ?? reviewJob

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 工具栏 */}
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b bg-background/85 px-4 py-2 backdrop-blur">
          <div className="flex min-w-0 items-center gap-2">
            <div className="w-[150px] lg:hidden">
              <Select value={String(id)} onChange={(v) => v && nav(`/books/${bookId}/chapters/${v}`)} options={chapters.map((c) => ({ value: String(c.id), label: `第${c.number}章 ${c.title.replace(/^第\d+章\s*/, '')}` }))} />
            </div>
            <Badge tone={STATUS[ch.status].tone} dot>{STATUS[ch.status].l}</Badge>
            <SaveIndicator state={saveState} at={savedAt} />
          </div>
          <div className="flex items-center gap-1">
            <Tip content="整理段落：段与段之间统一空一行"><Button size="icon-sm" variant="ghost" disabled={busy || hasVariants || rewriting || !!diff} onClick={() => {
              const fixed = content.replace(/\r\n/g, '\n').split('\n').map((l) => l.trim()).filter(Boolean).join('\n\n')
              if (fixed === content) { toast.info('段落格式已经是整齐的'); return }
              edit({ content: fixed }); toast.success('已整理段落', { description: '可随时手动再改' })
            }} aria-label="整理段落"><Rows3 className="h-4 w-4" /></Button></Tip>
            <Tip content={serif ? '切换为黑体' : '切换为宋体'}><Button size="icon-sm" variant="ghost" onClick={() => { setSerif(!serif); localStorage.setItem('novelos-serif', serif ? '0' : '1') }} aria-label="字体"><Type className="h-4 w-4" /></Button></Tip>
            <Button size="sm" variant="ghost" loading={!!reviewJob} disabled={busy || hasVariants} icon={<RotateCw className="h-3.5 w-3.5" />} onClick={runReview}><span className="hidden sm:inline">审稿</span></Button>
            <Button size="sm" variant="ghost" loading={!!humanizeJob} disabled={busy || hasVariants} icon={<Wand2 className="h-3.5 w-3.5" />} onClick={() => runRewrite('humanize')}><span className="hidden sm:inline">人味修整</span></Button>
            <Button size="sm" variant="ghost" loading={!!thickenJob} disabled={busy || hasVariants} icon={<Sparkles className="h-3.5 w-3.5" />} onClick={() => runRewrite('thicken')}><span className="hidden sm:inline">描写增厚</span></Button>
            <Tip content="写要求让 AI 改写全章或选中的文字，对比后再决定采纳"><Button size="sm" variant="ghost" loading={!!rewriteJob} disabled={busy || hasVariants || !!diff} icon={<PenLine className="h-3.5 w-3.5" />} onClick={openRewrite}><span className="hidden sm:inline">按要求改写</span></Button></Tip>
            {!!ch.history && !hasVariants && <Tip content={`撤回到「${ch.last_history_label || '上一版'}」的正文（共 ${ch.history} 个旧版本）`}><Button size="icon-sm" variant="ghost" disabled={busy || !!diff} onClick={() => setConfirmUndo(true)} aria-label="撤回"><RotateCcw className="h-4 w-4" /></Button></Tip>}
            <Dialog open={confirmUndo} onOpenChange={setConfirmUndo}>
              <DialogContent title="撤回到上一版正文？" desc={`恢复「${ch.last_history_label || '上一版'}」时的正文，之后的修改会丢掉。`}
                footer={<><Button variant="ghost" onClick={() => setConfirmUndo(false)}>取消</Button><Button variant="primary" loading={undoMut.isPending} onClick={() => undoMut.mutate()}>撤回</Button></>} />
            </Dialog>
            <RewriteDialog open={rwOpen} onOpenChange={setRwOpen} selection={rwSel} committed={ch.status === 'committed'} onSubmit={runCustomRewrite} />
            {ch.status !== 'committed' && <Tip content="删除草稿"><Button size="icon-sm" variant="ghost" disabled={busy} onClick={() => setConfirmDel(true)} aria-label="删除草稿" className="text-muted-foreground hover:text-danger"><Trash2 className="h-4 w-4" /></Button></Tip>}
            <Dialog open={confirmDel} onOpenChange={setConfirmDel}>
              <DialogContent title={`删除第 ${ch.number} 章草稿？`} desc="大纲会保留，之后可以重新写这一章。"
                footer={<><Button variant="ghost" onClick={() => setConfirmDel(false)}>取消</Button><Button variant="danger" loading={rmDraft.isPending} onClick={() => rmDraft.mutate()}>删除</Button></>} />
            </Dialog>
            <Tip content={hasVariants ? '先采纳一个版本' : ch.status === 'committed' ? '已提交，修改后可再次提交' : '确认本章，人物状态与伏笔写入底账'}>
              <span><Button size="sm" variant={ch.status === 'committed' ? 'secondary' : 'primary'} loading={commit.isPending || committing} disabled={busy || hasVariants || committing} icon={<CheckCheck className="h-3.5 w-3.5" />} onClick={() => commit.mutate()}><span className="hidden sm:inline">提交</span></Button></span>
            </Tip>
            <Tip content={panelOpen ? '收起面板' : '展开面板'}>
              <Button size="icon-sm" variant="ghost" className="hidden xl:inline-flex" onClick={() => { setPanelOpen(!panelOpen); localStorage.setItem('novelos-panel', panelOpen ? '0' : '1') }} aria-label="面板">
                {panelOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
              </Button>
            </Tip>
            <Button size="icon-sm" variant="ghost" className="xl:hidden" onClick={() => setSheetOpen(true)} aria-label="审稿面板"><PanelRightOpen className="h-4 w-4" /></Button>
          </div>
        </div>

        {diff ? (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <DiffView title={diff.title} before={diff.before} after={diff.after} applying={applyDiff.isPending || applyRewrite.isPending}
              onClose={() => { if (diff.kind === 'rewrite') toast.info('已丢弃改写稿，正文没有变'); setDiff(null) }}
              onApply={(c, s) => {
                if (diff.kind === 'rewrite') {
                  if (s.accepted === 0) { setDiff(null); toast.info('一处都没接受，正文没有变'); return }
                  applyRewrite.mutate(c, { onSuccess: (res) => {
                    qc.setQueryData(qk.chapter(id), res); qc.invalidateQueries({ queryKey: qk.chapters(bookId) })
                    dirty.current = false; setContent(res.content ?? c); setSaveState('saved'); setDiff(null)
                    toast.success(`已采纳 ${s.accepted} 处改写`, { description: '旧正文已保留，可点「撤回」恢复' })
                    if (autoReviewRef.current) start(api.reviewChapter(id), { key: `review:${id}`, label: '审稿', successMsg: '改写后审稿完成', onSuccess: () => setTab('review') })
                  } })
                  return
                }
                if (s.reverted === 0) { setDiff(null); toast.success(`已接受全部 ${s.accepted} 处修改`); return }
                applyDiff.mutate(c, { onSuccess: (res) => {
                  qc.setQueryData(qk.chapter(id), (old: Chapter | undefined) => ({ ...(old ?? res), ...res, content: c }))
                  dirty.current = false; setContent(c); setSaveState('saved'); setDiff(null)
                  toast.success(`已接受 ${s.accepted} 处，撤销 ${s.reverted} 处`)
                } })
              }} />
          </div>
        ) : (
          <div ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto">
            {runningJob && rewriting && (
              <div className="sticky top-0 z-10 flex items-center justify-center gap-2 bg-primary-soft/95 py-2 text-[12.5px] font-medium text-primary backdrop-blur">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />{runningJob.message || `${runningJob.label}中…`} {Math.round(runningJob.progress)}% · 完成后可逐段对比
              </div>
            )}
            <div className="mx-auto w-full max-w-[720px] px-6 pb-40 pt-8 md:px-10">
              {hasVariants && (
                <div className="mb-8 rounded-xl bg-gradient-to-br from-primary-soft to-surface p-4 hairline">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-1.5 text-[14px] font-semibold"><Copy className="h-4 w-4 text-primary" />这一章写了 {variants.length} 个版本</div>
                    </div>
                    <Button size="sm" variant="primary" loading={adopt.isPending} disabled={!curVariant} onClick={() => curVariant && adopt.mutate(curVariant.id)}>采纳此版</Button>
                  </div>
                  <div className="mt-3 grid gap-2" style={{ gridTemplateColumns: `repeat(${variants.length}, minmax(0,1fr))` }}>
                    {variants.map((v, i) => {
                      const best = Math.max(...variants.map((x) => x.review_overall ?? 0)) === (v.review_overall ?? -1)
                      return (
                        <button key={v.id} onClick={() => { setVariantId(v.id); setFocusQuote(null) }}
                          className={cn('relative rounded-lg px-3 py-2 text-left transition', v.id === variantId ? 'bg-surface shadow-card ring-2 ring-primary/50' : 'bg-surface/50 hairline hover:bg-surface')}>
                          <div className="flex items-center justify-between">
                            <span className="text-[13px] font-semibold">版本 {String.fromCharCode(65 + i)}</span>
                            {best && <span className="rounded bg-success-soft px-1.5 text-[10.5px] font-medium text-success">最高分</span>}
                          </div>
                          <div className="num mt-1 flex items-baseline gap-0.5"><span className="text-[20px] font-semibold leading-none">{v.review_overall ?? '—'}</span><span className="text-xs text-muted-foreground">分</span></div>
                          <div className="num mt-1 truncate text-[11.5px] text-muted-foreground">{fmtNum(v.words)} 字{v.lint ? ` · AI味 ${Math.round(v.lint.ai_score)}` : ''}</div>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
              <div className="num mb-2 text-[12.5px] font-medium text-muted-foreground">第 {ch.number} 章</div>
              <input value={title} onChange={(e) => edit({ title: e.target.value })} readOnly={hasVariants || rewriting} placeholder="章节标题"
                className="mb-6 w-full bg-transparent text-[26px] font-semibold tracking-tight outline-none placeholder:text-muted-foreground/50" />
              {hasVariants && curVariant && !curVariant.content ? (
                <p className="py-10 text-center text-sm text-muted-foreground">该版本内容未返回</p>
              ) : (
                <HighlightEditor ref={editor} scroller={scroller} value={shown} onChange={(v) => edit({ content: v })} ranges={ranges} readOnly={hasVariants || rewriting} serif={serif} placeholder="从这里开始写……" />
              )}
            </div>
          </div>
        )}

        <div className="flex shrink-0 items-center justify-between gap-3 border-t px-4 py-1.5 text-[11.5px] text-muted-foreground">
          <div className="num flex items-center gap-3">
            <span><b className="font-semibold text-foreground/80">{words.toLocaleString()}</b> 字</span>
            <span>{analysis.paras.length} 段</span>
            <span>约 {Math.max(1, Math.round(words / 500))} 分钟读完</span>
            {(showBare || showSummary) && <span className="flex items-center gap-2">{showBare && <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-amber-400" />裸对白</span>}{showSummary && <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-sky-400" />概述</span>}</span>}
          </div>
          <span className="hidden sm:inline"><Kbd>{modKey}</Kbd> <Kbd>S</Kbd> 保存</span>
        </div>
      </div>

      {panelOpen && <aside className="hidden w-[336px] shrink-0 border-l bg-surface/60 xl:block">{panel}</aside>}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen} title="审稿与人味" width={400}><div className="-mx-6 -my-5 h-[calc(100dvh-80px)]">{panel}</div></Sheet>
    </div>
  )
}

function RewriteDialog({ open, onOpenChange, selection, committed, onSubmit }: {
  open: boolean; onOpenChange: (o: boolean) => void; selection: { start: number; end: number; text: string } | null; committed: boolean
  onSubmit: (o: { instruction: string; scope: 'all' | 'selection'; route: string | null; autoReview: boolean }) => void
}) {
  const [ask, setAsk] = useState('')
  const [scope, setScope] = useState<'all' | 'selection'>('all')
  const [autoReview, setAutoReview] = useState(() => localStorage.getItem('novelos-rewrite-review') !== '0')
  const storage = useModelRoute('novelos.rewrite-route')
  useEffect(() => { if (open) setScope(selection ? 'selection' : 'all') }, [open, selection])
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title="按要求改写" desc="AI 只生成改写稿，逐段对比后你决定接受哪些；采纳后旧正文保留，可撤回。">
        <div className="space-y-3">
          <Segmented block value={scope} onChange={(v) => (v === 'selection' && !selection ? toast.info('先在正文里选中要改的文字，再点「按要求改写」') : setScope(v))}
            options={[{ value: 'all', label: '全章' }, { value: 'selection', label: selection ? `选中的文字（${countWords(selection.text)} 字）` : '选中的文字（未选中）' }]} />
          {scope === 'selection' && selection && <p className="line-clamp-3 rounded-md bg-subtle px-3 py-2 font-serif text-[13px] leading-relaxed text-foreground/75">{selection.text}</p>}
          {committed && <p className="rounded-md bg-warning-soft px-3 py-2 text-[12.5px] text-warning">这一章已提交入账：改写只改正文，不会改人物状态和伏笔底账。情节有大改时记得核对。</p>}
          <AskBox title="改写要求" storage={storage} emptyLabel="默认（正文模型）" value={ask} onChange={setAsk} submitLabel="生成改写稿"
            placeholder="例如：节奏加快，删掉中间那段回忆；对话多一点；把打斗写得更短更狠"
            onSubmit={() => { onSubmit({ instruction: ask.trim(), scope, route: storage.model, autoReview }); setAsk('') }}
            extra={<label className="flex cursor-pointer items-center justify-between gap-3 text-[12.5px] text-muted-foreground"><span>采纳后自动重新审稿（人味检查会自动跑）</span><Switch checked={autoReview} onCheckedChange={(v) => { setAutoReview(v); localStorage.setItem('novelos-rewrite-review', v ? '1' : '0') }} /></label>} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function SaveIndicator({ state, at }: { state: 'saved' | 'dirty' | 'saving' | 'error'; at: string | null }) {
  const m = {
    saved: { i: <CloudCheck className="h-3.5 w-3.5" />, t: at ? `已保存 · ${fmtTime(at)}` : '已保存', c: 'text-muted-foreground' },
    dirty: { i: <CloudUpload className="h-3.5 w-3.5" />, t: '未保存', c: 'text-muted-foreground' },
    saving: { i: <Loader2 className="h-3.5 w-3.5 animate-spin" />, t: '保存中…', c: 'text-muted-foreground' },
    error: { i: <AlertCircle className="h-3.5 w-3.5" />, t: '保存失败', c: 'text-danger' },
  }[state]
  return <span className={cn('flex items-center gap-1 whitespace-nowrap text-xs', m.c)}>{m.i}{m.t}</span>
}

