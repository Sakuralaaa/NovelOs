import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { BookPlus, Globe2, Plus, Search, Sparkles, Trash } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { JobInline } from '@/components/common/JobInline'
import { Chips, Lbl, Pager, sourceLabel } from '@/components/fanfic/bits'
import { fanficApi, fqk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { FanficSource, LibCat, LibEntry } from '@/lib/types'
import { cn, fmtNum } from '@/lib/utils'

export const LIB_CATS: { value: LibCat; label: string }[] = [
  { value: 'world', label: '世界设定' }, { value: 'character', label: '角色档案' }, { value: 'timeline', label: '剧情时间线' }, { value: 'relation', label: '关系索引' },
]
const SUB_HINT: Record<LibCat, string[]> = {
  world: ['力量体系', '世界规则', '关键物品', '组织势力', '地理地点', '制度社会', '历史背景', '其他设定'],
  character: ['主角', '主要配角', '反派', '其他角色'], timeline: ['剧情时间线', '名场面'], relation: ['亲情', '师徒', '伴侣', '宿敌', '同伴', '其他关系'],
}
const SIZE = 36

/** v0.15 原著世界库头部：封面字、书名、标签、简介、统计与操作 */
export function SourceHero({ s, title, setTitle, canSearch, dirty, supRunning, onSupplement, onDelete, deleting }: {
  s: FanficSource; title: string; setTitle: (v: string) => void; canSearch: boolean; dirty: boolean; supRunning: boolean
  onSupplement: () => void; onDelete: () => void; deleting: boolean
}) {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState(false)
  const [intro, setIntro] = useState(s.intro ?? '')
  const [tags, setTags] = useState<string[]>(s.tags ?? [])
  const [books, setBooks] = useState(false)
  useEffect(() => { setIntro(s.intro ?? ''); setTags(s.tags ?? []) }, [s.id, s.intro, s.tags])
  const save = useMutation({
    mutationFn: () => fanficApi.updateSource(s.id, { intro, tags }),
    meta: { errorTitle: '保存失败' },
    onSuccess: (r) => { qc.setQueryData(fqk.source(s.id), r.source); qc.invalidateQueries({ queryKey: fqk.sources }); setEdit(false); toast.success('已保存') },
  })
  const total = Object.values(s.entry_counts ?? {}).reduce((a, b) => a + b, 0)
  const list = s.books ?? []
  return (
    <section className="rounded-2xl border bg-surface p-4 shadow-sm sm:p-5">
      <div className="flex min-w-0 gap-4">
        <div className="hidden h-[112px] w-[112px] shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-[hsl(18_80%_52%)] text-[48px] font-semibold text-primary-foreground shadow-sm sm:flex">
          {(s.title || '原').slice(0, 1)}
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[11.5px] font-medium text-primary">原著世界库</div>
          <Input value={title} onChange={(e) => setTitle(e.target.value.slice(0, 60))} aria-label="原著名"
            className="-ml-1 h-11 border-transparent bg-transparent px-1 text-[24px] font-semibold tracking-tight shadow-none hover:border-input" />
          <div className="num mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px]">
            <span className="rounded-full bg-primary-soft px-2 leading-[22px] text-primary">{sourceLabel(s)}</span>
            <span className="rounded-full bg-muted px-2 leading-[22px] text-muted-foreground">完整度 {s.completeness}</span>
            {!!s.web_rounds && <span className="rounded-full bg-muted px-2 leading-[22px] text-muted-foreground">联网检索 {s.web_rounds} 轮</span>}
            {(s.tags ?? []).map((t) => <span key={t} className="rounded-full bg-[hsl(30_90%_55%/0.12)] px-2 leading-[22px] text-[hsl(25_80%_40%)]">#{t}</span>)}
            <button type="button" onClick={() => setEdit((v) => !v)} className="h-[22px] rounded-full px-2 text-muted-foreground hover:bg-muted hover:text-foreground">{edit ? '收起' : '编辑简介与标签'}</button>
          </div>
          {edit ? (
            <div className="mt-2 space-y-2">
              <Textarea rows={4} value={intro} onChange={(e) => setIntro(e.target.value.slice(0, 600))} placeholder="原著简介：主角、主线、世界观一两段话" />
              <Chips value={tags} onChange={setTags} max={12} placeholder="标签，如：玄幻、热血，回车添加" />
              <div className="flex justify-end gap-1.5"><Button variant="ghost" className="h-9" onClick={() => setEdit(false)}>取消</Button><Button variant="primary" className="h-9" loading={save.isPending} onClick={() => save.mutate()}>保存</Button></div>
            </div>
          ) : (s.intro ? (
            <div className="mt-2">
              <p className={cn('whitespace-pre-wrap text-[13px] leading-relaxed text-foreground/75', !open && 'line-clamp-3')}>{s.intro}</p>
              {s.intro.length > 120 && <button type="button" onClick={() => setOpen(!open)} className="mt-0.5 text-[12px] text-primary hover:underline">{open ? '收起' : '展开全部'}</button>}
            </div>
          ) : <p className="mt-2 text-[12.5px] text-muted-foreground">还没有简介</p>)}
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <Link to={`/fanfic/new?source=${s.id}`}><Button variant="primary" className="h-10" icon={<BookPlus className="h-4 w-4" />}>用它建同人书</Button></Link>
            <Button variant="soft" className="h-10" onClick={() => setBooks(true)}>同原著作品 {list.length}</Button>
            {!supRunning && <Button variant="ghost" className="h-10" icon={<Globe2 className="h-4 w-4" />} disabled={!canSearch || dirty}
              title={!canSearch ? '未配置联网搜索模型' : dirty ? '先保存或还原修改' : ''} onClick={onSupplement}>联网补充</Button>}
            <Button variant="ghost" className="h-10 text-danger hover:bg-danger-soft" loading={deleting} icon={<Trash className="h-4 w-4" />} onClick={onDelete}>删除</Button>
            <div className="num ml-auto flex gap-5 pr-1">
              <Stat n={total} label="设定条目" /><Stat n={s.entry_counts?.character ?? 0} label="角色档案" /><Stat n={list.length} label="在用的书" />
            </div>
          </div>
        </div>
      </div>
      <Dialog open={books} onOpenChange={setBooks}>
        <DialogContent title={`《${s.title}》的同人作品`} desc="这些书共用这一份原著世界库，库里的改动对它们都生效。">
          {list.length ? (
            <ul className="space-y-1">{list.map((b) => (
              <li key={b.id}><Link to={`/books/${b.id}`} className="flex min-h-[44px] items-center gap-2 rounded-lg px-2 hover:bg-muted">
                <span className="min-w-0 flex-1 truncate text-[14px] font-medium">{b.title}</span><span className="num text-[12px] text-muted-foreground">{fmtNum(b.words)} 字</span></Link></li>
            ))}</ul>
          ) : <p className="py-4 text-center text-[13px] text-muted-foreground">还没有书用这份原著。</p>}
        </DialogContent>
      </Dialog>
    </section>
  )
}

const Stat = ({ n, label }: { n: number; label: string }) => (
  <div className="text-center"><div className="text-[20px] font-semibold leading-tight">{fmtNum(n)}</div><div className="text-[11px] text-muted-foreground">{label}</div></div>
)

/** v0.15 世界库：四大类在顶部，子分类一排，搜索 + 翻页 + 卡片网格；点卡片看详情/编辑 */
export function Library({ id }: { id: number }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const [cat, setCat] = useState<LibCat>('world')
  const [sub, setSub] = useState('')
  const [kw, setKw] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(1)
  const [edit, setEdit] = useState<Partial<LibEntry> | null>(null)
  const [expand, setExpand] = useState(false)
  useEffect(() => { const t = setTimeout(() => setQ(kw.trim()), 250); return () => clearTimeout(t) }, [kw])
  useEffect(() => setPage(1), [cat, sub, q])
  const lq = useQuery({ queryKey: [...fqk.source(id), 'entries', cat, sub, q, page], queryFn: () => fanficApi.entries(id, { cat, sub: sub || undefined, q: q || undefined, page, size: SIZE }),
    placeholderData: keepPreviousData })
  const d = lq.data
  const expKey = `fanfic-expand-${id}`
  const running = useActiveJob(expKey)
  const refresh = () => qc.invalidateQueries({ queryKey: fqk.source(id) })
  const runExpand = async (hint: string, count: number) => {
    setExpand(false)
    await start(fanficApi.expandLibrary(id, { cat, sub: sub || undefined, hint: hint || undefined, count }), {
      label: `扩充${LIB_CATS.find((c) => c.value === cat)!.label}${sub ? `·${sub}` : ''}`, key: expKey,
      successMsg: '世界库已扩充', onSuccess: (j) => { refresh(); toast.success(`新增 ${j.result?.added ?? 0} 条`) },
    })
  }
  return (
    <section className="mt-6 min-w-0">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <div className="-mx-3 min-w-0 overflow-x-auto px-3 [scrollbar-width:none] sm:mx-0 sm:px-0">
          <Segmented value={cat} onChange={(v) => { setCat(v); setSub(''); setKw('') }} className="h-10" options={LIB_CATS.map((c) => ({
            value: c.value, label: <span className="inline-flex items-center gap-1 whitespace-nowrap">{c.label}<span className="num text-[11px] opacity-60">{d?.cats[c.value] ?? ''}</span></span>,
          }))} />
        </div>
        <div className="relative ml-auto min-w-[180px] flex-1 sm:max-w-[280px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜条目名、要点、人物" className="h-10 pl-8" aria-label="搜索世界库" />
        </div>
      </div>
      <div className="mt-3 flex min-w-0 flex-wrap items-center gap-1.5">
        <SubChip on={!sub} onClick={() => setSub('')} label="全部" n={d ? d.cats[cat] : undefined} />
        {d?.subs.map((x) => <SubChip key={x.sub} on={sub === x.sub} onClick={() => setSub(x.sub)} label={x.sub} n={x.count} />)}
        <div className="ml-auto flex gap-1.5">
          <Button variant="ghost" className="h-9" icon={<Plus className="h-4 w-4" />} onClick={() => setEdit({ cat, sub: sub || SUB_HINT[cat][0], name: '', summary: '', detail: '', tags: [] })}>添加条目</Button>
          {!running && <Button variant="soft" className="h-9" icon={<Sparkles className="h-4 w-4" />} onClick={() => setExpand(true)}>AI 扩充{sub ? `「${sub}」` : '本类'}</Button>}
        </div>
      </div>
      {running && <div className="mt-3"><JobInline job={running} /></div>}

      <div className="mt-3">
        {lq.isLoading ? (
          <div className="grid gap-2.5 grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))]">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[120px] rounded-xl" />)}</div>
        ) : !d?.items.length ? (
          <p className="rounded-xl border border-dashed px-4 py-10 text-center text-[13px] text-muted-foreground">{q ? '没有匹配的条目' : '这一类还没有条目，点「AI 扩充」或「添加条目」'}</p>
        ) : (
          <>
            <div className="mb-2 flex items-baseline gap-2"><h3 className="text-[14px] font-semibold">{sub || LIB_CATS.find((c) => c.value === cat)!.label}</h3><span className="num text-[12px] text-muted-foreground">共 {d.total} 条</span></div>
            <div className={cn('grid gap-2.5 grid-cols-[repeat(auto-fill,minmax(min(100%,260px),1fr))]', lq.isFetching && 'opacity-70')}>
              {d.items.map((e) => (
                <button key={e.id} type="button" onClick={() => setEdit(e)}
                  className="focus-ring flex min-h-[112px] min-w-0 gap-2.5 rounded-xl border bg-background p-3 text-left transition hover:border-primary/40 hover:shadow-sm">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-soft text-[15px] font-semibold text-primary">{e.name.slice(0, 1)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] font-semibold">{e.name}</span>
                    <span className="block text-[11px] text-muted-foreground">{e.sub}{e.cat === 'timeline' && e.sub !== '名场面' && e.order ? ` · 第 ${e.order} 节点` : ''}</span>
                    <span className="mt-1 line-clamp-3 text-[12.5px] leading-relaxed text-foreground/70">{e.summary || e.detail || '（还没写要点）'}</span>
                  </span>
                </button>
              ))}
            </div>
            <Pager page={d.page} pages={d.pages} onChange={setPage} />
          </>
        )}
      </div>

      <EntryDialog id={id} entry={edit} onClose={() => setEdit(null)} onSaved={refresh} />
      <ExpandDialog open={expand} onClose={() => setExpand(false)} label={`${LIB_CATS.find((c) => c.value === cat)!.label}${sub ? `·${sub}` : ''}`} onRun={runExpand} />
    </section>
  )
}

const SubChip = ({ on, onClick, label, n }: { on: boolean; onClick: () => void; label: string; n?: number }) => (
  <button type="button" aria-pressed={on} onClick={onClick}
    className={cn('focus-ring inline-flex h-9 items-center gap-1 whitespace-nowrap rounded-full px-3 text-[13px] transition', on ? 'bg-foreground text-background' : 'bg-muted/70 text-foreground/75 hover:bg-muted')}>
    {label}{n != null && <span className="num text-[11px] opacity-60">{n}</span>}
  </button>
)

function EntryDialog({ id, entry, onClose, onSaved }: { id: number; entry: Partial<LibEntry> | null; onClose: () => void; onSaved: () => void }) {
  const [e, setE] = useState<Partial<LibEntry>>({})
  useEffect(() => { if (entry) setE(entry) }, [entry])
  const isNew = !entry?.id
  const save = useMutation({
    mutationFn: () => {
      const b = { cat: e.cat, sub: e.sub?.trim(), name: e.name?.trim(), summary: e.summary ?? '', detail: e.detail ?? '', tags: e.tags ?? [], order: e.order ?? 0 }
      return isNew ? fanficApi.addEntry(id, b) : fanficApi.updateEntry(id, entry!.id!, b)
    },
    meta: { errorTitle: '保存失败' },
    onSuccess: () => { onSaved(); onClose(); toast.success('已保存') },
  })
  const del = useMutation({
    mutationFn: () => fanficApi.deleteEntry(id, entry!.id!),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { onSaved(); onClose(); toast.success('已删除') },
  })
  const cat = (e.cat ?? 'world') as LibCat
  return (
    <Dialog open={!!entry} onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title={isNew ? '添加条目' : e.name || '条目'}
        footer={<>
          {!isNew && <Button variant="ghost" className="mr-auto h-10 text-danger hover:bg-danger-soft" loading={del.isPending} icon={<Trash className="h-4 w-4" />} onClick={() => { if (window.confirm(`删除「${e.name}」？`)) del.mutate() }}>删除</Button>}
          <Button className="h-10" onClick={onClose}>取消</Button>
          <Button variant="primary" className="h-10" disabled={!e.name?.trim()} loading={save.isPending} onClick={() => save.mutate()}>保存</Button>
        </>}>
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-[2fr_1fr]">
            <div><Lbl>名字</Lbl><Input className="h-10" value={e.name ?? ''} onChange={(x) => setE({ ...e, name: x.target.value.slice(0, 60) })} placeholder={cat === 'relation' ? '甲 — 乙' : '条目名'} /></div>
            <div><Lbl>子分类</Lbl><Input className="h-10" list={`subs-${cat}`} value={e.sub ?? ''} onChange={(x) => setE({ ...e, sub: x.target.value.slice(0, 20) })} />
              <datalist id={`subs-${cat}`}>{SUB_HINT[cat].map((x) => <option key={x} value={x} />)}</datalist></div>
          </div>
          <div><Lbl hint={`${(e.summary ?? '').length}/200`}>要点</Lbl><Textarea rows={2} value={e.summary ?? ''} onChange={(x) => setE({ ...e, summary: x.target.value.slice(0, 200) })} placeholder="一句话说清楚" /></div>
          <div><Lbl hint={`${(e.detail ?? '').length}/2000`}>详细说明</Lbl><Textarea rows={7} value={e.detail ?? ''} onChange={(x) => setE({ ...e, detail: x.target.value.slice(0, 2000) })} placeholder="来历、规则、限制、相关人物……" /></div>
          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
            <div><Lbl>相关人物 / 关键词</Lbl><Chips value={e.tags ?? []} onChange={(v) => setE({ ...e, tags: v })} max={8} /></div>
            {cat === 'timeline' && <div><Lbl>顺序</Lbl><Input type="number" className="num h-10 w-24" value={e.order ?? 0} onChange={(x) => setE({ ...e, order: Number(x.target.value) || 0 })} /></div>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ExpandDialog({ open, onClose, label, onRun }: { open: boolean; onClose: () => void; label: string; onRun: (hint: string, count: number) => void }) {
  const [hint, setHint] = useState('')
  const [count, setCount] = useState('20')
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent title={`AI 扩充「${label}」`} desc="有联网搜索时先检索再整理；已有的同名条目不会重复，也不会覆盖你改过的内容。"
        footer={<><Button className="h-10" onClick={onClose}>取消</Button><Button variant="primary" className="h-10" icon={<Sparkles className="h-4 w-4" />} onClick={() => onRun(hint.trim(), Number(count))}>开始扩充</Button></>}>
        <div className="space-y-3">
          <div><Lbl>想重点补什么（可不填）</Lbl><Input className="h-10" value={hint} onChange={(e) => setHint(e.target.value.slice(0, 200))} placeholder="如：唐门暗器、海神九考、七怪的武魂" /></div>
          <div><Lbl>补多少条</Lbl><Segmented block value={count} onChange={setCount} options={['10', '20', '40'].map((n) => ({ value: n, label: `${n} 条` }))} /></div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
