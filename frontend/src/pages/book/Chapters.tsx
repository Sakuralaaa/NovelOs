import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle, CheckCheck, Layers, ChevronLeft, Feather, CloudCheck, CloudUpload, Loader2, PanelRightClose, PanelRightOpen, PenLine, RotateCcw, RotateCw, Sparkles, Trash2, Type, Wand2, AlertCircle, Copy, Rows3, Gauge, ShieldCheck, Zap,
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
import { AigcPanel, useSha256 } from '@/components/aigc/Aigc'
import { CostButton } from '@/components/cost/CostButton'
import { FanficChapterPanel } from '@/components/FanficChapterPanel'
import { DuanjuPanel } from '@/components/chapter/DuanjuPanel'
import { ChapterToolsMenu } from '@/components/chapter/ChapterTools'
import { useBook } from '@/hooks/queries'
import { useBookId } from '@/hooks/useBookId'
import { useDebouncedCallback } from '@/hooks/useDebounced'
import { modKey, useHotkey } from '@/hooks/useHotkey'
import { api, qk, v013Api } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import { analyzeText } from '@/lib/textAnalysis'
import type { AigcSegment, ApprovalMode, Book, Chapter, ChapterVariant, EstimateKind } from '@/lib/types'
import { cn, countWords, fmtNum, fmtTime } from '@/lib/utils'

