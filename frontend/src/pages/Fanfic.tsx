import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, BookOpenCheck, BookPlus, ChevronLeft, CloudUpload, FileText, Globe2, Loader2, Plus, RotateCcw, Save, Search, Sparkles, Trash,
} from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { EmptyState, ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { Chips, DEPTHS, Lbl, Pager, RemoveBtn, StrList, depthLabel, sourceLabel } from '@/components/fanfic/bits'
import { Select } from '@/components/ui/select'
import { TemplatePicker } from '@/components/fanfic/TemplatePicker'
import { ApiError, fanficApi, fqk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type {
  FanficDepth, FanficSearchStatus, FanficSource, FanficTemplate, SourceCardPart, SourceCards, SourceCharacter, SourceFaction, SourceScene, SourceTimelineItem,
} from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

const CREATE_KEY = 'fanfic-source-create'
const MAX_BYTES = 30 * 1024 * 1024
const MIN_CHARS = 200
const bare = (s: string) => s.replace(/\s/g, '').length

type FanficView = 'search' | 'import' | 'sources'
const VIEW_META: Record<FanficView, { title: string; desc: string }> = {
  search: { title: '联网取材', desc: '只填作品名，用联网搜索整理人物、世界观、时间线和势力；资料可能有误，生成后请核对。' },
  import: { title: '导入原著', desc: '粘贴或上传 TXT（≤30MB），提炼角色、世界观、势力、时间线和名场面，原文只在本次提炼中使用，不保存。' },
  sources: { title: '原著资料', desc: '提炼好的设定卡可以逐条修改，再用它建同人书。' },
}

export default function FanficPage() {
  const { id } = useParams()
  const loc = useLocation()
  const [sp] = useSearchParams()
  const sid = id && /^\d+$/.test(id) ? Number(id) : 0
  // 旧地址：/fanfic、/fanfic/:id、/fanfic?source=
  if (loc.pathname === '/fanfic' || loc.pathname === '/fanfic/') {
    const src = sp.get('source')
    return <Navigate to={src && /^\d+$/.test(src) ? `/fanfic/sources/${src}` : '/fanfic/new'} replace />
  }
  if (sid && !loc.pathname.startsWith('/fanfic/sources/')) return <Navigate to={`/fanfic/sources/${sid}`} replace />
  if (sid) return (
    <div className="page max-w-[1080px]">
      <Link to="/fanfic/sources" className="focus-ring -ml-1 mb-1 inline-flex h-10 items-center gap-0.5 rounded-md pr-2 text-[13px] text-muted-foreground hover:text-foreground"><ChevronLeft className="h-4 w-4" />原著资料</Link>
      <SourceDetail id={sid} />
    </div>
  )
  const view: FanficView = loc.pathname.startsWith('/fanfic/import') ? 'import' : loc.pathname.startsWith('/fanfic/sources') ? 'sources' : 'search'
  const meta = VIEW_META[view]
  return (
    <div className={cn('page', view === 'sources' ? 'max-w-[1080px]' : 'max-w-[880px]')}>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="flex items-center gap-2 text-[22px] font-semibold tracking-tight"><BookOpenCheck className="h-5 w-5 text-primary" weight="duotone" />{meta.title}</h1>
        {view === 'sources' && (
          <Link to="/fanfic/new" className="ml-auto"><Button variant="primary" size="sm" className="h-10" icon={<BookPlus className="h-4 w-4" />}>建同人书</Button></Link>
        )}
      </div>
      <p className="mt-1 text-[13px] text-muted-foreground">{meta.desc}</p>
      <div className="mt-5">
        {view === 'sources' ? <SourceList /> : <ImportPanel key={view} kind={view} />}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 取材 / 导入

const SEARCH_DEPTHS: { value: FanficDepth; label: string; desc: string }[] = [
  { value: 'quick', label: '快速', desc: '2 轮检索：概况 + 主要人物' },
  { value: 'standard', label: '标准', desc: '4 轮：再加时间线、势力' },
  { value: 'deep', label: '深入', desc: '6+ 轮：体系细节、后续剧情' },
]
type ImportMode = 'search' | 'paste' | 'txt'

function SearchHint({ status }: { status?: FanficSearchStatus }) {
  if (!status) return null
  if (status.mode === 'none') return (
    <div className="flex gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] leading-relaxed text-warning">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 break-words">还没有配置联网搜索模型。去 <Link to="/settings#routing" className="font-medium underline underline-offset-2">设置 → 任务路由 → 联网搜索</Link> 选一个能联网的模型；也可以改用粘贴 / TXT 原文。</span>
    </div>
  )
  if (status.mode === 'mock') return <p className="text-[11.5px] text-muted-foreground">演示模式：没有配置渠道，返回演示资料（不会真的联网）。</p>
  return null
}

function ImportPanel({ kind }: { kind: 'search' | 'import' }) {
  const nav = useNavigate()
  const { start } = useJobs()
  const running = useActiveJob(CREATE_KEY)
  const fileRef = useRef<HTMLInputElement>(null)
  const tq = useQuery({ queryKey: fqk.templates, queryFn: fanficApi.templates, staleTime: 600_000 })
  const status = tq.data?.search
  const canSearch = status ? status.available : true
  const [mode, setMode] = useState<ImportMode>(kind === 'search' ? 'search' : 'paste')
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [focus, setFocus] = useState<string[]>([])
  const [depth, setDepth] = useState<FanficDepth>('standard')
  const [tplId, setTplId] = useState<string | null>(null)
  const [webOn, setWebOn] = useState<boolean | null>(null) // null = 跟随「是否配置了搜索模型」的默认值
  const web = (webOn ?? canSearch) && canSearch
  const n = bare(text)
  const hasTitle = !!title.trim()
  const ready = mode === 'search' ? hasTitle && canSearch : mode === 'paste' ? n >= MIN_CHARS : !!file
  const tpl = tq.data?.templates.find((t) => t.id === tplId) ?? null
  const pickTemplate = (t: FanficTemplate) => {
    if (tplId === t.id) { setTplId(null); return }
    setTplId(t.id)
    setTitle(t.title)
    setFocus(t.characters.slice(0, 2))
  }
  const pickFile = (f?: File | null) => {
    if (!f) return
    if (!/\.txt$/i.test(f.name) && f.type && f.type !== 'text/plain') { toast.error('只支持 .txt 文本文件'); return }
    if (f.size > MAX_BYTES) { toast.error('文件超过 30MB，请只保留需要的部分再导入'); return }
    setFile(f)
    if (!title) setTitle(f.name.replace(/\.txt$/i, '').slice(0, 60))
  }
  const go = async () => {
    if (!ready) return
    const t = title.trim()
    const template_id = tpl && tpl.title === t ? tpl.id : undefined
    const common = { title: t || undefined, focus: focus.length ? focus.slice(0, 10) : undefined, depth, template_id }
    const withWeb = web && !!t
    const req = mode === 'search' ? fanficApi.createSource({ source: 'search', ...common, title: t })
      : mode === 'paste' ? fanficApi.createSource({ source: 'paste', text, web_supplement: withWeb, ...common })
        : fanficApi.createSource({ source: 'txt', file: file!, web_supplement: withWeb, ...common })
    await start(req, {
      label: mode === 'search' ? `联网取材《${t}》` : withWeb ? '提炼原著设定 + 联网补充' : '提炼原著设定', key: CREATE_KEY,
      successMsg: '原著设定卡已生成',
      onSuccess: (j) => {
        const id = j.result?.source_id ?? j.result?.source?.id
        setText(''); setFile(null); setTitle(''); setFocus([]); setTplId(null)
        if (id) nav(`/fanfic/sources/${id}`)
      },
    })
  }
  const depths = mode === 'search' ? SEARCH_DEPTHS : DEPTHS
  return (
    <div className="min-w-0 space-y-3">
      {kind === 'import' && (
        <Segmented value={mode} onChange={setMode} className="h-10" options={[
          { value: 'paste', label: <span className="inline-flex items-center gap-1 whitespace-nowrap"><FileText className="h-3.5 w-3.5" />粘贴</span> },
          { value: 'txt', label: <span className="inline-flex items-center gap-1 whitespace-nowrap"><CloudUpload className="h-3.5 w-3.5" />TXT</span> },
        ]} />
      )}
      {mode === 'search' && (
        <>
          <TemplatePicker templates={tq.data?.templates ?? []} categories={tq.data?.categories ?? []} loading={tq.isLoading} selected={tplId} onPick={pickTemplate} />
          <SearchHint status={status} />
        </>
      )}
      <Input value={title} onChange={(e) => { setTitle(e.target.value.slice(0, 60)); if (tpl && e.target.value.trim() !== tpl.title) setTplId(null) }}
        placeholder={mode === 'search' ? '作品名（必填），如：斗罗大陆' : web ? '原著名（联网补充需要）' : '原著名（可选）'} className="h-10" aria-label="作品名" />
      {tpl && mode === 'search' && (
        <div className="rounded-lg bg-subtle/70 px-3 py-2 text-[12px] leading-relaxed text-muted-foreground">
          <span className="font-medium text-foreground/85">{tpl.title}</span>{tpl.aliases.length > 0 && <>（{tpl.aliases.join(' / ')}）</>}：{tpl.intro}
          <span className="mt-1 block">检索重点：{tpl.search_focus.slice(0, 3).join('；')}</span>
        </div>
      )}
      {mode === 'paste' && (
        <div>
          <Textarea rows={7} value={text} onChange={(e) => setText(e.target.value)} placeholder="把原著正文粘贴到这里（至少 200 字）"
            className="min-h-[160px] font-serif text-[13.5px]" />
          <div className={cn('num mt-1 text-right text-[12px]', n && n < MIN_CHARS ? 'text-danger' : 'text-muted-foreground')}>{n.toLocaleString('zh-CN')} 字{n > 0 && n < MIN_CHARS ? `，至少 ${MIN_CHARS} 字` : ''}</div>
        </div>
      )}
      {mode === 'txt' && (
        <div>
          <input ref={fileRef} type="file" accept=".txt,text/plain" className="hidden" onChange={(e) => { pickFile(e.target.files?.[0]); e.target.value = '' }} />
          {file ? (
            <div className="flex min-w-0 items-center gap-2 rounded-xl border border-primary/40 bg-primary-soft/40 px-3 py-2">
              <FileText className="h-4 w-4 shrink-0 text-primary" />
              <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{file.name}</span>
              <span className="num shrink-0 text-[12px] text-muted-foreground">{(file.size / 1024 / 1024).toFixed(1)}MB</span>
              <RemoveBtn label="移除文件" onClick={() => setFile(null)} />
            </div>
          ) : (
            <button type="button" onClick={() => fileRef.current?.click()}
              onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); pickFile(e.dataTransfer.files?.[0]) }}
              className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed bg-subtle/40 px-4 py-7 text-center transition hover:border-primary/40 hover:bg-primary-soft/30">
              <CloudUpload className="h-7 w-7 text-primary/80" />
              <span className="text-[14px] font-medium">点击选择 TXT 文件</span>
              <span className="text-[12px] text-muted-foreground">UTF-8 / GBK / UTF-16 自动识别</span>
            </button>
          )}
        </div>
      )}
      {mode !== 'search' && (
        <label className={cn('flex min-h-[44px] items-start gap-2.5 rounded-lg border px-3 py-2', canSearch ? 'cursor-pointer' : 'cursor-not-allowed opacity-60')}>
          <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]" checked={web} disabled={!canSearch}
            onChange={(e) => setWebOn(e.target.checked)} aria-label="联网补充" />
          <span className="min-w-0">
            <span className="block text-[13px] font-medium">联网补充</span>
            <span className="block text-[11.5px] leading-snug text-muted-foreground">
              {!canSearch ? '未配置联网搜索模型（设置 → 任务路由 → 联网搜索）'
                : web && !hasTitle ? '填写原著名后才会联网补充'
                  : '用搜索补齐原文没覆盖的人物、设定和后续剧情；冲突以原文为准'}
            </span>
          </span>
        </label>
      )}
      <div>
        <Lbl hint="最多 10 个">{mode === 'search' ? '重点人物 / 剧情范围（可选，每项多检索一轮）' : '重点角色 / 剧情关键词（可选）'}</Lbl>
        <Chips value={focus} onChange={setFocus} max={10} placeholder={mode === 'search' ? '如：唐三、小舞，回车添加' : '如：主角名，回车添加'} />
      </div>
      <div>
        <Lbl>{mode === 'search' ? '检索深度' : '提炼深度'}</Lbl>
        <div className="grid grid-cols-3 gap-1.5">
          {depths.map((d) => (
            <button key={d.value} type="button" onClick={() => setDepth(d.value)} aria-pressed={depth === d.value}
              className={cn('focus-ring min-h-[56px] min-w-0 rounded-lg border px-2 py-1.5 text-left transition',
                depth === d.value ? 'border-primary bg-primary-soft/50' : 'hover:border-foreground/20')}>
              <span className={cn('block text-[13px] font-semibold', depth === d.value && 'text-primary')}>{d.label}</span>
              <span className="block text-[11px] leading-snug text-muted-foreground">{d.desc}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="sticky bottom-0 pb-3 pt-3">
        {running ? <JobInline job={running} /> : (
          <Button variant="primary" className="h-11 w-full" disabled={!ready} icon={mode === 'search' ? <Globe2 className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />} onClick={() => void go()}>
            {mode === 'search' ? (hasTitle ? `开始联网取材《${title.trim().slice(0, 12)}》` : '填写作品名后开始取材') : '提炼原著设定卡'}
          </Button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- 原著资料列表

function SourceList() {
  const q = useQuery({ queryKey: fqk.sources, queryFn: fanficApi.sources })
  if (q.isLoading) return <div className="space-y-2">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-[64px] rounded-xl" />)}</div>
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />
  const list = q.data ?? []
  return (
    <div className="space-y-2">
      {!list.length ? (
        <EmptyState kind="cards" title="还没有原著资料" desc="联网取材或导入原著 TXT 后，提炼出的设定卡会出现在这里。"
          action={<div className="flex gap-2"><Link to="/fanfic/search"><Button variant="primary" size="sm" icon={<Globe2 className="h-4 w-4" />}>联网取材</Button></Link><Link to="/fanfic/import"><Button variant="soft" size="sm" icon={<CloudUpload className="h-4 w-4" />}>导入原著</Button></Link></div>} />
      ) : (
        <ul className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))]">
          {list.map((s) => (
            <li key={s.id}>
              <Link to={`/fanfic/sources/${s.id}`} className="card-hover focus-ring flex min-h-[60px] min-w-0 items-center gap-3 rounded-xl border bg-surface px-3 py-2.5">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] font-semibold">{s.title || '未命名'}</span>
                  <span className="num mt-0.5 flex flex-wrap items-center gap-x-1.5 text-[12px] text-muted-foreground">
                    <span className={cn('whitespace-nowrap rounded px-1.5 leading-[18px]', s.source === 'search' || s.web_rounds ? 'bg-primary-soft text-primary' : 'bg-muted')}>{sourceLabel(s)}</span>
                    <span>{s.counts.characters} 角色</span><span className="opacity-40">·</span>
                    <span>{depthLabel(s.depth)}</span><span className="opacity-40">·</span>
                    <span>完整度 {s.completeness}</span>
                    {s.used_by.length > 0 && <span className="rounded bg-primary-soft px-1.5 leading-[18px] text-primary">{s.used_by.length} 本书在用</span>}
                    {s.warnings_count > 0 && <span className="inline-flex items-center gap-0.5 text-warning"><AlertTriangle className="h-3 w-3" />{s.warnings_count}</span>}
                  </span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 设定卡详情

type ViewTab = 'world' | 'characters' | 'timeline' | 'relations'
const TABS: { value: ViewTab; label: string; parts: SourceCardPart[] }[] = [
  { value: 'world', label: '世界设定', parts: ['world', 'factions'] }, { value: 'characters', label: '角色档案', parts: ['characters'] },
  { value: 'timeline', label: '时间线', parts: ['timeline', 'scenes'] }, { value: 'relations', label: '关系索引', parts: [] },
]
const PAGE = 12
const hit = (kw: string, ...xs: (string | string[] | undefined)[]) => !kw || xs.some((x) => (Array.isArray(x) ? x.join(' ') : x ?? '').toLowerCase().includes(kw))
function usePaged(all: number[], kw: string, size = PAGE) {
  const [page, setPage] = useState(1)
  useEffect(() => setPage(1), [kw])
  const pages = Math.max(1, Math.ceil(all.length / size))
  const p = Math.min(page, pages)
  return { idx: all.slice((p - 1) * size, p * size), page: p, pages, setPage }
}
const PARTS: { value: SourceCardPart; label: string }[] = [
  { value: 'characters', label: '角色档案' }, { value: 'world', label: '世界设定' }, { value: 'factions', label: '势力' },
  { value: 'timeline', label: '时间线' }, { value: 'scenes', label: '名场面' },
]
const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])
const str = (v: unknown) => (typeof v === 'string' ? v : v == null ? '' : String(v))
function normCards(c: Partial<SourceCards> | undefined | null): SourceCards {
  const w = (c?.world ?? {}) as Partial<SourceCards['world']>
  return {
    characters: arr<SourceCharacter>(c?.characters).map((x) => ({
      name: str(x.name), aliases: arr<string>(x.aliases), role: str(x.role), personality: str(x.personality), speech_style: str(x.speech_style),
      catchphrases: arr<string>(x.catchphrases), relations: arr<{ target: string; relation: string }>(x.relations).map((r) => ({ target: str(r.target), relation: str(r.relation) })),
      abilities: arr<string>(x.abilities), limits: arr<string>(x.limits), notes: str(x.notes),
    })),
    world: { summary: str(w.summary), rules: arr<string>(w.rules), locations: arr<{ name: string; desc: string }>(w.locations).map((l) => ({ name: str(l.name), desc: str(l.desc) })) },
    factions: arr<SourceFaction>(c?.factions).map((f) => ({ name: str(f.name), stance: str(f.stance), members: arr<string>(f.members), notes: str(f.notes) })),
    timeline: arr<SourceTimelineItem>(c?.timeline).map((t, i) => ({ order: Number(t.order) || i + 1, event: str(t.event), characters: arr<string>(t.characters), impact: str(t.impact) })),
    scenes: arr<SourceScene>(c?.scenes).map((s) => ({ title: str(s.title), summary: str(s.summary), characters: arr<string>(s.characters) })),
  }
}

function SourceDetail({ id }: { id: number }) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const q = useQuery({ queryKey: fqk.source(id), queryFn: () => fanficApi.source(id), retry: false })
  const [tab, setTab] = useState<ViewTab>('world')
  const [kw, setKw] = useState('')
  const [draft, setDraft] = useState<SourceCards | null>(null)
  const [title, setTitle] = useState('')
  const [saveWarn, setSaveWarn] = useState<string[]>([])
  const [forceAsk, setForceAsk] = useState<string | null>(null)
  const base = useMemo(() => (q.data ? normCards(q.data.cards) : null), [q.data])
  useEffect(() => { if (q.data) { setDraft(normCards(q.data.cards)); setTitle(q.data.title) } }, [q.data])
  useEffect(() => { setSaveWarn([]); setTab('world'); setKw('') }, [id])

  const dirtyParts = useMemo(() => (draft && base ? PARTS.map((p) => p.value).filter((k) => JSON.stringify(draft[k]) !== JSON.stringify(base[k])) : []), [draft, base])
  const titleDirty = !!q.data && title.trim() !== q.data.title && !!title.trim()
  const dirty = dirtyParts.length > 0 || titleDirty

  const save = useMutation({
    mutationFn: () => {
      const cards: Partial<SourceCards> = {}
      for (const k of dirtyParts) (cards as any)[k] = draft![k]
      return fanficApi.updateSource(id, { ...(titleDirty ? { title: title.trim() } : {}), ...(dirtyParts.length ? { cards } : {}) })
    },
    meta: { errorTitle: '保存失败' },
    onSuccess: (r) => {
      qc.setQueryData(fqk.source(id), r.source)
      qc.invalidateQueries({ queryKey: fqk.sources })
      setSaveWarn(r.warnings ?? [])
      if (r.warnings?.length) toast.warning(`已保存，有 ${r.warnings.length} 条重合提醒`)
      else toast.success('已保存')
    },
  })
  const { start } = useJobs()
  const supKey = `fanfic-supplement-${id}`
  const supRunning = useActiveJob(supKey)
  const tq = useQuery({ queryKey: fqk.templates, queryFn: fanficApi.templates, staleTime: 600_000 })
  const canSearch = tq.data ? tq.data.search.available : true
  const supplement = async () => {
    await start(fanficApi.supplementSource(id, { depth: 'standard' }), {
      label: '联网补充原著资料', key: supKey, successMsg: '联网补充完成',
      onSuccess: (j) => {
        const src = j.result?.source as FanficSource | undefined
        if (src) { qc.setQueryData(fqk.source(id), src); setDraft(normCards(src.cards)) }
        qc.invalidateQueries({ queryKey: fqk.sources })
      },
    })
  }
  const remove = useMutation({
    mutationFn: (force: boolean) => fanficApi.deleteSource(id, force),
    meta: { silent: true },
    onSuccess: () => {
      setForceAsk(null)
      qc.invalidateQueries({ queryKey: fqk.sources })
      qc.invalidateQueries({ queryKey: ['fanfic', 'book'] })
      qc.removeQueries({ queryKey: fqk.source(id) })
      toast.success('已删除原著资料')
      nav('/fanfic/sources', { replace: true })
    },
    onError: (e: any) => {
      if (e instanceof ApiError && e.status === 409) setForceAsk(e.message)
      else toast.error('删除失败', { description: e?.message })
    },
  })

  if (q.isLoading || (q.data && !draft)) return <div className="space-y-3"><Skeleton className="h-8 w-1/2" /><Skeleton className="h-64 rounded-xl" /></div>
  if (q.isError || !q.data || !draft) return <ErrorState error={q.error ?? { message: '没找到这份原著资料' }} onRetry={() => q.refetch()} />
  const s: FanficSource = q.data
  const set = <K extends SourceCardPart>(k: K, v: SourceCards[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d))

  return (
    <div className="min-w-0 pb-20">
      <div className="flex min-w-0 flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1 basis-[240px]">
          <Input value={title} onChange={(e) => setTitle(e.target.value.slice(0, 60))} aria-label="原著名"
            className="h-11 border-transparent bg-transparent px-1 text-[19px] font-semibold tracking-tight shadow-none hover:border-input" />
          <div className="num mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 px-1 text-[12.5px] text-muted-foreground">
            <span className={cn('whitespace-nowrap rounded px-1.5 leading-[20px]', s.source === 'search' || s.web_rounds ? 'bg-primary-soft text-primary' : 'bg-muted')}>{sourceLabel(s)}</span>
            {s.source !== 'search' && <span>取用 {fmtNum(s.chars)} / {fmtNum(s.total_chars)} 字</span>}
            {!!s.web_rounds && <span>联网检索 {s.web_rounds} 轮</span>}
            <span>{depthLabel(s.depth)}{s.source === 'search' ? '检索' : '提炼'}</span>
            <span>完整度 {s.completeness}</span>
            <span>{fmtDateTime(s.updated_at)}</span>
            {s.focus?.length > 0 && <span className="truncate">重点：{s.focus.join('、')}</span>}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-1.5">
          <Link to={`/fanfic/new?source=${s.id}`}><Button variant="soft" className="h-10" icon={<BookPlus className="h-4 w-4" />}>用它建书</Button></Link>
          {supRunning ? null : (
            <Button variant="ghost" className="h-10" icon={<Globe2 className="h-4 w-4" />} disabled={!canSearch || dirty}
              title={!canSearch ? (tq.data?.search.hint || '未配置联网搜索模型') : dirty ? '先保存或还原修改' : '用联网搜索补齐缺的人物、设定和后续剧情（以现有设定卡为准）'}
              onClick={() => void supplement()}>联网补充</Button>
          )}
          <Button variant="ghost" className="h-10 text-danger hover:bg-danger-soft" loading={remove.isPending && !forceAsk} icon={<Trash className="h-4 w-4" />}
            onClick={() => { if (window.confirm(`删除原著资料「${s.title}」？设定卡将一并删除。`)) remove.mutate(false) }}>删除</Button>
        </div>
      </div>

      {supRunning && <div className="mt-3"><JobInline job={supRunning} /></div>}
      {!canSearch && tq.data && <p className="mt-2 text-[12px] text-muted-foreground">联网补充需要先在 <Link to="/settings#routing" className="text-primary hover:underline">设置 → 任务路由 → 联网搜索</Link> 配置模型。</p>}
      {(s.refs?.length ?? 0) > 0 && (
        <details className="mt-3 rounded-lg border px-3 py-2 text-[12.5px]">
          <summary className="flex min-h-[32px] cursor-pointer items-center text-muted-foreground">联网来源链接 {s.refs!.length} 个（资料可能有误，请核对）</summary>
          <ul className="mt-1 space-y-1">{s.refs!.map((u) => <li key={u} className="min-w-0 break-all"><a href={u} target="_blank" rel="noreferrer noopener" className="text-primary hover:underline">{u}</a></li>)}</ul>
        </details>
      )}
      {s.used_by.length > 0 && (
        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted-foreground">在用的书：
          {s.used_by.map((b) => <Link key={b} to={`/books/${b}`} className="inline-flex h-8 items-center rounded-md bg-primary-soft px-2 text-primary hover:underline">书 #{b}</Link>)}
        </p>
      )}
      {(s.warnings?.length > 0 || saveWarn.length > 0) && (
        <ul className="mt-3 space-y-1 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning">
          {saveWarn.map((w, i) => <li key={`s${i}`} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words"><b>重合提醒：</b>{w}</span></li>)}
          {s.warnings.map((w, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words">{w}</span></li>)}
        </ul>
      )}

      <div className="mt-4 flex min-w-0 flex-wrap items-center gap-2">
        <div className="-mx-3 min-w-0 overflow-x-auto px-3 [scrollbar-width:none] sm:mx-0 sm:px-0">
          <Segmented value={tab} onChange={(v) => { setTab(v); setKw('') }} className="h-10" options={TABS.map((t) => {
            const n = t.value === 'world' ? draft.factions.length + draft.world.locations.length + draft.world.rules.length
              : t.value === 'characters' ? draft.characters.length : t.value === 'timeline' ? draft.timeline.length + draft.scenes.length
                : draft.characters.reduce((x, c) => x + c.relations.length, 0)
            const d = (t.value === 'relations' ? ['characters'] : t.parts).some((k) => dirtyParts.includes(k as SourceCardPart))
            return { value: t.value, label: <span className="inline-flex items-center gap-1 whitespace-nowrap">{t.label}<span className="num text-[11px] opacity-60">{n}</span>{d && <span className="h-1.5 w-1.5 rounded-full bg-warning" />}</span> }
          })} />
        </div>
        <div className="relative ml-auto min-w-[180px] flex-1 sm:max-w-[260px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder={`搜${TABS.find((t) => t.value === tab)!.label}`} className="h-10 pl-8" aria-label="搜索原著资料" />
        </div>
      </div>

      <div className="mt-3">
        {tab === 'world' && <>
          <WorldEdit value={draft.world} kw={kw.trim().toLowerCase()} onChange={(v) => set('world', v)} />
          <h3 className="mb-2 mt-5 text-[14px] font-semibold">势力</h3>
          <FactionsEdit value={draft.factions} kw={kw.trim().toLowerCase()} onChange={(v) => set('factions', v)} />
        </>}
        {tab === 'characters' && <CharactersEdit value={draft.characters} kw={kw.trim().toLowerCase()} onChange={(v) => set('characters', v)} />}
        {tab === 'timeline' && <>
          <TimelineEdit value={draft.timeline} kw={kw.trim().toLowerCase()} onChange={(v) => set('timeline', v)} />
          <h3 className="mb-2 mt-5 text-[14px] font-semibold">名场面</h3>
          <ScenesEdit value={draft.scenes} kw={kw.trim().toLowerCase()} onChange={(v) => set('scenes', v)} />
        </>}
        {tab === 'relations' && <RelationsEdit value={draft.characters} kw={kw.trim().toLowerCase()} onChange={(v) => set('characters', v)} />}
      </div>

      {dirty && (
        <div className="sticky bottom-0 z-10 -mx-3 mt-4 flex items-center gap-2 border-t bg-background/95 px-3 py-2 backdrop-blur sm:mx-0 sm:rounded-xl sm:border">
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">有未保存的修改{dirtyParts.length ? `：${dirtyParts.map((k) => PARTS.find((p) => p.value === k)!.label).join('、')}` : ''}</span>
          <Button variant="ghost" className="h-10" icon={<RotateCcw className="h-4 w-4" />} onClick={() => { setDraft(normCards(s.cards)); setTitle(s.title) }}>还原</Button>
          <Button variant="primary" className="h-10" loading={save.isPending} icon={<Save className="h-4 w-4" />} onClick={() => save.mutate()}>保存</Button>
        </div>
      )}

      <Dialog open={!!forceAsk} onOpenChange={(o) => !o && setForceAsk(null)}>
        <DialogContent title="有同人书在用这份原著" desc={forceAsk ?? ''}
          footer={<>
            <Button className="h-10" onClick={() => setForceAsk(null)}>取消</Button>
            <Button variant="danger" className="h-10" loading={remove.isPending} icon={remove.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash className="h-4 w-4" />} onClick={() => remove.mutate(true)}>仍然删除</Button>
          </>}>
          <p className="text-[13px] leading-relaxed text-foreground/85">强制删除后，这些书仍保留同人设置（方向、遵循度、作者补充），但写章时不再注入原著角色与时间线，只按遵循规则把握；OOC 检查将不可用。已导入设定库的角色不受影响。</p>
          {s.used_by.length > 0 && <p className="mt-2 text-[12.5px] text-muted-foreground">在用：{s.used_by.map((b) => `书 #${b}`).join('、')}</p>}
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ---------------------------------------------------------------- 各块编辑器

const Box = ({ children, className }: { children: React.ReactNode; className?: string }) => <div className={cn('min-w-0 rounded-xl border bg-surface p-3', className)}>{children}</div>
const AddBtn = ({ onClick, children }: { onClick: () => void; children: React.ReactNode }) => (
  <Button variant="soft" className="h-11 w-full" icon={<Plus className="h-4 w-4" />} onClick={onClick}>{children}</Button>
)
const upd = <T,>(list: T[], i: number, patch: Partial<T>) => list.map((x, k) => (k === i ? { ...x, ...patch } : x))

function CharactersEdit({ value, kw, onChange }: { value: SourceCharacter[]; kw: string; onChange: (v: SourceCharacter[]) => void }) {
  const [open, setOpen] = useState<number | null>(null)
  const all = value.map((_, i) => i).filter((i) => { const c = value[i]; return hit(kw, c.name, c.aliases, c.role, c.personality, c.abilities, c.notes) })
  const pg = usePaged(all, kw)
  return (
    <div className="space-y-2">
      {pg.idx.map((i) => { const c = value[i]
        const p = (x: Partial<SourceCharacter>) => onChange(upd(value, i, x))
        const isOpen = open === i
        return (
          <Box key={i} className="p-0">
            <div className="flex min-w-0 items-center gap-1">
              <button type="button" onClick={() => setOpen(isOpen ? null : i)} aria-expanded={isOpen}
                className="focus-ring flex min-h-[52px] min-w-0 flex-1 items-center gap-2 rounded-xl px-3 py-2 text-left">
                <span className="min-w-0 flex-1">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-[14px] font-semibold">{c.name || '未命名角色'}</span>
                    {c.role && <span className="shrink-0 rounded-md bg-primary-soft px-1.5 text-[11.5px] leading-[20px] text-primary">{c.role}</span>}
                  </span>
                  {!isOpen && <span className="mt-0.5 block truncate text-[12.5px] text-muted-foreground">{c.personality || c.speech_style || '点开编辑'}</span>}
                </span>
                <span className="shrink-0 text-[12px] text-muted-foreground">{isOpen ? '收起' : '编辑'}</span>
              </button>
              <RemoveBtn label="删除角色" className="mr-1" onClick={() => { if (window.confirm(`删除角色「${c.name || '未命名'}」？`)) { onChange(value.filter((_, k) => k !== i)); setOpen(null) } }} />
            </div>
            {isOpen && (
              <div className="grid gap-3 border-t p-3 sm:grid-cols-2">
                <div><Lbl>名字</Lbl><Input className="h-10" value={c.name} onChange={(e) => p({ name: e.target.value })} /></div>
                <div><Lbl>定位</Lbl><Input className="h-10" value={c.role} placeholder="主角 / 主要配角 / 反派…" onChange={(e) => p({ role: e.target.value })} /></div>
                <div className="sm:col-span-2"><Lbl>别称</Lbl><Chips value={c.aliases} onChange={(v) => p({ aliases: v })} /></div>
                <div className="sm:col-span-2"><Lbl hint={`${c.personality.length}/160`}>性格</Lbl><Textarea rows={2} value={c.personality} onChange={(e) => p({ personality: e.target.value.slice(0, 160) })} /></div>
                <div className="sm:col-span-2"><Lbl hint={`${c.speech_style.length}/100`}>说话方式</Lbl><Textarea rows={2} value={c.speech_style} onChange={(e) => p({ speech_style: e.target.value.slice(0, 100) })} /></div>
                <div className="sm:col-span-2"><Lbl hint="最多 6 条，每条 ≤30 字">口癖</Lbl><Chips max={6} value={c.catchphrases} onChange={(v) => p({ catchphrases: v.map((x) => x.slice(0, 30)) })} /></div>
                <div className="sm:col-span-2">
                  <Lbl>关系</Lbl>
                  <div className="space-y-1.5">
                    {c.relations.map((r, k) => (
                      <div key={k} className="flex min-w-0 items-center gap-1.5">
                        <Input className="h-10 w-[38%] min-w-0" placeholder="对象" value={r.target} onChange={(e) => p({ relations: upd(c.relations, k, { target: e.target.value }) })} />
                        <Input className="h-10 min-w-0 flex-1" placeholder="关系" value={r.relation} onChange={(e) => p({ relations: upd(c.relations, k, { relation: e.target.value }) })} />
                        <RemoveBtn onClick={() => p({ relations: c.relations.filter((_, j) => j !== k) })} />
                      </div>
                    ))}
                    <button type="button" onClick={() => p({ relations: [...c.relations, { target: '', relation: '' }] })} className="focus-ring inline-flex h-10 items-center gap-1 rounded-md px-2 text-[13px] text-primary hover:bg-primary-soft/60"><Plus className="h-3.5 w-3.5" />添加关系</button>
                  </div>
                </div>
                <div><Lbl>能力</Lbl><StrList value={c.abilities} onChange={(v) => p({ abilities: v })} addLabel="添加能力" /></div>
                <div><Lbl>边界 / 限制</Lbl><StrList value={c.limits} onChange={(v) => p({ limits: v })} addLabel="添加限制" /></div>
                <div className="sm:col-span-2"><Lbl>备注</Lbl><Textarea rows={2} value={c.notes} onChange={(e) => p({ notes: e.target.value })} /></div>
              </div>
            )}
          </Box>
        )
      })}
      <Pager page={pg.page} pages={pg.pages} onChange={pg.setPage} />
      {kw && !all.length && <p className="py-4 text-center text-[12.5px] text-muted-foreground">没有匹配的角色</p>}
      {value.length < 60 && !kw && <AddBtn onClick={() => { onChange([...value, { name: '', aliases: [], role: '', personality: '', speech_style: '', catchphrases: [], relations: [], abilities: [], limits: [], notes: '' }]); setOpen(value.length); pg.setPage(Math.ceil((value.length + 1) / PAGE)) }}>添加角色</AddBtn>}
      {!value.length && <p className="text-center text-[12.5px] text-muted-foreground">没有提炼出角色</p>}
    </div>
  )
}

function WorldEdit({ value, kw, onChange }: { value: SourceCards['world']; kw: string; onChange: (v: SourceCards['world']) => void }) {
  const locs = value.locations.map((_, i) => i).filter((i) => hit(kw, value.locations[i].name, value.locations[i].desc))
  return (
    <div className="space-y-3">
      {kw && <Box><Lbl>匹配的规则</Lbl>{value.rules.filter((r) => hit(kw, r)).map((r, i) => <p key={i} className="py-1 text-[13px]">{r}</p>)}{!value.rules.some((r) => hit(kw, r)) && <p className="text-[12.5px] text-muted-foreground">无</p>}</Box>}
      {!kw && <Box><Lbl hint={`${value.summary.length}/400`}>世界观概述</Lbl><Textarea rows={4} value={value.summary} onChange={(e) => onChange({ ...value, summary: e.target.value.slice(0, 400) })} /></Box>}
      {!kw && <Box><Lbl hint="最多 12 条，每条 ≤80 字">规则</Lbl><StrList max={12} value={value.rules} onChange={(v) => onChange({ ...value, rules: v.map((x) => x.slice(0, 80)) })} addLabel="添加规则" /></Box>}
      <Box>
        <Lbl>地点</Lbl>
        <div className="space-y-2">
          {locs.map((i) => { const l = value.locations[i]; return (
            <div key={i} className="flex min-w-0 flex-wrap items-start gap-1.5 sm:flex-nowrap">
              <Input className="h-10 min-w-0 flex-1 sm:w-[30%] sm:flex-none" placeholder="地名" value={l.name} onChange={(e) => onChange({ ...value, locations: upd(value.locations, i, { name: e.target.value }) })} />
              <Input className="h-10 min-w-0 flex-[2] basis-[60%]" placeholder="描述" value={l.desc} onChange={(e) => onChange({ ...value, locations: upd(value.locations, i, { desc: e.target.value }) })} />
              <RemoveBtn onClick={() => onChange({ ...value, locations: value.locations.filter((_, k) => k !== i) })} />
            </div>
          ) })}
          <button type="button" onClick={() => onChange({ ...value, locations: [...value.locations, { name: '', desc: '' }] })} className="focus-ring inline-flex h-10 items-center gap-1 rounded-md px-2 text-[13px] text-primary hover:bg-primary-soft/60"><Plus className="h-3.5 w-3.5" />添加地点</button>
        </div>
      </Box>
    </div>
  )
}

function FactionsEdit({ value, kw, onChange }: { value: SourceFaction[]; kw: string; onChange: (v: SourceFaction[]) => void }) {
  const all = value.map((_, i) => i).filter((i) => hit(kw, value[i].name, value[i].stance, value[i].members, value[i].notes))
  const pg = usePaged(all, kw)
  return (
    <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))]">
      {pg.idx.map((i) => { const f = value[i]
        const p = (x: Partial<SourceFaction>) => onChange(upd(value, i, x))
        return (
          <Box key={i} className="space-y-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <Input className="h-10 min-w-0 flex-1 font-semibold" placeholder="势力名" value={f.name} onChange={(e) => p({ name: e.target.value })} />
              <RemoveBtn label="删除势力" onClick={() => onChange(value.filter((_, k) => k !== i))} />
            </div>
            <div><Lbl>立场</Lbl><Input className="h-10" value={f.stance} onChange={(e) => p({ stance: e.target.value })} /></div>
            <div><Lbl>成员</Lbl><Chips value={f.members} onChange={(v) => p({ members: v })} /></div>
            <div><Lbl>备注</Lbl><Textarea rows={2} value={f.notes} onChange={(e) => p({ notes: e.target.value })} /></div>
          </Box>
        )
      })}
      <div className="col-span-full"><Pager page={pg.page} pages={pg.pages} onChange={pg.setPage} /></div>
      {!kw && <div className="col-span-full"><AddBtn onClick={() => { onChange([...value, { name: '', stance: '', members: [], notes: '' }]); pg.setPage(Math.ceil((value.length + 1) / PAGE)) }}>添加势力</AddBtn></div>}
    </div>
  )
}

function TimelineEdit({ value, kw, onChange }: { value: SourceTimelineItem[]; kw: string; onChange: (v: SourceTimelineItem[]) => void }) {
  const all = value.map((_, i) => i).filter((i) => hit(kw, value[i].event, value[i].characters, value[i].impact))
  const pg = usePaged(all, kw, 20)
  return (
    <div className="space-y-2">
      {pg.idx.map((i) => { const t = value[i]
        const p = (x: Partial<SourceTimelineItem>) => onChange(upd(value, i, x))
        return (
          <Box key={i} className="space-y-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <Input type="number" inputMode="numeric" aria-label="顺序" className="num h-10 w-16 shrink-0 text-center" value={t.order} onChange={(e) => p({ order: Number(e.target.value) || 0 })} />
              <Input className="h-10 min-w-0 flex-1" placeholder="事件（≤80 字）" value={t.event} onChange={(e) => p({ event: e.target.value.slice(0, 80) })} />
              <RemoveBtn label="删除事件" onClick={() => onChange(value.filter((_, k) => k !== i))} />
            </div>
            <div><Lbl>涉及角色</Lbl><Chips value={t.characters} onChange={(v) => p({ characters: v })} /></div>
            <div><Lbl>影响</Lbl><Input className="h-10" value={t.impact} onChange={(e) => p({ impact: e.target.value })} /></div>
          </Box>
        )
      })}
      <Pager page={pg.page} pages={pg.pages} onChange={pg.setPage} />
      {kw && !all.length && <p className="py-4 text-center text-[12.5px] text-muted-foreground">没有匹配的事件</p>}
      {value.length < 120 && !kw && <AddBtn onClick={() => { onChange([...value, { order: (value.at(-1)?.order ?? 0) + 1, event: '', characters: [], impact: '' }]); pg.setPage(Math.ceil((value.length + 1) / 20)) }}>添加事件</AddBtn>}
      {value.length > 1 && !kw && (
        <Button variant="ghost" className="h-10 w-full" onClick={() => onChange([...value].sort((a, b) => a.order - b.order))}>按顺序号重新排序</Button>
      )}
    </div>
  )
}

function ScenesEdit({ value, kw, onChange }: { value: SourceScene[]; kw: string; onChange: (v: SourceScene[]) => void }) {
  const all = value.map((_, i) => i).filter((i) => hit(kw, value[i].title, value[i].summary, value[i].characters))
  const pg = usePaged(all, kw)
  return (
    <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,320px),1fr))]">
      {pg.idx.map((i) => { const s = value[i]
        const p = (x: Partial<SourceScene>) => onChange(upd(value, i, x))
        return (
          <Box key={i} className="space-y-2">
            <div className="flex min-w-0 items-center gap-1.5">
              <Input className="h-10 min-w-0 flex-1 font-semibold" placeholder="名场面标题" value={s.title} onChange={(e) => p({ title: e.target.value })} />
              <RemoveBtn label="删除名场面" onClick={() => onChange(value.filter((_, k) => k !== i))} />
            </div>
            <div><Lbl hint={`${s.summary.length}/160`}>概要（用自己的话）</Lbl><Textarea rows={3} value={s.summary} onChange={(e) => p({ summary: e.target.value.slice(0, 160) })} /></div>
            <div><Lbl>角色</Lbl><Chips value={s.characters} onChange={(v) => p({ characters: v })} /></div>
          </Box>
        )
      })}
      <div className="col-span-full"><Pager page={pg.page} pages={pg.pages} onChange={pg.setPage} /></div>
      {value.length < 30 && !kw && <div className="col-span-full"><AddBtn onClick={() => { onChange([...value, { title: '', summary: '', characters: [] }]); pg.setPage(Math.ceil((value.length + 1) / PAGE)) }}>添加名场面</AddBtn></div>}
    </div>
  )
}


/** v0.14.0 关系索引：把各角色的关系摊平成「谁 — 关系 — 谁」一张表，改动写回对应角色 */
function RelationsEdit({ value, kw, onChange }: { value: SourceCharacter[]; kw: string; onChange: (v: SourceCharacter[]) => void }) {
  const rows = value.flatMap((c, ci) => c.relations.map((r, ri) => ({ ci, ri, from: c.name, ...r })))
  const all = rows.map((_, i) => i).filter((i) => hit(kw, rows[i].from, rows[i].target, rows[i].relation))
  const pg = usePaged(all, kw, 30)
  const [adder, setAdder] = useState<string | null>(null)
  const setRel = (ci: number, ri: number, patch: Partial<{ target: string; relation: string }>) =>
    onChange(upd(value, ci, { relations: upd(value[ci].relations, ri, patch) }))
  const move = (ci: number, ri: number, to: number) => {
    if (to === ci || to < 0) return
    const r = value[ci].relations[ri]
    onChange(value.map((c, k) => (k === ci ? { ...c, relations: c.relations.filter((_, j) => j !== ri) } : k === to ? { ...c, relations: [...c.relations, r] } : c)))
  }
  const names = value.map((c, i) => ({ value: String(i), label: c.name || `未命名 #${i + 1}` }))
  if (!value.length) return <p className="py-6 text-center text-[12.5px] text-muted-foreground">还没有角色，先在角色档案里添加</p>
  return (
    <div className="space-y-1.5">
      {pg.idx.map((i) => {
        const r = rows[i]
        return (
          <div key={`${r.ci}-${r.ri}`} className="flex min-w-0 flex-wrap items-center gap-1.5 rounded-xl border bg-surface p-2 sm:flex-nowrap">
            <Select value={String(r.ci)} onChange={(v) => v != null && move(r.ci, r.ri, Number(v))} className="h-10 w-full sm:w-[28%]" options={names} />
            <Input className="h-10 min-w-0 flex-1" placeholder="关系，如：师徒、宿敌" value={r.relation} onChange={(e) => setRel(r.ci, r.ri, { relation: e.target.value })} />
            <Input className="h-10 min-w-0 flex-1 sm:w-[28%] sm:flex-none" placeholder="对象" value={r.target} onChange={(e) => setRel(r.ci, r.ri, { target: e.target.value })} />
            <RemoveBtn onClick={() => onChange(upd(value, r.ci, { relations: value[r.ci].relations.filter((_, j) => j !== r.ri) }))} />
          </div>
        )
      })}
      <Pager page={pg.page} pages={pg.pages} onChange={pg.setPage} />
      {!all.length && <p className="py-4 text-center text-[12.5px] text-muted-foreground">{kw ? '没有匹配的关系' : '还没有关系条目'}</p>}
      {!kw && (
        <div className="flex min-w-0 items-center gap-1.5 pt-1">
          <Select value={adder} onChange={(v) => setAdder(v)} placeholder="选一个角色" className="h-10 min-w-0 flex-1" options={names} />
          <Button variant="soft" className="h-10 shrink-0" icon={<Plus className="h-4 w-4" />} disabled={adder == null}
            onClick={() => { const ci = Number(adder); onChange(upd(value, ci, { relations: [...value[ci].relations, { target: '', relation: '' }] })); pg.setPage(Math.ceil((rows.length + 1) / 30)) }}>添加关系</Button>
        </div>
      )}
    </div>
  )
}
