import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, CloudUpload, FileText, Loader2, Plus, Search, X } from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { BookCover } from '@/components/radar/BookCover'
import { chapterText } from '@/components/radar/ShelfCard'
import { api, qk } from '@/lib/api'
import type { Gender, ImitateExtract, RankBoard, RankItem } from '@/lib/types'
import { cn, fmtNum } from '@/lib/utils'

const BOARDS: { g: Gender; b: RankBoard; label: string }[] = [
  { g: 'male', b: 'read', label: '男频阅读榜' }, { g: 'male', b: 'new', label: '男频新书榜' },
  { g: 'female', b: 'read', label: '女频阅读榜' }, { g: 'female', b: 'new', label: '女频新书榜' },
]
const PAGE = 20
export const bareLen = (s: string) => s.replace(/\s/g, '').length

/** 胶囊按钮（与雷达页题材胶囊同款，触控高度 32px） */
export function Pill({ active, children, onClick, className }: { active?: boolean; children: React.ReactNode; onClick: () => void; className?: string }) {
  return (
    <button type="button" onClick={onClick}
      className={cn('inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-3 text-[13px] transition', active ? 'bg-foreground text-background' : 'bg-muted/70 text-foreground/75 hover:bg-muted hover:text-foreground', className)}>
      {children}
    </button>
  )
}

/** 榜单选书：4 榜 tab + 题材胶囊 + 搜索 + 紧凑书架列表（整页滚动，不做内滚动） */
export function BookPicker({ selected, onToggle, max = 3, single, initial }: {
  selected: RankItem[]; onToggle: (i: RankItem) => void; max?: number; single?: boolean; initial?: { gender?: Gender; board?: RankBoard }
}) {
  const [tab, setTab] = useState(() => Math.max(0, BOARDS.findIndex((x) => x.g === (initial?.gender ?? 'male') && x.b === (initial?.board ?? 'read'))))
  const { g, b } = BOARDS[tab]
  const [cat, setCat] = useState('')
  const [kw, setKw] = useState('')
  const [limit, setLimit] = useState(PAGE)
  useEffect(() => { setCat(''); setLimit(PAGE) }, [tab])
  useEffect(() => setLimit(PAGE), [cat, kw])
  const q = useQuery({ queryKey: qk.radarLatest(g, '', b), queryFn: () => api.radarLatest({ gender: g, board: b }) })
  const items = q.data?.items ?? []
  const cats = useMemo(() => {
    const m = new Map<string, number>()
    items.forEach((i) => m.set(i.category, (m.get(i.category) ?? 0) + 1))
    return [...m.entries()].sort((x, y) => y[1] - x[1])
  }, [items])
  const k = kw.trim().toLowerCase()
  const list = items.filter((i) => (!cat || i.category === cat) && (!k || i.title.toLowerCase().includes(k) || (i.author || '').toLowerCase().includes(k)))
  const isSel = (i: RankItem) => selected.some((x) => x.book_id_ext === i.book_id_ext)
  const full = selected.length >= max

  return (
    <div className="space-y-3">
      <div className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-0.5 [scrollbar-width:none]">
        {BOARDS.map((x, i) => (
          <button key={x.label} type="button" onClick={() => setTab(i)}
            className={cn('h-9 shrink-0 rounded-lg px-3.5 text-[13px] font-medium transition', tab === i ? 'bg-primary text-primary-foreground shadow-card' : 'bg-surface text-foreground/75 hairline hover:bg-subtle')}>
            {x.label}
          </button>
        ))}
      </div>
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜索书名、作者" className="h-10 pl-9" />
        {kw && <button type="button" aria-label="清空搜索" onClick={() => setKw('')} className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"><X className="h-4 w-4" /></button>}
      </div>
      {cats.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <Pill active={!cat} onClick={() => setCat('')}>🏆 总榜<span className="num opacity-55">{items.length}</span></Pill>
          {cats.map(([c, n]) => <Pill key={c} active={cat === c} onClick={() => setCat(c)}>{c}<span className="num opacity-55">{n}</span></Pill>)}
        </div>
      )}

      {q.isLoading ? (
        <div className="grid gap-2 md:grid-cols-2">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[76px] rounded-xl" />)}</div>
      ) : !list.length ? (
        <div className="rounded-xl border border-dashed px-4 py-8 text-center text-[13px] text-muted-foreground">{items.length ? '没有匹配的书' : '这个榜还没有数据，先去热点雷达刷新榜单'}</div>
      ) : (
        <>
          <div className="grid gap-2 md:grid-cols-2">
            {list.slice(0, limit).map((i, n) => {
              const on = isSel(i)
              const dis = !single && !on && full
              return (
                <button key={`${i.category}-${i.book_id_ext}`} type="button" disabled={dis} onClick={() => onToggle(i)} aria-pressed={on}
                  className={cn('group flex min-w-0 items-center gap-3 rounded-xl border bg-surface p-2.5 text-left transition active:scale-[0.995] disabled:opacity-45',
                    on ? 'border-primary/50 bg-primary-soft/40 ring-1 ring-primary/30' : 'hover:border-foreground/15 hover:shadow-card')}>
                  <span className={cn('num w-6 shrink-0 text-center font-serif text-[17px] font-bold italic', (cat ? i.rank : n + 1) <= 3 ? 'text-primary' : 'text-foreground/25')}>{cat ? i.rank : n + 1}</span>
                  <BookCover src={i.cover} title={i.title} size="sm" className="w-[42px] shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold leading-snug">{i.title}</span>
                    <span className="num mt-0.5 block truncate text-[12px] text-muted-foreground">{i.author || '佚名'} · {chapterText(i.chapter_count)} · 在读 {fmtNum(i.read_count)}</span>
                    <span className="mt-1 inline-block rounded bg-muted/80 px-1.5 text-[11px] leading-[18px] text-muted-foreground">{i.category}</span>
                  </span>
                  <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-full border transition', on ? 'border-primary bg-primary text-primary-foreground' : 'text-muted-foreground group-hover:border-foreground/30')}>
                    {on ? <Check className="h-4 w-4" strokeWidth={2.5} /> : <Plus className="h-4 w-4" />}
                  </span>
                </button>
              )
            })}
          </div>
          {list.length > limit && <div className="text-center"><Button variant="ghost" size="sm" className="h-9" onClick={() => setLimit((l) => l + PAGE)}>显示更多（{list.length - limit}）</Button></div>}
        </>
      )}
    </div>
  )
}

