import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowRight, CircleDot, Flag, Info, Lightbulb, ListTree, PenLine, Plus, Search, Sparkles, Sprout, Trash, Trash2 } from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardBody } from '@/components/ui/card'
import { Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { AskBox, useModelRoute } from '@/components/common/AiAsk'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Foreshadow, ForeshadowOverview, ForeshadowPlanItem, ForeshadowStatus, ForeshadowTier } from '@/lib/types'
import { cn } from '@/lib/utils'

const COLS: { key: ForeshadowStatus; label: string; desc: string; icon: typeof Sprout; accent: string; bg: string }[] = [
  { key: 'planned', label: '计划中', desc: '规划好了，还没写进正文', icon: Lightbulb, accent: 'text-sky-500', bg: 'bg-sky-500' },
  { key: 'planted', label: '埋设', desc: '已经埋下，等待推进', icon: Sprout, accent: 'text-primary', bg: 'bg-primary' },
  { key: 'advancing', label: '推进', desc: '被再次提及，逐步升温', icon: ArrowRight, accent: 'text-warning', bg: 'bg-warning' },
  { key: 'resolved', label: '回收', desc: '已在正文中揭晓', icon: Flag, accent: 'text-success', bg: 'bg-success' },
  { key: 'dropped', label: '放弃', desc: '不再使用的线索', icon: Trash, accent: 'text-muted-foreground', bg: 'bg-muted-foreground' },
]
const TIERS: { value: ForeshadowTier; label: string }[] = [
  { value: 'short', label: '短线（10 章内收）' }, { value: 'mid', label: '中线（30 章内收）' }, { value: 'long', label: '长线（50 章以上）' },
]
const TIER_SHORT: Record<string, string> = { short: '短线', mid: '中线', long: '长线' }
const SOURCE_LABEL: Record<string, string> = { ai: 'AI 规划', manual: '手动', outline: '按细纲登记', chapter: '' }