/** v0.9.3 工具栏：窄屏 / 触控 ≥40px；只有宽屏 + 鼠标时收成 32px */
const FINE = '[@media(min-width:640px)_and_(pointer:fine)]'
const TB = `h-10 px-2.5 ${FINE}:h-8`
const TBI = `h-10 w-10 ${FINE}:h-8 ${FINE}:w-8`
/** 后端 /api/estimate 支持 aigc（契约偏离补充），前端 EstimateKind 暂未列出 */
const AIGC_KIND: EstimateKind = 'aigc'

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
  const { data: book } = useBook(bookId)

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
  const [diff, setDiff] = useState<{ title: string; before: string; after: string; kind?: 'rewrite'; label?: string; warnings?: string[] } | null>(null)
  const [showAigc, setShowAigc] = useState(false)
  const [rwOpen, setRwOpen] = useState(false)
  const [rwSel, setRwSel] = useState<{ start: number; end: number; text: string } | null>(null)
  const [candOpen, setCandOpen] = useState(false)
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
  const polishJob = useActiveJob(`polish:${id}`)
  const aigcJob = useActiveJob(`aigc:${id}`)
  const busy = !!(reviewJob || humanizeJob || thickenJob || rewriteJob || polishJob)
  const rewriting = !!(humanizeJob || thickenJob || rewriteJob || polishJob)

  const runRewrite = async (kind: 'humanize' | 'thicken') => {
    if (!(await save())) return
    const before = latest.current.content
    const label = kind === 'thicken' ? '描写增厚' : '人味修整'
    start(kind === 'thicken' ? api.thickenChapter(id) : api.humanizeChapter(id), {
      key: `${kind}:${id}`, label, silent: true,
      onSuccess: async (j) => {
        // v0.9.3 审批模式 review：后端不落库，只回对比稿 draft（thicken 的 before/after 是指标，正文在 draft 里）
        const d = (j.result as Record<string, any> | undefined)?.draft as { before?: unknown; after?: unknown; changed?: boolean; label?: string } | undefined
        if (d && typeof d.after === 'string') {
          const b0 = typeof d.before === 'string' ? d.before : before
          if (d.changed === false || d.after === b0) { toast.info(`${label}完成，这一章没有需要改的地方`); return }
          if (latest.current.content !== b0) { toast.error(`${label}期间正文被改过，为免覆盖已丢弃这次结果，请重试`); return }
          autoReviewRef.current = false
          setDiff({ title: `${label} · 逐段对比，确定后才写入`, before: b0, after: d.after, kind: 'rewrite', label: d.label || `${label}前` })
          return
        }
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
  // v0.9.1：语感重塑。结果若带 before/after 则走「按要求改写」的预览-采纳流程；若后端已直接写入正文，则像人味修整一样逐段对比、可撤销
  const runPolish = async () => {
    if (!(await save())) return
    const before = latest.current.content
    start(api.polishVoice(bookId, id), {
      key: `polish:${id}`, label: '语感重塑', silent: true,
      onSuccess: async (j) => {
        const r = (j.result ?? {}) as Record<string, any>
        const warnings = normWarnings(r.warnings)
        const title = '语感重塑 · 逐段对比，确定后才写入'
        if (typeof r.after === 'string') {
          const b0 = typeof r.before === 'string' ? r.before : before
          if (r.changed === false || r.after === b0) { toast.info('语感重塑完成，这一章没有需要改的地方'); return }
          if (latest.current.content !== b0) { toast.error('重塑期间正文被改过，为免覆盖已丢弃这次结果，请重试'); return }
          autoReviewRef.current = false
          setDiff({ title, before: b0, after: r.after, kind: 'rewrite', label: typeof r.label === 'string' && r.label ? r.label : '语感重塑前', warnings })
          return
        }
        try {
          const fresh = await api.chapter(id)
          qc.setQueryData(qk.chapter(id), fresh)
          dirty.current = false
          setContent(fresh.content ?? '')
          setSaveState('saved')
          if ((fresh.content ?? '') !== before) setDiff({ title: '语感重塑完成 · 逐段对比', before, after: fresh.content ?? '', warnings })
          else toast.info('语感重塑完成，这一章没有需要改的地方')
        } catch { toast.success('语感重塑完成') }
      },
    })
  }
  // v0.9.1：朱雀 AIGC 检测
  const runAigc = async () => {
    if (!(await save())) return
    start(api.chapterAigc(bookId, id), {
      key: `aigc:${id}`, label: 'AI 率检测',
      successMsg: (j) => { const v = (j.result?.aigc ?? j.result)?.softmax ?? 0; return `AI 率检测完成：${Math.round(v <= 1 ? v * 100 : v)}%` },
      onSuccess: (j) => {
        // 结果 = {chapter_id, aigc}（兼容直接返回 Aigc）；同时已写入章节，失效刷新会再拉一次详情
        const a = (j.result?.aigc ?? j.result) as Chapter['aigc']
        if (a) qc.setQueryData(qk.chapter(id), (old: Chapter | undefined) => (old ? { ...old, aigc: { ...a, stale: false } } : old))
        setTab('aigc')
      },
    })
  }
  const runReview = async () => {
    if (!(await save())) return
    start(api.reviewChapter(id), { key: `review:${id}`, label: '审稿', successMsg: '审稿完成', onSuccess: () => setTab('review') })
  }

  const [rwSeed, setRwSeed] = useState('')
  const openRewrite = (seed?: string) => {
    const sel = editor.current?.getSelection()
    const text = sel && sel.end > sel.start ? latest.current.content.slice(sel.start, sel.end) : ''
    setRwSel(text.trim() ? { start: sel!.start, end: sel!.end, text } : null)
    setRwSeed(typeof seed === 'string' ? seed : '')
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
    mutationFn: (c: string) => api.applyRewrite(id, { content: c, label: diff?.label || '按要求改写前' }),
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

  // v0.9：应用审稿补丁（同步）；先落盘本地修改，旧正文进历史可撤回
  const applyPatches = useMutation({
    mutationFn: async (indices: number[]) => {
      if (!(await save())) throw new Error('本地修改还没保存成功，稍后再试')
      return api.applyReviewPatches(id, indices)
    },
    meta: { errorTitle: '应用补丁失败' },
    onSuccess: (r) => {
      qc.setQueryData(qk.chapter(id), r.chapter); qc.invalidateQueries({ queryKey: qk.chapters(bookId) })
      dirty.current = false; setContent(r.chapter.content ?? ''); setTitle(r.chapter.title); setSaveState('saved'); setFocusQuote(null)
      const skipped = r.skipped.length ? `跳过 ${r.skipped.length} 处：${r.skipped.map((k) => `#${k.index + 1} ${k.reason}`).join('；')}` : undefined
      if (!r.applied.length) { toast.info('没有应用任何补丁', { description: skipped ?? '原句在正文里找不到了' }); return }
      toast.success(`已应用 ${r.applied.length} 处补丁`, {
        description: skipped ?? '应用前的正文已存进历史',
        action: { label: '撤回', onClick: () => undoMut.mutate() },
        duration: 8000,
      })
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
  // AIGC 是否过期：能算 sha256 且与 content_hash 一致 → 未过期；否则看本地是否改过、章节 updated_at 是否晚于检测时间
  const aigc = ch?.aigc ?? null
  // 过期判断：以服务端 aigc.stale 为准；本地还没保存的修改也算过期。老后端没有 stale 字段时，退回比对 sha256 前缀 / updated_at
  const hash = useSha256(content, !!aigc && aigc.stale === undefined)
  const hashMatch = hash && aigc?.content_hash && /^[0-9a-f]{16,64}$/i.test(aigc.content_hash) ? hash.startsWith(aigc.content_hash.toLowerCase()) : null
  const localEdited = content !== (ch?.content ?? '') || saveState !== 'saved'
  const aigcStale = !!aigc && (localEdited || (aigc.stale !== undefined ? aigc.stale
    : hashMatch !== null ? !hashMatch
    : !!ch?.updated_at && !!aigc.checked_at && new Date(ch.updated_at).getTime() - new Date(aigc.checked_at).getTime() > 3000))
  const locateSeg = (sg: AigcSegment) => {
    const end = Math.min(sg.end, shown.length)
    if (sg.start >= shown.length) { toast.info('这一段的位置超出了当前正文', { description: '正文可能已经改过，重新检测一次吧' }); return }
    setShowAigc(true)
    setFocusQuote({ q: `aigc:${sg.start}`, start: sg.start, end })
    setSheetOpen(false)
    setTimeout(() => editor.current?.reveal(sg.start, end), 30)
  }
  const local: LocalStats = {
    avg_sentence_len: analysis.avg_sentence_len, short_sentence_ratio: analysis.short_sentence_ratio, bare_dialogue_ratio: analysis.bare_dialogue_ratio,
    summary_ratio: analysis.summary_ratio, dialogue_ratio: analysis.dialogue_ratio,
    bareCount: analysis.paras.filter((p) => p.kind === 'bare-dialogue').length, summaryCount: analysis.paras.filter((p) => p.kind === 'summary').length,
  }
  const ranges = useMemo<Range[]>(() => {
    const r: Range[] = []
    if (showBare) analysis.paras.filter((p) => p.kind === 'bare-dialogue').forEach((p) => r.push({ start: p.start, end: p.end, kind: 'bare' }))
    if (showSummary) analysis.paras.filter((p) => p.kind === 'summary').forEach((p) => r.push({ start: p.start, end: p.end, kind: 'summary' }))
    if (showAigc && aigc && !curVariant) aigc.segments?.forEach((sg) => { if (sg.label !== 'human' && sg.end > sg.start) r.push({ start: sg.start, end: Math.min(sg.end, shown.length), kind: sg.label }) })
    if (focusQuote) { const f = { start: focusQuote.start, end: focusQuote.end, kind: 'focus' as const }; return [...r.filter((x) => x.end <= f.start || x.start >= f.end), f] }
    return r
  }, [analysis, showBare, showSummary, focusQuote, showAigc, aigc, curVariant, shown.length])

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
      <div className="border-b px-4 py-3"><TabsList className="w-full"><TabsTrigger value="review">审稿</TabsTrigger><TabsTrigger value="lint">人味</TabsTrigger><TabsTrigger value="aigc">AI 率</TabsTrigger><TabsTrigger value="changes">变更</TabsTrigger><TabsTrigger value="duanju">短剧</TabsTrigger></TabsList></div>
      <div className="flex-1 overflow-y-auto px-4 py-4">
        <TabsContent value="review" className="focus:outline-none"><ReviewPanel review={ch.review} onQuote={locateQuote} onReview={runReview} reviewing={!!reviewJob} activeQuote={focusQuote?.q}
          onApplyPatches={(ix) => applyPatches.mutate(ix)} applyingPatches={applyPatches.isPending}
          patchDisabled={hasVariants ? '先采纳一个版本' : busy ? '有任务在进行' : !!diff && '先处理对比稿'}
          onUndo={ch.history ? () => setConfirmUndo(true) : undefined} undoLabel={ch.last_history_label} undoDisabled={busy || hasVariants || !!diff} />
          {book?.fanfic && <div className="mt-4"><FanficChapterPanel chapterId={ch.id} bookId={bookId} onLocate={locateQuote} /></div>}</TabsContent>
        <TabsContent value="lint" className="focus:outline-none">
          <LintPanel lint={lintForPanel} local={local} showBare={showBare} showSummary={showSummary} onToggleBare={setShowBare} onToggleSummary={setShowSummary}
            onHumanize={() => runRewrite('humanize')} onThicken={() => runRewrite('thicken')} busy={busy || hasVariants} thickening={!!thickenJob} humanizing={!!humanizeJob} />
        </TabsContent>
        <TabsContent value="aigc" className="focus:outline-none">
          <AigcPanel aigc={aigc} text={content} job={aigcJob} onRun={runAigc} stale={aigcStale}
            staleNote={localEdited ? '正文有未保存或检测后的修改，结果已过期' : '检测后正文有修改，结果已过期'}
            showHl={showAigc && !hasVariants} onToggleHl={setShowAigc} onLocate={locateSeg}
            disabled={hasVariants ? '先采纳一个版本再检测' : rewriting ? '改写任务进行中' : false} reportUrl={aigc ? v013Api.aigcReportUrl(ch.id) : undefined} />
        </TabsContent>
        <TabsContent value="changes" className="focus:outline-none"><ChangesPanel changes={ch.changes} /></TabsContent>
        <TabsContent value="duanju" className="focus:outline-none"><DuanjuPanel chapterId={ch.id} unsaved={saveState !== 'saved'} onLocate={locateQuote} /></TabsContent>
      </div>
    </Tabs>
  )

  const runningJob = polishJob ?? rewriteJob ?? thickenJob ?? humanizeJob ?? reviewJob

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 工具栏（v0.9.3：吸顶、紧凑；窄屏横向滚动；触控 ≥40px） */}
        <div className="sticky top-0 z-20 flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-b bg-background/85 px-2 py-1 backdrop-blur sm:flex-nowrap sm:px-3">
          <div className="flex min-w-0 shrink-0 items-center gap-2">
            <div className="w-[150px] lg:hidden">
              <Select value={String(id)} onChange={(v) => v && nav(`/books/${bookId}/chapters/${v}`)} options={chapters.map((c) => ({ value: String(c.id), label: `第${c.number}章 ${c.title.replace(/^第\d+章\s*/, '')}` }))} />
            </div>
            <Badge tone={STATUS[ch.status].tone} dot>{STATUS[ch.status].l}</Badge>
            <SaveIndicator state={saveState} at={savedAt} />
          </div>
          <div className="-mx-2 flex w-[calc(100%+1rem)] min-w-0 overflow-x-auto overscroll-x-contain px-2 [scrollbar-width:none] sm:mx-0 sm:w-auto sm:flex-1 sm:px-0 [&::-webkit-scrollbar]:hidden">
            <div className="ml-auto flex shrink-0 items-center gap-1 py-0.5 pr-1">
              <Tip content="写下一章（AI 按大纲写新章节）">
                <span className="inline-flex shrink-0"><WriteNextButton bookId={bookId} size="sm" label="写作" buttonClassName={`h-10 min-w-10 ${FINE}:h-8 ${FINE}:min-w-0`} /></span>
              </Tip>
              <ToolSep />
              <Tip content="写要求让 AI 改写全章或选中的文字，对比后再决定采纳">
                <span className="inline-flex shrink-0"><CostButton target={{ kind: 'chapter_rewrite', bookId, chapterId: id }} label="按要求改写" confirmLabel="写要求"
                  size="sm" variant="ghost" className={TB} loading={!!rewriteJob} disabled={busy || hasVariants || !!diff} icon={<PenLine className="h-3.5 w-3.5" />} onRun={() => openRewrite()}>改写</CostButton></span>
              </Tip>
              <Tip content="语感重塑：短句、动作先行、去套话；不改情节和数值">
                <span className="inline-flex shrink-0"><CostButton target={{ kind: 'polish_voice', bookId, chapterId: id }} label="语感重塑"
                  size="sm" variant="ghost" className={TB} loading={!!polishJob} disabled={busy || hasVariants || !!diff} icon={<Feather className="h-3.5 w-3.5" />} onRun={runPolish}>语感</CostButton></span>
              </Tip>
              <Tip content="人味修整：定点清理 AI 腔">
                <span className="inline-flex shrink-0"><CostButton target={{ kind: 'humanize', bookId, chapterId: id }} label="人味修整"
                  size="sm" variant="ghost" className={TB} loading={!!humanizeJob} disabled={busy || hasVariants || !!diff} icon={<Wand2 className="h-3.5 w-3.5" />} onRun={() => runRewrite('humanize')}>人味</CostButton></span>
              </Tip>
              <Tip content="描写增厚：给裸对白、概述段补动作与细节">
                <span className="inline-flex shrink-0"><CostButton target={{ kind: 'thicken', bookId, chapterId: id }} label="描写增厚"
                  size="sm" variant="ghost" className={TB} loading={!!thickenJob} disabled={busy || hasVariants || !!diff} icon={<Sparkles className="h-3.5 w-3.5" />} onRun={() => runRewrite('thicken')}>增厚</CostButton></span>
              </Tip>
              <ToolSep />
              <Tip content="审稿：按需挑问题、给建议与补丁（不动正文）">
                <span className="inline-flex shrink-0"><CostButton target={{ kind: 'review', bookId, chapterId: id }} label="审稿"
                  size="sm" variant="ghost" className={TB} loading={!!reviewJob} disabled={busy || hasVariants} icon={<RotateCw className="h-3.5 w-3.5" />} onRun={runReview}>审稿</CostButton></span>
              </Tip>
              <Tip content={hasVariants ? '先采纳一个版本再检测' : rewriting ? '改写任务进行中' : 'AI 率检测（朱雀，计检测额度）'}>
                <span className="inline-flex shrink-0"><CostButton target={{ kind: AIGC_KIND, bookId, chapterId: id }} label="AI 率检测"
                  size="sm" variant="ghost" className={TB} loading={!!aigcJob} disabled={hasVariants || rewriting || !!diff} icon={<Gauge className="h-3.5 w-3.5" />} onRun={runAigc}>AI 率</CostButton></span>
              </Tip>
              <ToolSep />
              <Tip content="整理段落：段与段之间统一空一行"><Button size="sm" variant="ghost" className={TB} disabled={busy || hasVariants || rewriting || !!diff} onClick={() => {
                const fixed = content.replace(/\r\n/g, '\n').split('\n').map((l) => l.trim()).filter(Boolean).join('\n\n')
                if (fixed === content) { toast.info('段落格式已经是整齐的'); return }
                edit({ content: fixed }); toast.success('已整理段落', { description: '可随时手动再改' })
              }} icon={<Rows3 className="h-3.5 w-3.5" />}>整理段落</Button></Tip>
              <ChapterToolsMenu bookId={bookId} chapterId={id} title={title} content={content} className={TB} disabled={hasVariants || !!diff}
                onTitle={(t) => edit({ title: t })} onLocate={locateQuote} onRewrite={(ins) => openRewrite(ins)}
                onFormat={() => { void v013Api.format(content).then((r) => { if (!r.changed) { toast.info('排版已经是规范的'); return } edit({ content: r.text }); toast.success('已规范排版', { description: r.notes.join('；') }) }) }} />
              <Tip content={serif ? '切换为黑体' : '切换为宋体'}><Button size="icon-sm" variant="ghost" className={TBI} onClick={() => { setSerif(!serif); localStorage.setItem('novelos-serif', serif ? '0' : '1') }} aria-label="字体"><Type className="h-4 w-4" /></Button></Tip>
              {!hasVariants && variants.length > 1 && <Tip content="当时写的几版候选稿"><Button size="sm" variant="ghost" className={TB} disabled={busy || !!diff} onClick={() => setCandOpen(true)} icon={<Layers className="h-3.5 w-3.5" />}>候选稿</Button></Tip>}
              {!!ch.history && !hasVariants && <Tip content={`撤回到「${ch.last_history_label || '上一版'}」的正文（共 ${ch.history} 个旧版本）`}><Button size="icon-sm" variant="ghost" className={TBI} disabled={busy || !!diff} onClick={() => setConfirmUndo(true)} aria-label="撤回"><RotateCcw className="h-4 w-4" /></Button></Tip>}
              <ToolSep />
              {book && <ApprovalToggle book={book} disabled={busy || !!diff} />}
              <ToolSep />
              {ch.status !== 'committed' && <Tip content="删除草稿"><Button size="icon-sm" variant="ghost" disabled={busy} onClick={() => setConfirmDel(true)} aria-label="删除草稿" className={cn(TBI, 'text-muted-foreground hover:text-danger')}><Trash2 className="h-4 w-4" /></Button></Tip>}
              <Tip content={hasVariants ? '先采纳一个版本' : ch.status === 'committed' ? '已提交，修改后可再次提交' : '确认本章，人物状态与伏笔写入底账'}>
                <span className="inline-flex shrink-0"><Button size="sm" variant={ch.status === 'committed' ? 'secondary' : 'primary'} className={TB} loading={commit.isPending || committing} disabled={busy || hasVariants || committing || !!diff} icon={<CheckCheck className="h-3.5 w-3.5" />} onClick={() => commit.mutate()}>提交</Button></span>
              </Tip>
              <Tip content={panelOpen ? '收起面板' : '展开面板'}>
                <Button size="icon-sm" variant="ghost" className={cn(TBI, 'hidden xl:inline-flex')} onClick={() => { setPanelOpen(!panelOpen); localStorage.setItem('novelos-panel', panelOpen ? '0' : '1') }} aria-label="面板">
                  {panelOpen ? <PanelRightClose className="h-4 w-4" /> : <PanelRightOpen className="h-4 w-4" />}
                </Button>
              </Tip>
              <Button size="icon-sm" variant="ghost" className={cn(TBI, 'xl:hidden')} onClick={() => setSheetOpen(true)} aria-label="审稿面板"><PanelRightOpen className="h-4 w-4" /></Button>
            </div>
          </div>
          <Dialog open={confirmUndo} onOpenChange={setConfirmUndo}>
            <DialogContent title="撤回到上一版正文？" desc={`恢复「${ch.last_history_label || '上一版'}」时的正文，之后的修改会丢掉。`}
              footer={<><Button variant="ghost" onClick={() => setConfirmUndo(false)}>取消</Button><Button variant="primary" loading={undoMut.isPending} onClick={() => undoMut.mutate()}>撤回</Button></>} />
          </Dialog>
          <CandidatesDialog open={candOpen} onOpenChange={setCandOpen} variants={variants} reason={ch.review?.pairwise?.reason}
            current={content} busy={busy || !!diff} onUse={(v) => {
              setCandOpen(false)
              autoReviewRef.current = false
              setDiff({ title: `换成第 ${v.id} 版 · 逐段对比，确定后才写入`, before: content, after: v.content, kind: 'rewrite', label: `换成候选稿第 ${v.id} 版前` })
            }} />
          <RewriteDialog open={rwOpen} onOpenChange={setRwOpen} selection={rwSel} committed={ch.status === 'committed'} onSubmit={runCustomRewrite} seed={rwSeed} />
          <Dialog open={confirmDel} onOpenChange={setConfirmDel}>
            <DialogContent title={`删除第 ${ch.number} 章草稿？`} desc="大纲会保留，之后可以重新写这一章。"
              footer={<><Button variant="ghost" onClick={() => setConfirmDel(false)}>取消</Button><Button variant="danger" loading={rmDraft.isPending} onClick={() => rmDraft.mutate()}>删除</Button></>} />
          </Dialog>
        </div>

        {diff ? (
          <div key="diff" className="min-h-0 flex-1 overflow-y-auto">
            {!!diff.warnings?.length && (
              <div className="mx-auto w-full max-w-[860px] px-6 pt-4">
                <div className="rounded-xl border border-warning/25 bg-warning-soft px-4 py-3">
                  <div className="flex items-center gap-1.5 text-[13px] font-medium text-warning"><AlertTriangle className="h-4 w-4" />采纳前请核对（{diff.warnings.length} 条）</div>
                  <ul className="mt-1.5 space-y-1">{diff.warnings.map((w, i) => <li key={i} className="break-words text-[12.5px] leading-relaxed text-foreground/80">· {w}</li>)}</ul>
                </div>
              </div>
            )}
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
          <div key="editor" ref={scroller} className="relative min-h-0 flex-1 overflow-y-auto">
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
                      <div className="flex items-center gap-1.5 text-[14px] font-semibold"><Copy className="h-4 w-4 text-primary" />{variants.length > 1 ? `这一章写了 ${variants.length} 个版本` : '新章节待采纳：看过后点「采纳此版」才写入正文'}</div>
                    </div>
                    <Button size="sm" variant="primary" loading={adopt.isPending} disabled={!curVariant} onClick={() => curVariant && adopt.mutate(curVariant.id)}>采纳此版</Button>
                  </div>
                  <div className="mt-3 grid gap-2" style={{ gridTemplateColumns: `repeat(${variants.length}, minmax(0,1fr))` }}>
                    {variants.map((v, i) => (
                      <button key={v.id} onClick={() => { setVariantId(v.id); setFocusQuote(null) }}
                        className={cn('relative rounded-lg px-3 py-2 text-left transition', v.id === variantId ? 'bg-surface shadow-card ring-2 ring-primary/50' : 'bg-surface/50 hairline hover:bg-surface')}>
                        <div className="flex items-center justify-between">
                          <span className="text-[13px] font-semibold">版本 {String.fromCharCode(65 + i)}</span>
                        </div>
                        <div className="num mt-1 truncate text-[12px] text-muted-foreground">{fmtNum(v.words)} 字</div>
                      </button>
                    ))}
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
            {(showBare || showSummary || (showAigc && aigc)) && <span className="flex items-center gap-2">{showBare && <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-amber-400" />裸对白</span>}{showSummary && <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-sky-400" />概述</span>}{showAigc && aigc && <><span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-danger/70" />AI</span><span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-warning/80" />疑似</span></>}</span>}
          </div>
          <span className="hidden sm:inline"><Kbd>{modKey}</Kbd> <Kbd>S</Kbd> 保存</span>
        </div>
      </div>

      {panelOpen && <aside className="hidden w-[336px] shrink-0 border-l bg-surface/60 xl:block">{panel}</aside>}
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen} title="审稿 · 人味 · AI 率 · 短剧" width={400}><div className="-mx-6 -my-5 h-[calc(100dvh-80px)]">{panel}</div></Sheet>
    </div>
  )
}

function RewriteDialog({ open, onOpenChange, selection, committed, onSubmit, seed }: {
  open: boolean; onOpenChange: (o: boolean) => void; selection: { start: number; end: number; text: string } | null; committed: boolean; seed?: string
  onSubmit: (o: { instruction: string; scope: 'all' | 'selection'; route: string | null; autoReview: boolean }) => void
}) {
  const [ask, setAsk] = useState('')
  const [scope, setScope] = useState<'all' | 'selection'>('all')
  const [autoReview, setAutoReview] = useState(() => localStorage.getItem('novelos-rewrite-review') !== '0')
  const storage = useModelRoute('novelos.rewrite-route')
  const refBookId = useBookId()
  useEffect(() => { if (open) setScope(selection ? 'selection' : 'all') }, [open, selection])
  useEffect(() => { if (open && seed) setAsk(seed) }, [open, seed])
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title="按要求改写" desc="AI 只生成改写稿，逐段对比后你决定接受哪些；采纳后旧正文保留，可撤回。">
        <div className="space-y-3">
          <Segmented block value={scope} onChange={(v) => (v === 'selection' && !selection ? toast.info('先在正文里选中要改的文字，再点「按要求改写」') : setScope(v))}
            options={[{ value: 'all', label: '全章' }, { value: 'selection', label: selection ? `选中的文字（${countWords(selection.text)} 字）` : '选中的文字（未选中）' }]} />
          {scope === 'selection' && selection && <p className="line-clamp-3 rounded-md bg-subtle px-3 py-2 font-serif text-[13px] leading-relaxed text-foreground/75">{selection.text}</p>}
          {committed && <p className="rounded-md bg-warning-soft px-3 py-2 text-[12.5px] text-warning">这一章已提交入账：改写只改正文，不会改人物状态和伏笔底账。情节有大改时记得核对。</p>}
          <AskBox title="改写要求" refBookId={refBookId} storage={storage} emptyLabel="默认（正文模型）" value={ask} onChange={setAsk} submitLabel="生成改写稿"
            placeholder="例如：节奏加快，删掉中间那段回忆；对话多一点；把打斗写得更短更狠"
            onSubmit={() => { onSubmit({ instruction: ask.trim(), scope, route: storage.model, autoReview }); setAsk('') }}
            extra={<label className="flex cursor-pointer items-center justify-between gap-3 text-[12.5px] text-muted-foreground"><span>采纳后自动重新审稿（人味检查会自动跑）</span><Switch checked={autoReview} onCheckedChange={(v) => { setAutoReview(v); localStorage.setItem('novelos-rewrite-review', v ? '1' : '0') }} /></label>} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ToolSep() {
  return <span aria-hidden className="mx-0.5 h-5 w-px shrink-0 bg-border" />
}

/** v0.9.3：审批模式切换。章节 AI 只有显式设为 review 才拦截落库（approval_mode_explicit），所以按实际生效的模式显示 */
function ApprovalToggle({ book, disabled }: { book: Book; disabled?: boolean }) {
  const qc = useQueryClient()
  const explicit = !!book.approval_mode_explicit
  const cur: ApprovalMode = explicit && book.approval_mode === 'review' ? 'review' : 'auto'
  const m = useMutation({
    mutationFn: (mode: ApprovalMode) => api.setApprovalMode(book.id, mode),
    meta: { errorTitle: '切换审批模式失败' },
    onSuccess: (b, mode) => {
      if (b && typeof b === 'object') qc.setQueryData(qk.book(book.id), (old: Book | undefined) => ({ ...(old ?? b), ...b }))
      qc.invalidateQueries({ queryKey: qk.book(book.id) })
      toast.success(mode === 'review' ? '已切到逐条审批' : '已切到自动采纳', {
        description: mode === 'review' ? '写章、改写、人味修整、增厚等只给对比稿，你确认后才写入正文' : 'AI 改动按写作偏好自动落库（旧正文仍可撤回）',
      })
    },
  })
  const opts: { v: ApprovalMode; l: string; i: typeof Zap; tip: string }[] = [
    { v: 'auto', l: '自动采纳', i: Zap, tip: 'AI 改动直接写入正文（旧正文进历史，可撤回）' },
    { v: 'review', l: '逐条审批', i: ShieldCheck, tip: 'AI 只生成对比稿 / 待采纳版本，逐段确认后才写入' },
  ]
  return (
    <div role="radiogroup" aria-label="审批模式" className="inline-flex shrink-0 items-center rounded-md bg-muted p-0.5">
      {opts.map((o) => (
        <Tip key={o.v} content={!explicit && o.v === 'review' && book.approval_mode === 'review' ? '这本书还没显式设置过：章节 AI 目前仍自动落库，点这里开启逐条审批' : o.tip}>
          <button type="button" role="radio" aria-checked={cur === o.v} disabled={disabled || m.isPending}
            onClick={() => { if (cur !== o.v) m.mutate(o.v) }}
            className={cn('focus-ring inline-flex h-9 items-center gap-1 whitespace-nowrap rounded-[5px] px-2.5 text-[12.5px] font-medium transition disabled:opacity-55',
              `${FINE}:h-7`, cur === o.v ? 'bg-surface text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground')}>
            {m.isPending && m.variables === o.v ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <o.i className="h-3.5 w-3.5" />}{o.l}
          </button>
        </Tip>
      ))}
    </div>
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

/** Job 结果里的 warnings 可能是字符串或 {message} 对象 */
function normWarnings(w: unknown): string[] {
  if (!Array.isArray(w)) return []
  return w.map((x) => (typeof x === 'string' ? x : x && typeof x === 'object' ? String((x as any).message ?? (x as any).text ?? JSON.stringify(x)) : String(x))).filter(Boolean)
}

/** v0.17 候选稿：开篇第 1 章和大爽点章写了 2 版，成对比较选了一版；落选的在这里看，也可以换成它 */
function CandidatesDialog({ open, onOpenChange, variants, reason, current, busy, onUse }: {
  open: boolean; onOpenChange: (v: boolean) => void; variants: ChapterVariant[]; reason?: string; current: string; busy: boolean
  onUse: (v: ChapterVariant) => void
}) {
  const [sel, setSel] = useState<number | null>(null)
  const cur = variants.find((v) => v.id === sel) ?? variants.find((v) => v.picked === false) ?? variants[0]
  if (!cur) return null
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title="候选稿" desc={reason || undefined}
        footer={<><Button variant="ghost" onClick={() => onOpenChange(false)}>关闭</Button>
          <Button variant="primary" disabled={busy || cur.content === current} onClick={() => onUse(cur)}>换成这一版</Button></>}>
        <div className="flex flex-wrap gap-1.5">
          {variants.map((v) => (
            <button key={v.id} onClick={() => setSel(v.id)} className={cn('flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12.5px] transition',
              v.id === cur.id ? 'border-primary bg-primary-soft text-primary' : 'text-muted-foreground hover:text-foreground')}>
              第 {v.id} 版<span className="num">{fmtNum(v.words)} 字</span>
              {v.picked === true && <Badge tone="success">入选</Badge>}
              {v.picked === false && <Badge tone="neutral">落选</Badge>}
            </button>
          ))}
        </div>
        <div className="prose-zh mt-3 max-h-[52vh] overflow-y-auto whitespace-pre-wrap rounded-lg bg-subtle p-3 font-serif text-[14px] leading-[1.9]">{cur.content}</div>
      </DialogContent>
    </Dialog>
  )
}
