import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  ChartBar, Check, Copy, Dice, MessageDots, Notebook, Search, Sliders, Smartphone, TextAa, Toolbox, Wand2,
} from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Switch } from '@/components/ui/switch'
import { JobInline } from '@/components/common/JobInline'
import { qk, v013Api } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { ChapterTitles, ContextPreview, FreqItem, ReaderComments, SearchHit, SearchResult, SearchScope, Spark } from '@/lib/types'
import { cn, countWords, fmtNum } from '@/lib/utils'

type Tool = 'titles' | 'comments' | 'freq' | 'phone' | 'search' | 'sparks' | 'context'
const TOOLS: { key: Tool; label: string; icon: typeof TextAa }[] = [
  { key: 'titles', label: '起章名', icon: TextAa }, { key: 'comments', label: '神评', icon: MessageDots },
  { key: 'sparks', label: '脑洞抽卡', icon: Dice }, { key: 'freq', label: '高频词', icon: ChartBar },
  { key: 'phone', label: '手机预览', icon: Smartphone }, { key: 'search', label: '查找替换', icon: Search },
  { key: 'context', label: '上下文构成', icon: Sliders },
]

/** 章节工具条的「工具」菜单：章名 / 神评 / 脑洞 / 高频词 / 手机预览 / 查找替换 / 上下文构成 */
export function ChapterToolsMenu({ bookId, chapterId, title, content, onTitle, onLocate, onRewrite, onFormat, className, disabled }: {
  bookId: number; chapterId: number; title: string; content: string
  onTitle: (t: string) => void; onLocate: (q: string) => void; onRewrite: (instruction: string) => void; onFormat?: () => void
  className?: string; disabled?: boolean
}) {
  const [open, setOpen] = useState<Tool | null>(null)
  const [menu, setMenu] = useState(false)
  return (
    <>
      <Popover open={menu} onOpenChange={setMenu}>
        <PopoverTrigger asChild>
          <Button size="sm" variant="ghost" className={className} icon={<Toolbox className="h-3.5 w-3.5" />} disabled={disabled}>工具</Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[220px] p-1.5">
          {TOOLS.map((t) => (
            <button key={t.key} type="button" onClick={() => { setMenu(false); setOpen(t.key) }}
              className="flex h-10 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] hover:bg-muted">
              <t.icon className="h-4 w-4 text-foreground/60" />{t.label}
            </button>
          ))}
          {onFormat && (
            <button type="button" onClick={() => { setMenu(false); onFormat() }} className="flex h-10 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] hover:bg-muted">
              <Wand2 className="h-4 w-4 text-foreground/60" />排版规范
            </button>
          )}
        </PopoverContent>
      </Popover>
      <TitlesSheet open={open === 'titles'} onClose={() => setOpen(null)} chapterId={chapterId} current={title} onPick={onTitle} />
      <CommentsSheet open={open === 'comments'} onClose={() => setOpen(null)} chapterId={chapterId} onLocate={onLocate} onRewrite={onRewrite} />
      <SparksSheet open={open === 'sparks'} onClose={() => setOpen(null)} bookId={bookId} />
      <FreqSheet open={open === 'freq'} onClose={() => setOpen(null)} chapterId={chapterId} content={content} onLocate={onLocate}
        onRewrite={(w) => onRewrite(`这些词用得太多，换成不同的说法，或直接删掉：${w.join('、')}`)} />
      <PhoneSheet open={open === 'phone'} onClose={() => setOpen(null)} title={title} content={content} />
      <SearchReplaceSheet bookId={bookId} open={open === 'search'} onOpenChange={(o) => !o && setOpen(null)} />
      <ContextSheet open={open === 'context'} onClose={() => setOpen(null)} bookId={bookId} chapterId={chapterId} />
    </>
  )
}

function useToolJob<T>(key: string) {
  const { start } = useJobs()
  const active = useActiveJob(key)
  const [data, setData] = useState<T | null>(null)
  const run = (p: Promise<import('@/lib/types').Job>, label: string) =>
    start(p, { key, label, silent: true, onSuccess: (j) => setData(j.result as T) })
  return { active, data, setData, run }
}