export default function Foreshadows() {
  const id = useBookId()
  const q = useQuery({ queryKey: qk.foreshadows(id), queryFn: () => api.foreshadows(id) })
  const ov = useQuery({ queryKey: qk.foreshadowOverview(id), queryFn: () => api.foreshadowOverview(id) })
  const chs = useQuery({ queryKey: qk.chapters(id), queryFn: () => api.chapters(id) })
  const [kw, setKw] = useState('')
  const [editing, setEditing] = useState<Partial<Foreshadow> | null>(null)
  const [planOpen, setPlanOpen] = useState(false)
  const list = useMemo(() => (q.data ?? []).filter((f) => !kw || f.desc.includes(kw)), [q.data, kw])
  const latestCh = Math.max(0, ...(chs.data ?? []).filter((c) => c.status === 'committed').map((c) => c.number))
  const chId = (n: number) => chs.data?.find((c) => c.number === n)?.id
  const newOne = () => setEditing({ desc: '', status: 'planned', tier: '' })

  return (
    <div className="page max-w-[1400px]">
      <BookCrumb bookId={id} page="伏笔" />
      <PageHeader className="mt-3" title="伏笔"
        actions={<>
          <div className="relative w-48"><Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜索伏笔" className="pl-8" /></div>
          <Button icon={<Plus className="h-4 w-4" />} onClick={newOne}>手动新增</Button>
          <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={() => setPlanOpen(true)}>AI 规划伏笔</Button>
        </>} />
      {q.isLoading ? <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">{COLS.map((c) => <Skeleton key={c.key} className="h-80 rounded-xl" />)}</div>
        : q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : !q.data?.length ? <Guide bookId={id} ov={ov.data} onPlan={() => setPlanOpen(true)} onNew={newOne} />
        : (
          <>
            <OutlinePlanned bookId={id} ov={ov.data} />
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
              {COLS.map((col) => {
                const items = list.filter((f) => f.status === col.key)
                return (
                  <div key={col.key} className="flex flex-col rounded-xl bg-subtle/70 p-2.5 hairline">
                    <div className="flex items-center justify-between px-1.5 pb-2.5 pt-1" title={col.desc}>
                      <div className="flex items-center gap-2"><span className={cn('h-2 w-2 rounded-full', col.bg)} /><span className="text-[14px] font-semibold">{col.label}</span><span className="num rounded-full bg-surface px-1.5 text-xs text-muted-foreground hairline">{items.length}</span></div>
                      <col.icon className={cn('h-4 w-4', col.accent)} />
                    </div>
                    <div className="flex-1 space-y-2">
                      {items.map((f, i) => {
                        const stale = (f.status === 'planted' || f.status === 'advancing') && latestCh - f.last_ch >= 20
                        return (
                          <motion.div key={f.id} role="button" tabIndex={0} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.03 }} onClick={() => setEditing(f)} onKeyDown={(e) => { if (e.key === 'Enter') setEditing(f) }}
                            className={cn('block w-full cursor-pointer rounded-lg bg-surface p-3 text-left shadow-card hairline transition hover:shadow-lift', f.status === 'dropped' && 'opacity-60', stale && 'ring-1 ring-danger/40')}>
                            <p className={cn('text-[13.5px] leading-relaxed', f.status === 'dropped' && 'line-through')}>{f.desc}</p>
                            <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[11.5px]">
                              {f.tier && <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">{TIER_SHORT[f.tier]}</span>}
                              {f.status === 'planned' ? <>
                                {f.plan_plant_ch ? <ChTag n={f.plan_plant_ch} label="计划埋" /> : <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">埋的章未定</span>}
                                {f.plan_resolve_ch && <ChTag n={f.plan_resolve_ch} label="计划收" />}
                              </> : <>
                                <ChTag n={f.planted_ch} label="埋" to={chId(f.planted_ch) ? `/books/${id}/chapters/${chId(f.planted_ch)}` : undefined} />
                                {f.last_ch !== f.planted_ch && <ChTag n={f.last_ch} label="最近" to={chId(f.last_ch) ? `/books/${id}/chapters/${chId(f.last_ch)}` : undefined} />}
                                {f.resolved_ch && <ChTag n={f.resolved_ch} label="收" tone="success" to={chId(f.resolved_ch) ? `/books/${id}/chapters/${chId(f.resolved_ch)}` : undefined} />}
                                {!f.resolved_ch && f.plan_resolve_ch && <ChTag n={f.plan_resolve_ch} label="计划收" />}
                              </>}
                              {f.source && SOURCE_LABEL[f.source] && <span className={cn('rounded px-1.5 py-0.5', f.source === 'outline' ? 'bg-warning-soft text-warning' : 'bg-muted text-muted-foreground')}>{SOURCE_LABEL[f.source]}</span>}
                              {stale && <span className="rounded bg-danger-soft px-1.5 py-0.5 text-danger">{latestCh - f.last_ch} 章未推进</span>}
                            </div>
                          </motion.div>
                        )
                      })}
                      {!items.length && <div className="flex h-20 items-center justify-center rounded-lg border border-dashed text-xs text-muted-foreground/70"><CircleDot className="mr-1 h-3.5 w-3.5" />暂无</div>}
                    </div>
                  </div>
                )
              })}
            </div>
          </>
        )}
      <ForeshadowEditor bookId={id} item={editing} onClose={() => setEditing(null)} latest={latestCh} />
      <PlanSheet bookId={id} open={planOpen} onOpenChange={setPlanOpen} />
    </div>
  )
}