export interface TextDoc { title: string; text: string; chapters: ImitateExtract['chapters']; from: 'upload' | 'paste'; total?: number; truncated?: boolean }

/** 上传 TXT（后端识别章节）或粘贴正文 */
/** live：粘贴/输入后立即把当前正文交给 onChange（不用先点「使用这段正文」），章节识别在后台静默进行 */
export function TextSource({ mode, value, onChange, maxChars, live }: { mode: 'upload' | 'paste'; value: TextDoc | null; onChange: (d: TextDoc | null) => void; maxChars?: number; live?: boolean }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [paste, setPaste] = useState(value?.from === 'paste' ? value.text : '')
  const [title, setTitle] = useState(value?.from === 'paste' ? value.title : '')
  const [showAll, setShowAll] = useState(false)
  const n = bareLen(paste)
  // live 模式：正文一变就交出去（标题取输入框），停顿 900ms 后后台识别章节，识别期间正文又变了就丢弃结果
  const liveSeq = useRef(0)
  const liveSet = (text: string, t: string) => {
    if (!live) return
    const seq = ++liveSeq.current
    if (!bareLen(text)) { onChange(null); return }
    onChange({ title: t.trim(), text, chapters: [], from: 'paste' })
    window.setTimeout(async () => {
      if (seq !== liveSeq.current) return
      try {
        const r = await api.imitateExtract(text)
        if (seq !== liveSeq.current) return
        onChange({ title: t.trim(), text, chapters: r.chapters ?? [], from: 'paste', total: r.total_chapters, truncated: r.truncated })
      } catch { /* 识别失败不影响使用：按一整段处理 */ }
    }, 900)
  }

  const upload = async (f?: File | null) => {
    if (!f) return
    if (!/\.txt$/i.test(f.name) && f.type && f.type !== 'text/plain') { toast.error('只支持 .txt 文本文件'); return }
    setBusy(true)
    try {
      const r = await api.imitateExtract(f)
      onChange({ title: r.title_guess || f.name.replace(/\.txt$/i, ''), text: r.text, chapters: r.chapters ?? [], from: 'upload', total: r.total_chapters, truncated: r.truncated })
      toast.success(r.total_chapters ? `识别出 ${r.total_chapters} 章，取前 ${r.chapters?.length ?? 0} 章` : '没识别出章节，按全文处理')
    } catch (e: any) {
      toast.error('读取失败', { description: e?.message })
    } finally { setBusy(false); if (fileRef.current) fileRef.current.value = '' }
  }
  const detect = async () => {
    setBusy(true)
    try {
      const r = await api.imitateExtract(paste)
      const guess = r.title_guess && !/^\s*(第[一二三四五六七八九十百千零\d]+[章节回]|chapter\s*\d)/i.test(r.title_guess) ? r.title_guess : ''
      onChange({ title: title.trim() || guess || '粘贴的正文', text: r.text || paste, chapters: r.chapters ?? [], from: 'paste', total: r.total_chapters, truncated: r.truncated })
    } catch (e: any) {
      // 识别失败不影响使用：按一整段处理
      onChange({ title: title.trim() || '粘贴的正文', text: paste, chapters: [], from: 'paste' })
      toast.info('没能识别章节，按一整段处理', { description: e?.message })
    } finally { setBusy(false) }
  }

  if (mode === 'upload') {
    return (
      <div className="space-y-3">
        <input ref={fileRef} type="file" accept=".txt,text/plain" className="hidden" onChange={(e) => void upload(e.target.files?.[0])} />
        <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void upload(e.dataTransfer.files?.[0]) }}
          className="flex w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed bg-subtle/40 px-4 py-7 text-center transition hover:border-primary/40 hover:bg-primary-soft/30">
          {busy ? <Loader2 className="h-7 w-7 animate-spin text-primary" /> : <CloudUpload className="h-7 w-7 text-primary/80" />}
          <span className="text-[14px] font-medium">{busy ? '正在识别章节…' : value?.from === 'upload' ? '换一个 TXT 文件' : '点击选择 TXT 文件'}</span>
          <span className="text-[12px] text-muted-foreground">UTF-8 / GBK 均可，章节标题单独成行识别更准；原文只用于拆解，不保存</span>
        </button>
        {value?.from === 'upload' && <ChapterList doc={value} showAll={showAll} onToggle={() => setShowAll((x) => !x)} onClear={() => onChange(null)} maxChars={maxChars} />}
      </div>
    )
  }
  return (
    <div className="space-y-3">
      <Input value={title} onChange={(e) => { setTitle(e.target.value); if (live && value?.from === 'paste') onChange({ ...value, title: e.target.value.trim() }) }} placeholder="书名（可选）" className="h-10" />
      <Textarea rows={8} value={paste} onChange={(e) => { setPaste(e.target.value); if (live) liveSet(e.target.value, title); else if (value?.from === 'paste') onChange(null) }}
        placeholder={'把正文粘贴到这里，章节标题单独成行效果最好，例如：\n第一章 xxx\n正文……'} className="min-h-[200px] font-serif text-[13.5px]" />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={cn('num text-[12px]', maxChars && n > maxChars ? 'font-medium text-danger' : 'text-muted-foreground')}>{n.toLocaleString('zh-CN')}{maxChars ? ` / ${maxChars.toLocaleString('zh-CN')}` : ''} 字</span>
        {live ? (
          n > 0 && <span className="inline-flex items-center gap-1 text-[12px] text-success"><Check className="h-3.5 w-3.5" />{value?.chapters.length ? `识别出 ${value.total ?? value.chapters.length} 章，可以直接开始` : '可以直接开始'}</span>
        ) : (
          <Button size="sm" variant={value?.from === 'paste' ? 'soft' : 'primary'} className="h-9" disabled={!n} loading={busy} icon={value?.from === 'paste' ? <Check className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />} onClick={() => void detect()}>
            {value?.from === 'paste' ? '已使用这段正文' : '使用这段正文'}
          </Button>
        )}
      </div>
      {value?.from === 'paste' && value.chapters.length > 0 && <ChapterList doc={value} showAll={showAll} onToggle={() => setShowAll((x) => !x)} maxChars={maxChars} />}
    </div>
  )
}