function TitlesSheet({ open, onClose, chapterId, current, onPick }: { open: boolean; onClose: () => void; chapterId: number; current: string; onPick: (t: string) => void }) {
  const { active, data, run } = useToolJob<ChapterTitles>(`titles:${chapterId}`)
  const res = data?.chapter_id === chapterId ? data : null
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="起章名" width={520}
      footer={<Button variant="primary" loading={!!active} onClick={() => void run(v013Api.titles(chapterId, 7), '起章名')}>{res ? '换一批' : '生成候选'}</Button>}>
      <div className="space-y-3">
        <div className="rounded-lg bg-subtle px-3 py-2 text-[13px]"><span className="text-muted-foreground">现在：</span>{current || '（无）'}</div>
        {active && <JobInline job={active} />}
        {res?.titles.map((t) => (
          <button key={t.title} type="button" onClick={() => { onPick(t.title); toast.success(`章名改为「${t.title}」`) }}
            className={cn('flex w-full min-w-0 items-start gap-3 rounded-xl border bg-surface px-3.5 py-3 text-left transition hover:border-primary/50', t.title === current && 'border-primary')}>
            <span className="num flex h-8 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-[13px] font-semibold text-primary">{t.score}</span>
            <span className="min-w-0 flex-1">
              <span className="block text-[14.5px] font-semibold">{t.title}</span>
              {t.reason && <span className="mt-0.5 block text-[12.5px] text-muted-foreground">{t.reason}</span>}
              {t.notes.length > 0 && <span className="mt-1 flex flex-wrap gap-1">{t.notes.map((n) => <Badge key={n} tone="warning">{n}</Badge>)}</span>}
            </span>
          </button>
        ))}
      </div>
    </Sheet>
  )
}

const MOOD: Record<string, string> = { 爽: 'bg-success-soft text-success', 笑: 'bg-primary-soft text-primary', 急: 'bg-warning-soft text-warning', 烦: 'bg-danger-soft text-danger', 猜: 'bg-muted text-foreground/70' }