/** 空状态：讲清楚伏笔从哪来、下一步做什么 */
function Guide({ bookId, ov, onPlan, onNew }: { bookId: number; ov?: ForeshadowOverview; onPlan: () => void; onNew: () => void }) {
  const planned = ov?.outline_planned ?? []
  return (
    <div className="space-y-4">
      <EmptyState kind="foreshadow" title="还没有伏笔"
        desc="伏笔有两个来源：写章节时，大纲细纲里安排的伏笔会在章节「提交」入账时自动登记到这里；也可以现在就让 AI 从大纲和设定规划，或者手动添加，先放进「计划中」，写到对应章节时自动转成「已埋」。"
        action={<>
          <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={onPlan}>AI 规划伏笔</Button>
          <Button icon={<Plus className="h-4 w-4" />} onClick={onNew}>手动新增</Button>
        </>} />
      {ov && (
        <Card><CardBody className="space-y-2 text-[13px] leading-relaxed">
          <div className="flex items-center gap-1.5 font-semibold"><Info className="h-4 w-4 text-primary" />这本书现在的情况</div>
          {!ov.outline_nodes ? (
            <p className="text-muted-foreground">还没有大纲。先 <Link to={`/books/${bookId}/outline`} className="font-medium text-primary hover:underline">生成大纲</Link>，细纲里会安排伏笔；或者直接手动添加。</p>
          ) : (
            <p className="text-muted-foreground">
              已提交 <b className="text-foreground">{ov.committed}</b> 章{ov.drafts ? `，还有 ${ov.drafts} 章草稿没提交` : ''}。
              {planned.length ? <>大纲细纲里已经安排了 <b className="text-foreground">{planned.length}</b> 条伏笔（最早在第 {planned[0].chapter} 章），写到并「提交」那一章后就会出现在这里。</> : '大纲细纲里暂时没有安排伏笔，可以让 AI 规划。'}
              {ov.drafts > 0 && ' 草稿要点「提交」才会入账。'}
            </p>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            {ov.outline_nodes > 0 && <Link to={`/books/${bookId}/chapters`}><Button size="sm" icon={<PenLine className="h-3.5 w-3.5" />}>去写正文</Button></Link>}
            <Link to={`/books/${bookId}/outline`}><Button size="sm" variant="ghost" icon={<ListTree className="h-3.5 w-3.5" />}>打开大纲</Button></Link>
          </div>
          {planned.length > 0 && <OutlinePlannedList bookId={bookId} items={planned} />}
        </CardBody></Card>
      )}
    </div>
  )
}

function OutlinePlanned({ bookId, ov }: { bookId: number; ov?: ForeshadowOverview }) {
  const [open, setOpen] = useState(false)
  const items = ov?.outline_planned ?? []
  if (!items.length) return null
  return (
    <div className="mb-4 rounded-xl bg-sky-500/[0.06] px-4 py-3 hairline">
      <button className="flex w-full items-center justify-between gap-2 text-left text-[13px]" onClick={() => setOpen(!open)}>
        <span><b>细纲里还有 {items.length} 条伏笔没入账</b><span className="text-muted-foreground"> · 写到对应章节并提交后自动登记，也可以先加进「计划中」</span></span>
        <span className="text-xs text-primary">{open ? '收起' : '查看'}</span>
      </button>
      {open && <div className="mt-2"><OutlinePlannedList bookId={bookId} items={items} /></div>}
    </div>
  )
}

function OutlinePlannedList({ bookId, items }: { bookId: number; items: ForeshadowOverview['outline_planned'] }) {
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: (its: ForeshadowOverview['outline_planned']) => api.addForeshadows(bookId, {
      attach: false, items: its.map((x) => ({ desc: x.desc, tier: (x.tier || '') as ForeshadowTier, plant_ch: x.chapter, resolve_ch: null, note: `第${x.chapter}章细纲安排`, related: [], source: 'outline' })),
    }),
    meta: { errorTitle: '加入失败' },
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: qk.foreshadows(bookId) }); toast.success(`已加入「计划中」${r.created} 条`) },
  })
  return (
    <div className="space-y-1.5">
      {items.map((x, i) => (
        <div key={i} className="flex items-center gap-2 rounded-md bg-surface px-2.5 py-1.5 text-[12.5px] hairline">
          <span className="num shrink-0 rounded bg-muted px-1.5 text-muted-foreground">第{x.chapter}章</span>
          <span className="min-w-0 flex-1 truncate">{x.desc}</span>
        </div>
      ))}
      <div className="flex justify-end"><Button size="xs" variant="soft" loading={m.isPending} onClick={() => m.mutate(items)}>全部加入「计划中」</Button></div>
    </div>
  )
}