function ChapterList({ doc, showAll, onToggle, onClear, maxChars }: { doc: TextDoc; showAll: boolean; onToggle: () => void; onClear?: () => void; maxChars?: number }) {
  const total = doc.chapters.reduce((s, c) => s + (c.chars || 0), 0) || bareLen(doc.text)
  const vis = showAll ? doc.chapters : doc.chapters.slice(0, 6)
  return (
    <div className="rounded-xl border bg-surface">
      <div className="flex items-center gap-2 border-b px-3.5 py-2.5">
        <FileText className="h-4 w-4 shrink-0 text-primary" />
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-semibold">{doc.title}</span>
        <span className="num shrink-0 text-[12px] text-muted-foreground">{doc.total && doc.total > doc.chapters.length ? `共 ${doc.total} 章 · 取前 ${doc.chapters.length} 章` : `${doc.chapters.length} 章`} · {total.toLocaleString('zh-CN')} 字</span>
        {onClear && <button type="button" aria-label="移除" onClick={onClear} className="-mr-1.5 flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted"><X className="h-4 w-4" /></button>}
      </div>
      {doc.chapters.length > 0 && (
        <ol className="divide-y divide-border/60">
          {vis.map((c, i) => (
            <li key={i} className="flex items-center gap-3 px-3.5 py-2 text-[13px]">
              <span className="num w-6 shrink-0 text-right text-[11.5px] text-muted-foreground">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate">{c.title || `第 ${i + 1} 段`}</span>
              <span className="num shrink-0 text-[12px] text-muted-foreground">{fmtNum(c.chars)} 字</span>
            </li>
          ))}
        </ol>
      )}
      {doc.chapters.length > 6 && (
        <button type="button" onClick={onToggle} className="flex h-10 w-full items-center justify-center gap-1 border-t text-[12.5px] text-muted-foreground hover:text-foreground">
          {showAll ? '收起' : `展开全部 ${doc.chapters.length} 章`}<ChevronDown className={cn('h-3.5 w-3.5 transition-transform', showAll && 'rotate-180')} />
        </button>
      )}
      {doc.truncated && <p className="border-t px-3.5 py-2 text-[12px] text-muted-foreground">前 {doc.chapters.length} 章超过 20,000 字，已截断</p>}
      {maxChars && total > maxChars && <p className="border-t px-3.5 py-2 text-[12px] text-warning">超过 {maxChars.toLocaleString('zh-CN')} 字，深度拆解只取前 {maxChars.toLocaleString('zh-CN')} 字</p>}
    </div>
  )
}