function CommentsSheet({ open, onClose, chapterId, onLocate, onRewrite }: { open: boolean; onClose: () => void; chapterId: number; onLocate: (q: string) => void; onRewrite: (s: string) => void }) {
  const { active, data, run } = useToolJob<ReaderComments>(`comments:${chapterId}`)
  const res = data?.chapter_id === chapterId ? data : null
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="神评" width={560}
      footer={<>
        {res?.instruction && <Button icon={<Wand2 className="h-4 w-4" />} onClick={() => { onClose(); onRewrite(res.instruction) }}>按弃读点改写</Button>}
        <Button variant="primary" loading={!!active} onClick={() => void run(v013Api.readerComments(chapterId, 4), '神评')}>{res ? '再来一轮' : '生成段评'}</Button>
      </>}>
      <div className="space-y-4">
        {active && <JobInline job={active} />}
        {res && (
          <>
            <div className="flex flex-wrap gap-2">
              {res.continue_rate != null && <Badge tone={res.continue_rate >= 0.75 ? 'success' : res.continue_rate >= 0.5 ? 'warning' : 'danger'}>追读 {Math.round(res.continue_rate * 100)}%</Badge>}
              {res.verdicts.map((v) => <Badge key={v.persona} tone={v.will_continue ? 'outline' : 'danger'}>{v.persona}{v.will_continue ? ' 会追' : ' 想弃'}</Badge>)}
            </div>
            {res.verdicts.filter((v) => v.drop).map((v) => (
              <button key={v.persona} type="button" onClick={() => onLocate(v.drop)} className="block w-full rounded-xl bg-danger-soft/50 px-3.5 py-2.5 text-left">
                <div className="text-[12px] font-medium text-danger">{v.persona} 在这里想划走{v.why ? `：${v.why}` : ''}</div>
                <p className="mt-1 line-clamp-2 font-serif text-[13.5px] text-foreground/80">「{v.drop}」</p>
              </button>
            ))}
            <div className="space-y-2">
              {res.comments.map((c, i) => (
                <button key={i} type="button" onClick={() => onLocate(c.quote)} className="block w-full rounded-xl bg-surface px-3.5 py-2.5 text-left hairline hover:bg-subtle">
                  <p className="line-clamp-2 border-l-2 border-primary/40 pl-2 font-serif text-[13px] text-foreground/60">{c.quote}</p>
                  <div className="mt-1.5 flex items-center gap-2">
                    <span className="text-[12px] font-medium text-foreground/70">{c.persona}</span>
                    {c.mood && <span className={cn('rounded px-1.5 text-[11px] leading-[18px]', MOOD[c.mood] ?? 'bg-muted')}>{c.mood}</span>}
                  </div>
                  <p className="mt-0.5 text-[13.5px]">{c.text}</p>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </Sheet>
  )
}

function SparksSheet({ open, onClose, bookId }: { open: boolean; onClose: () => void; bookId: number }) {
  const { active, data, run } = useToolJob<{ book_id: number; sparks: Spark[] }>(`sparks:${bookId}`)
  const [ctx, setCtx] = useState(true)
  const [hint, setHint] = useState('')
  const [saved, setSaved] = useState<Record<string, boolean>>({})
  const qc = useQueryClient()
  const save = useMutation({
    mutationFn: (sp: Spark) => v013Api.sparkToNote(bookId, sp),
    meta: { errorTitle: '存笔记失败' },
    onSuccess: (_n, sp) => { setSaved((m) => ({ ...m, [sp.title]: true })); qc.invalidateQueries({ queryKey: ['notes', bookId] }); toast.success('已存进笔记「脑洞」') },
  })
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="脑洞抽卡" width={560}
      footer={<Button variant="primary" loading={!!active} icon={<Dice className="h-4 w-4" />} onClick={() => void run(v013Api.sparks(bookId, { n: 5, use_context: ctx, hint }), '脑洞抽卡')}>{data ? '再抽一次' : '抽 5 个'}</Button>}>
      <div className="space-y-3">
        <Field label="方向"><Input value={hint} onChange={(e) => setHint(e.target.value)} placeholder="如：下一章要一个打脸；想加一条感情线" className="h-10" /></Field>
        <label className="flex min-h-[40px] cursor-pointer items-center justify-between gap-3 text-[13.5px]">参考本书设定和最近剧情<Switch checked={ctx} onCheckedChange={setCtx} /></label>
        {active && <JobInline job={active} />}
        {data?.sparks.map((sp) => (
          <div key={sp.title} className="rounded-xl bg-surface p-3.5 hairline">
            <div className="flex items-start gap-2">
              <span className="min-w-0 flex-1 text-[14.5px] font-semibold">{sp.title}</span>
              {sp.fit && <Badge tone="outline">{sp.fit}</Badge>}
            </div>
            <p className="mt-1.5 text-[13px] leading-relaxed text-foreground/80">{sp.beat}</p>
            {sp.payoff && <p className="mt-1 text-[12.5px] text-primary">爽点：{sp.payoff}</p>}
            <div className="mt-2 flex justify-end gap-1.5">
              <Button size="sm" variant="ghost" icon={<Copy className="h-3.5 w-3.5" />} onClick={() => { void navigator.clipboard?.writeText(`${sp.title}\n${sp.beat}`); toast.success('已复制') }}>复制</Button>
              <Button size="sm" variant="soft" icon={saved[sp.title] ? <Check className="h-3.5 w-3.5" /> : <Notebook className="h-3.5 w-3.5" />} disabled={saved[sp.title]} loading={save.isPending && save.variables?.title === sp.title} onClick={() => save.mutate(sp)}>{saved[sp.title] ? '已存' : '存笔记'}</Button>
            </div>
          </div>
        ))}
      </div>
    </Sheet>
  )
}

export function FreqList({ items, onPick, picked }: { items: FreqItem[]; onPick?: (w: string) => void; picked?: string[] }) {
  if (!items.length) return <p className="py-6 text-center text-[12.5px] text-muted-foreground">没有明显的高频词</p>
  const max = items[0]?.count || 1
  return (
    <div className="space-y-1">
      {items.map((it) => (
        <button key={it.word} type="button" onClick={() => onPick?.(it.word)} disabled={!onPick}
          className={cn('flex h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-[13px] transition', onPick && 'hover:bg-muted', picked?.includes(it.word) && 'bg-primary-soft')}>
          <span className="w-[5.5em] shrink-0 truncate font-medium">{it.word}</span>
          <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted"><span className="block h-full rounded-full bg-primary/60" style={{ width: `${(it.count / max) * 100}%` }} /></span>
          <span className="num w-10 shrink-0 text-right text-muted-foreground">{it.count}</span>
        </button>
      ))}
    </div>
  )
}

function FreqSheet({ open, onClose, chapterId, content, onLocate, onRewrite }: { open: boolean; onClose: () => void; chapterId: number; content: string; onLocate: (q: string) => void; onRewrite: (w: string[]) => void }) {
  const q = useQuery({ queryKey: ['chapter-freq', chapterId, content.length], queryFn: () => v013Api.chapterFreq(chapterId), enabled: open })
  const [picked, setPicked] = useState<string[]>([])
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="高频词" width={460}
      footer={<Button variant="primary" disabled={!picked.length} icon={<Wand2 className="h-4 w-4" />} onClick={() => { onClose(); onRewrite(picked) }}>改掉选中的 {picked.length || ''}</Button>}>
      {q.isLoading ? <Skeleton className="h-64 rounded-xl" /> : (
        <FreqList items={q.data?.items ?? []} picked={picked} onPick={(w) => { setPicked((p) => (p.includes(w) ? p.filter((x) => x !== w) : [...p, w])); onLocate(w) }} />
      )}
    </Sheet>
  )
}

/** 按番茄阅读器版式渲染：375 宽、首屏约 360 字，标出首屏边界和第一处冲突 */
function PhoneSheet({ open, onClose, title, content }: { open: boolean; onClose: () => void; title: string; content: string }) {
  const paras = useMemo(() => content.split('\n').map((p) => p.trim()).filter(Boolean), [content])
  const FIRST = 360
  let acc = 0
  let foldAt = paras.length
  for (let i = 0; i < paras.length; i++) { acc += paras[i].length; if (acc > FIRST) { foldAt = i; break } }
  const conflictRe = /[！？!?]|不|怒|杀|滚|冷笑|拦|退婚|跪|打|血/
  const firstConflict = paras.findIndex((p) => conflictRe.test(p))
  const words = countWords(content)
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="手机预览" width={460}>
      <div className="mb-3 flex flex-wrap gap-2">
        <Badge tone="outline">{fmtNum(words)} 字</Badge>
        <Badge tone={firstConflict >= 0 && firstConflict <= foldAt ? 'success' : 'warning'}>{firstConflict >= 0 && firstConflict <= foldAt ? '首屏有冲突' : '首屏没冲突'}</Badge>
        <Badge tone="outline">{paras.filter((p) => p.length > 100).length} 段超过 100 字</Badge>
      </div>
      <div className="mx-auto w-[375px] max-w-full overflow-hidden rounded-[28px] border-[6px] border-foreground/80 bg-[#f6f1e5] shadow-pop dark:bg-[#1f1d1a]">
        <div className="h-[640px] overflow-y-auto px-5 py-6 font-serif text-[18px] leading-[1.85] text-[#2b2622] dark:text-[#d9d2c3]">
          <h3 className="mb-5 text-[20px] font-semibold">{title}</h3>
          {paras.map((p, i) => (
            <div key={i}>
              {i === foldAt && <div className="my-3 border-t-2 border-dashed border-primary/60 text-center text-[11px] text-primary">首屏到这里</div>}
              <p className={cn('mb-[0.9em] indent-[2em]', i === firstConflict && 'rounded bg-primary-soft/60', p.length > 100 && 'bg-warning-soft/50')}>{p}</p>
            </div>
          ))}
        </div>
      </div>
    </Sheet>
  )
}

const SCOPES: { value: SearchScope; label: string }[] = [{ value: 'chapters', label: '正文' }, { value: 'cards', label: '设定' }, { value: 'outline', label: '大纲' }, { value: 'notes', label: '笔记' }]
const hitKey = (h: SearchHit) => `${h.scope}:${h.id}:${h.field}:${h.offset}`

export function SearchReplaceSheet({ bookId, open, onOpenChange }: { bookId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const [q, setQ] = useState('')
  const [rep, setRep] = useState('')
  const [scopes, setScopes] = useState<SearchScope[]>(['chapters'])
  const [regex, setRegex] = useState(false)
  const [res, setRes] = useState<SearchResult | null>(null)
  const [skip, setSkip] = useState<Set<string>>(new Set())
  const find = useMutation({
    mutationFn: () => v013Api.search(bookId, q, scopes, regex),
    meta: { errorTitle: '查找失败' },
    onSuccess: (r) => { setRes(r); setSkip(new Set()) },
  })
  const doRep = useMutation({
    mutationFn: () => v013Api.replace(bookId, { q, replacement: rep, scopes, regex, case: true, expect: res?.total, skip: [...skip] }),
    meta: { errorTitle: '替换失败' },
    onSuccess: (r) => {
      toast.success(`替换了 ${r.replaced} 处`, { description: r.skipped_locked.length ? `${r.skipped_locked.length} 处在锁定的条目里，没动` : '章节旧稿进了历史，可撤回' })
      setRes(null)
      qc.invalidateQueries({ queryKey: qk.chapters(bookId) }); qc.invalidateQueries({ queryKey: qk.cards(bookId) })
      qc.invalidateQueries({ queryKey: ['chapter'] }); qc.invalidateQueries({ queryKey: ['notes', bookId] }); qc.invalidateQueries({ queryKey: qk.outline(bookId) })
    },
  })
  const toggleScope = (sc: SearchScope) => setScopes((s) => (s.includes(sc) ? (s.length > 1 ? s.filter((x) => x !== sc) : s) : [...s, sc]))
  const n = (res?.total ?? 0) - skip.size
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="查找替换" width={640}
      footer={<>
        <Button onClick={() => find.mutate()} loading={find.isPending} disabled={!q} icon={<Search className="h-4 w-4" />}>查找</Button>
        <Button variant="primary" disabled={!res || n <= 0} loading={doRep.isPending} onClick={() => doRep.mutate()}>替换 {res ? n : ''} 处</Button>
      </>}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="查找"><Input value={q} onChange={(e) => { setQ(e.target.value); setRes(null) }} onKeyDown={(e) => e.key === 'Enter' && q && find.mutate()} className="h-10" /></Field>
          <Field label="替换为"><Input value={rep} onChange={(e) => setRep(e.target.value)} className="h-10" placeholder={regex ? '可用 \\1 引用分组' : ''} /></Field>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {SCOPES.map((sc) => (
            <button key={sc.value} type="button" onClick={() => { toggleScope(sc.value); setRes(null) }}
              className={cn('h-9 rounded-full border px-3 text-[13px] transition', scopes.includes(sc.value) ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>
              {sc.label}{res?.by_scope[sc.value] ? <span className="num ml-1">{res.by_scope[sc.value]}</span> : null}
            </button>
          ))}
          <label className="ml-auto flex h-9 cursor-pointer items-center gap-2 text-[13px]">正则<Switch checked={regex} onCheckedChange={(v) => { setRegex(v); setRes(null) }} /></label>
        </div>
        {res && (
          <div className="space-y-1.5">
            <div className="text-[12.5px] text-muted-foreground">共 {res.total} 处{res.truncated ? `，只列出前 ${res.hits.length} 处` : ''}</div>
            <div className="max-h-[55vh] divide-y overflow-auto rounded-xl hairline">
              {res.hits.map((h) => {
                const k = hitKey(h); const off = skip.has(k)
                return (
                  <label key={k} className={cn('flex cursor-pointer items-start gap-2.5 px-3 py-2', (off || h.locked) && 'opacity-50')}>
                    <input type="checkbox" checked={!off && !h.locked} disabled={h.locked} className="mt-1 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]"
                      onChange={() => setSkip((s) => { const x = new Set(s); x.has(k) ? x.delete(k) : x.add(k); return x })} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[11.5px] text-muted-foreground">{h.label}{h.locked && ' · 已锁定'}</span>
                      <span className="block break-all text-[13px]">…{h.before}<mark className="rounded bg-primary-soft px-0.5 text-primary">{h.match}</mark>{rep && !off && !h.locked && <mark className="ml-0.5 rounded bg-success-soft px-0.5 text-success">{regex ? '→' : rep}</mark>}{h.after}…</span>
                    </span>
                  </label>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </Sheet>
  )
}

function ContextSheet({ open, onClose, bookId, chapterId }: { open: boolean; onClose: () => void; bookId: number; chapterId: number }) {
  const qc = useQueryClient()
  const key = ['context-preview', bookId, chapterId]
  const q = useQuery({ queryKey: key, queryFn: () => v013Api.contextPreview(bookId, chapterId), enabled: open })
  const m = useMutation({
    mutationFn: (blocks: string[]) => v013Api.setContextExclude(bookId, blocks),
    meta: { errorTitle: '保存失败' },
    onSuccess: () => qc.invalidateQueries({ queryKey: key }),
  })
  const d: ContextPreview | undefined = q.data
  const max = Math.max(1, ...(d?.blocks.map((b) => b.chars) ?? [1]))
  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()} title="上下文构成" width={520}>
      {!d ? <Skeleton className="h-64 rounded-xl" /> : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2"><Badge tone="outline">固定资料 {fmtNum(d.fixed_chars)} 字</Badge><Badge tone="primary">合计 {fmtNum(d.total_chars)} 字</Badge></div>
          <div className="divide-y rounded-xl hairline">
            {d.blocks.map((b) => (
              <div key={b.label} className={cn('flex min-h-[48px] items-center gap-3 px-3.5 py-2', b.excluded && 'opacity-50')}>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13.5px] font-medium">{b.label}</div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary/60" style={{ width: `${(b.chars / max) * 100}%` }} /></div>
                </div>
                <span className="num w-14 shrink-0 text-right text-[12.5px] text-muted-foreground">{fmtNum(b.chars)}</span>
                {!b.pinned && <Switch checked={!b.excluded} onCheckedChange={(v) => m.mutate(v ? d.exclude.filter((x) => x !== b.label) : [...d.exclude, b.label])} />}
              </div>
            ))}
          </div>
        </div>
      )}
    </Sheet>
  )
}