function ForeshadowEditor({ bookId, item, onClose, latest }: { bookId: number; item: Partial<Foreshadow> | null; onClose: () => void; latest: number }) {
  const isNew = !item?.id
  const [f, setF] = useState<Partial<Foreshadow>>({})
  const [last, setLast] = useState<unknown>(null)
  if (item && item !== last) { setLast(item); setF({ ...item }) }
  const qc = useQueryClient()
  const done = (msg: string) => { qc.invalidateQueries({ queryKey: qk.foreshadows(bookId) }); qc.invalidateQueries({ queryKey: qk.book(bookId) }); toast.success(msg); onClose() }
  const body = () => ({
    desc: (f.desc ?? '').trim(), status: f.status, tier: f.tier ?? '', note: f.note ?? '',
    planted_ch: f.planted_ch ?? undefined, resolved_ch: f.resolved_ch ?? null, plan_plant_ch: f.plan_plant_ch ?? null, plan_resolve_ch: f.plan_resolve_ch ?? null,
  })
  const save = useMutation({
    mutationFn: () => (isNew ? api.createForeshadow(bookId, body()) : api.updateForeshadow(item!.id!, body())),
    meta: { errorTitle: '保存失败' },
    onSuccess: () => done(isNew ? '已新增伏笔' : '已保存'),
  })
  const del = useMutation({ mutationFn: () => api.deleteForeshadow(item!.id!), meta: { errorTitle: '删除失败' }, onSuccess: () => done('已删除') })
  const [confirmDel, setConfirmDel] = useState(false)
  const num = (v: string) => (v.trim() === '' ? null : Math.max(0, Number(v) || 0))
  const set = (p: Partial<Foreshadow>) => setF({ ...f, ...p })
  return (
    <Sheet open={!!item} onOpenChange={(o) => { if (!o) { onClose(); setConfirmDel(false) } }} title={isNew ? '新增伏笔' : '编辑伏笔'}
      footer={<>
        {!isNew && (confirmDel ? <Button variant="danger" className="mr-auto" loading={del.isPending} onClick={() => del.mutate()}>确认删除</Button>
          : <Button variant="ghost" className="mr-auto text-danger hover:bg-danger-soft hover:text-danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDel(true)}>删除</Button>)}
        <Button variant="ghost" onClick={onClose}>取消</Button>
        <Button variant="primary" disabled={!(f.desc ?? '').trim()} loading={save.isPending} onClick={() => save.mutate()}>保存</Button>
      </>}>
      <div className="space-y-4">
        <Field label="伏笔内容"><Textarea autoFocus value={f.desc ?? ''} onChange={(e) => set({ desc: e.target.value })} placeholder="例如：账本内页被撕掉的那一页" className="min-h-[72px]" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="状态"><Select value={f.status ?? 'planned'} onChange={(v) => v && set({ status: v as ForeshadowStatus, ...(v === 'resolved' && !f.resolved_ch ? { resolved_ch: latest || f.last_ch || null } : {}) })} options={COLS.map((c) => ({ value: c.key, label: c.label }))} /></Field>
          <Field label="层级"><Select value={f.tier || null} onChange={(v) => set({ tier: (v ?? '') as ForeshadowTier })} options={TIERS} allowEmpty emptyLabel="未定" placeholder="未定" /></Field>
        </div>
        {f.status === 'planned' ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="计划第几章埋"><Input type="number" min={1} value={f.plan_plant_ch ?? ''} onChange={(e) => set({ plan_plant_ch: num(e.target.value) })} placeholder="未定" /></Field>
            <Field label="计划第几章收"><Input type="number" min={1} value={f.plan_resolve_ch ?? ''} onChange={(e) => set({ plan_resolve_ch: num(e.target.value) })} placeholder="未定" /></Field>
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-3">
            <Field label="第几章埋"><Input type="number" min={0} value={f.planted_ch ?? ''} onChange={(e) => set({ planted_ch: num(e.target.value) ?? 0 })} /></Field>
            <Field label="计划第几章收"><Input type="number" min={1} value={f.plan_resolve_ch ?? ''} onChange={(e) => set({ plan_resolve_ch: num(e.target.value) })} placeholder="未定" /></Field>
            <Field label="回收章节"><Input type="number" min={1} value={f.resolved_ch ?? ''} onChange={(e) => { const v = num(e.target.value); set({ resolved_ch: v, ...(v ? { status: 'resolved' } : {}) }) }} placeholder="未回收" /></Field>
          </div>
        )}
        {!isNew && f.status !== 'resolved' && f.status !== 'planned' && (
          <Button size="sm" variant="soft" icon={<Flag className="h-3.5 w-3.5" />} onClick={() => set({ status: 'resolved', resolved_ch: f.resolved_ch || latest || f.last_ch || null })}>标记为已回收{latest ? `（第 ${latest} 章）` : ''}</Button>
        )}
        <Field label="怎么埋、怎么收（备注）"><Textarea value={f.note ?? ''} onChange={(e) => set({ note: e.target.value })} className="min-h-[72px]" placeholder="例如：开篇只写缺页；中途有人高价收购；回收时揭开缺页记的是谁的账" /></Field>
        <p className="text-xs leading-relaxed text-muted-foreground">「计划中」的伏笔写到对应章节、提交入账时会自动转成「已埋」。AI 规划时可以顺手写进那一章的细纲，写正文时就会照着埋。</p>
      </div>
    </Sheet>
  )
}

type PlanRow = ForeshadowPlanItem & { pick: boolean }

function PlanSheet({ bookId, open, onOpenChange }: { bookId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [ask, setAsk] = useState('')
  const [count, setCount] = useState('5')
  const [rows, setRows] = useState<PlanRow[] | null>(null)
  const [attach, setAttach] = useState(true)
  const storage = useModelRoute('novelos.foreshadow-route')
  const { start } = useJobs()
  const job = useActiveJob(`foreshadow-plan:${bookId}`)
  const qc = useQueryClient()
  const go = () => start(api.planForeshadows(bookId, { instruction: ask.trim(), route: storage.model, count: Number(count) }), {
    key: `foreshadow-plan:${bookId}`, label: 'AI 规划伏笔', silent: true,
    onSuccess: (j) => setRows(((j.result?.items ?? []) as ForeshadowPlanItem[]).map((x) => ({ ...x, pick: !x.duplicate_of }))),
  })
  const add = useMutation({
    mutationFn: () => api.addForeshadows(bookId, { attach, items: (rows ?? []).filter((r) => r.pick).map(({ pick: _p, ...r }) => r) }),
    meta: { errorTitle: '加入失败' },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: qk.foreshadows(bookId) }); qc.invalidateQueries({ queryKey: qk.outline(bookId) })
      toast.success(`已加入 ${r.created} 条伏笔`, { description: r.attached ? `写进了 ${r.attached} 处章细纲` : '还没有对应章的细纲，展开大纲后可再编辑' })
      setRows(null); setAsk(''); onOpenChange(false)
    },
  })
  const upd = (i: number, p: Partial<PlanRow>) => setRows((rs) => rs && rs.map((r, j) => (j === i ? { ...r, ...p } : r)))
  return (
    <Sheet open={open} onOpenChange={onOpenChange} width={680} title="AI 规划伏笔" desc="AI 读大纲和设定，给出长短线伏笔；勾选后放进「计划中」，可同时写进对应章细纲。">
      {!rows ? (
        <AskBox title="规划要求（可留空）" storage={storage} value={ask} onChange={setAsk} onSubmit={go} job={job} allowEmpty submitLabel="开始规划"
          placeholder="例如：围绕反派的真实目的埋两条长线；前五章至少埋一条短线；不要和身世有关"
          extra={<div className="flex items-center justify-end gap-2 text-[12.5px] text-muted-foreground">条数<div className="w-[96px]"><Select value={count} onChange={(v) => v && setCount(v)} options={[3, 5, 8, 10].map((n) => ({ value: String(n), label: `${n} 条` }))} /></div></div>} />
      ) : (
        <div className="space-y-3">
          {rows.map((r, i) => (
            <div key={i} className={cn('rounded-xl bg-surface p-3 shadow-card hairline', !r.pick && 'opacity-55')}>
              <div className="flex gap-2.5">
                <input type="checkbox" className="mt-1 h-4 w-4 accent-primary" checked={r.pick} onChange={() => upd(i, { pick: !r.pick })} />
                <div className="min-w-0 flex-1 space-y-2">
                  <Input value={r.desc} onChange={(e) => upd(i, { desc: e.target.value })} className="text-[13px]" />
                  <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                    {r.tier && <span className="rounded bg-muted px-1.5 py-0.5">{TIER_SHORT[r.tier]}</span>}
                    第<Input type="number" min={1} value={r.plant_ch ?? ''} onChange={(e) => upd(i, { plant_ch: e.target.value ? Number(e.target.value) : null })} className="h-7 w-16 px-2 text-xs" />章埋，
                    第<Input type="number" min={1} value={r.resolve_ch ?? ''} onChange={(e) => upd(i, { resolve_ch: e.target.value ? Number(e.target.value) : null })} className="h-7 w-16 px-2 text-xs" />章收
                    {r.duplicate_of && <span className="rounded bg-warning-soft px-1.5 py-0.5 text-warning">和已有伏笔重复</span>}
                    {!r.in_outline && <span className="text-muted-foreground/80">（那一章还没有细纲）</span>}
                  </div>
                  {r.note && <p className="text-[12.5px] leading-relaxed text-muted-foreground">{r.note}</p>}
                </div>
              </div>
            </div>
          ))}
          <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg bg-subtle px-3 py-2.5 text-[13px]">
            <span>同时写进对应章细纲（写正文时按计划埋、收）</span><Switch checked={attach} onCheckedChange={setAttach} />
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRows(null)}>重新规划</Button>
            <Button variant="primary" loading={add.isPending} disabled={!rows.some((r) => r.pick && r.desc.trim())} onClick={() => add.mutate()}>加入 {rows.filter((r) => r.pick).length} 条</Button>
          </div>
        </div>
      )}
    </Sheet>
  )
}

function ChTag({ n, label, to, tone }: { n: number; label: string; to?: string; tone?: 'success' }) {
  const cls = cn('num inline-flex items-center gap-0.5 rounded px-1.5 py-0.5', tone === 'success' ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground', to && 'hover:text-foreground')
  const body = <>{label} 第{n}章</>
  return to ? <Link to={to} className={cls} onClick={(e) => e.stopPropagation()}>{body}</Link> : <span className={cls}>{body}</span>
}
