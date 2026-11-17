import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowRight, ArrowUpRight, Check, Eye, RefreshCw, StopSquare, Undo2, X } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { JobInline } from '@/components/common/JobInline'
import { ModelSelect, useModelRoute } from '@/components/common/AiAsk'
import { useKindJob } from '@/hooks/useKindJob'
import { api, qk, wanbenApi, wqk } from '@/lib/api'
import { useJobs } from '@/lib/jobs'
import { diffParas, type DiffRow } from '@/lib/textAnalysis'
import type { IterMethod, WanbenIteration } from '@/lib/types'
import { cn, fmtNum, fmtTime } from '@/lib/utils'
import { Delta, parseRanges } from './bits'

const METHODS: { value: IterMethod; label: string }[] = [{ value: 'auto', label: '自动' }, { value: 'patch', label: '定点修' }, { value: 'rewrite', label: '整章重写' }]
const METHOD_LABEL: Record<string, string> = { patch: '定点修', rewrite: '整章重写', auto: '自动', humanize: '去 AI 味', polish: '语感重塑', format: '排版' }
const ITER_METHODS = ['patch', 'rewrite']
const IT_STATUS: Record<string, { label: string; tone: 'primary' | 'success' | 'neutral' }> = {
  pending: { label: '待采纳', tone: 'primary' }, adopted: { label: '已采纳', tone: 'success' }, discarded: { label: '已弃用', tone: 'neutral' },
}
const KEY = (id: number) => `wanben-iterate:${id}`

/** 章节迭代：选章号范围 + 要求 + 方式 + 轮数；版本列表看每轮分数变化，对比后采纳/弃用（采纳后可撤回） */
export function IterateCard({ bookId, maxChapter, className }: { bookId: number; maxChapter: number; className?: string }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const storage = useModelRoute('novelos.wanben-iterate-route')
  const [range, setRange] = useState('1-3')
  const [ins, setIns] = useState('')
  const [method, setMethod] = useState<IterMethod>('auto')
  const [rounds, setRounds] = useState(1)
  const [view, setView] = useState<'pending' | 'all'>('pending')
  const [openId, setOpenId] = useState<number | null>(null)
  const [adopted, setAdopted] = useState<Record<number, number>>({}) // iteration id → chapter id（本次会话采纳的，可撤回）
  const { active } = useKindJob(bookId, 'wanben_iterate', KEY(bookId), '章节迭代')
  const list = useQuery({ queryKey: wqk.iterations(bookId), queryFn: () => wanbenApi.iterations(bookId), refetchInterval: active ? 3000 : false })
  const ranges = parseRanges(range)
  const nChapters = ranges.reduce((n, [a, b]) => n + (b - a + 1), 0)

  const refresh = () => { qc.invalidateQueries({ queryKey: wqk.iterations(bookId) }); qc.invalidateQueries({ queryKey: wqk.refine(bookId) }) }
  const run = () => start(wanbenApi.iterate(bookId, { ranges, instruction: ins.trim(), method, rounds, route: storage.model }), {
    key: KEY(bookId), label: '章节迭代',
    successMsg: (j) => `迭代完成：${(j.result?.iterations as unknown[] | undefined)?.length ?? 0} 个新版本${j.result?.stopped ? '（已按要求提前停止）' : ''}`,
    onSuccess: () => { refresh(); setView('pending') },
  }).then(refresh)
  const stop = useMutation({ mutationFn: () => wanbenApi.stopIterate(bookId), meta: { errorTitle: '停止失败' }, onSuccess: (r) => toast.success('已请求停止', { description: r.message }) })

  const mine = (list.data ?? []).filter((x) => ITER_METHODS.includes(x.method))
  const rows = mine.filter((x) => view === 'all' || x.status === 'pending' || adopted[x.id] != null)
  const groups = useMemo(() => {
    const m = new Map<number, WanbenIteration[]>()
    for (const it of rows) m.set(it.number, [...(m.get(it.number) ?? []), it])
    return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([n, its]) => [n, [...its].sort((a, b) => b.round - a.round)] as const)
  }, [rows])
  const pendingN = mine.filter((x) => x.status === 'pending').length

  return (
    <Card className={className}>
      <CardHeader icon={<RefreshCw />} title="章节迭代" desc="每轮按审稿与读者问题修改，只出新版本，不改正文" />
      <CardBody className="space-y-4 p-4 sm:p-5">
        <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label="章号范围" hint={nChapters ? `${nChapters} 章` : '如 1-3, 8'}>
            <Input value={range} onChange={(e) => setRange(e.target.value)} placeholder={`1-${Math.max(1, Math.min(3, maxChapter))}`} className="h-10 num" />
          </Field>
          <Field label="轮数" hint="可多轮反复">
            <Segmented value={String(rounds)} onChange={(v) => setRounds(Number(v))} className="h-10" options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} />
          </Field>
        </div>
        <Field label="要求（可选）" hint="不写就按审稿与读者问题改">
          <Textarea value={ins} onChange={(e) => setIns(e.target.value)} maxLength={2000} placeholder="例如：开头再狠一点，第一句就让冲突落地；结尾停在揭露身份的前一刻" className="min-h-[72px]" />
        </Field>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="方式" className="min-w-0">
            <Segmented value={method} onChange={setMethod} options={METHODS} className="h-10" />
          </Field>
          <Field label="模型" className="min-w-0"><ModelSelect storage={storage} emptyLabel="默认（写作模型）" className="w-[190px]" /></Field>
          <div className="ml-auto flex gap-2">
            {active && <Button icon={<StopSquare className="h-4 w-4" />} loading={stop.isPending} onClick={() => stop.mutate()}>停止</Button>}
            <Button variant="primary" className="h-10" loading={!!active} disabled={!nChapters} onClick={() => void run()}>发起迭代</Button>
          </div>
        </div>
        <p className="text-[12px] leading-relaxed text-muted-foreground">「自动」：有作者要求、严重问题 ≥ 3 条或读者分不达标时整章重写，否则定点修。没有自动终止门槛，分数变化只做参考，满意了再采纳。</p>
        {active && <JobInline job={active} />}

        <div className="border-t pt-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[13.5px] font-semibold">迭代版本</div>
            <Segmented size="sm" value={view} onChange={setView} options={[{ value: 'pending', label: `待采纳 ${pendingN}` }, { value: 'all', label: '全部' }]} />
          </div>
          {list.isLoading ? <Skeleton className="h-24 rounded-xl" /> : !groups.length ? (
            <p className="rounded-xl border border-dashed px-4 py-6 text-center text-[12.5px] text-muted-foreground">{view === 'pending' ? '没有待采纳的版本' : '还没有迭代过'}</p>
          ) : (
            <div className="space-y-3">
              {groups.map(([n, its]) => (
                <div key={n} className="overflow-hidden rounded-xl hairline">
                  <div className="flex items-center justify-between gap-2 border-b bg-subtle/70 px-3.5 py-2">
                    <span className="text-[13px] font-semibold">第 {n} 章</span>
                    <Link to={`/books/${bookId}/chapters/${its[0].chapter_id}`} className="inline-flex h-8 items-center gap-1 text-[12.5px] text-primary hover:underline">打开章节<ArrowUpRight className="h-3.5 w-3.5" /></Link>
                  </div>
                  <div className="divide-y">
                    {its.map((it) => <IterRow key={it.id} it={it} onOpen={() => setOpenId(it.id)} canUndo={adopted[it.id] != null} bookId={bookId}
                      onAdopted={(cid) => setAdopted((m) => ({ ...m, [it.id]: cid }))} onUndone={() => setAdopted((m) => { const x = { ...m }; delete x[it.id]; return x })} />)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </CardBody>
      <CompareSheet bookId={bookId} id={openId} onClose={() => setOpenId(null)} onAdopted={(id, cid) => setAdopted((m) => ({ ...m, [id]: cid }))} />
    </Card>
  )
}

function useIterActions(bookId: number, onAdopted?: (iterId: number, chapterId: number) => void) {
  const qc = useQueryClient()
  const refresh = () => { qc.invalidateQueries({ queryKey: ['wanben', bookId] }); qc.invalidateQueries({ queryKey: qk.chapters(bookId) }) }
  const adopt = useMutation({
    mutationFn: (id: number) => wanbenApi.adoptIteration(bookId, id),
    meta: { errorTitle: '采纳失败' },
    onSuccess: (r, id) => {
      refresh(); qc.invalidateQueries({ queryKey: qk.chapter(r.chapter_id) })
      onAdopted?.(id, r.chapter_id)
      toast.success(`已采纳第 ${r.iteration.number} 章第 ${r.iteration.round} 轮`, { description: '旧正文已进章节历史，可随时撤回' })
    },
  })
  const discard = useMutation({
    mutationFn: (id: number) => wanbenApi.discardIteration(bookId, id),
    meta: { errorTitle: '弃用失败' },
    onSuccess: () => { refresh(); toast.success('已弃用这个版本') },
  })
  const undo = useMutation({
    mutationFn: (chapterId: number) => api.undoChapter(chapterId),
    meta: { errorTitle: '撤回失败' },
    onSuccess: (c) => { refresh(); qc.setQueryData(qk.chapter(c.id), c); toast.success(`第 ${c.number} 章已恢复到采纳前的正文`) },
  })
  return { adopt, discard, undo }
}

const pct = (v: number | null | undefined) => (v == null ? null : Math.round(v * 100))

function ScorePair({ label, before, after, delta }: { label: string; before: number | null | undefined; after: number | null | undefined; delta: number | null | undefined }) {
  return (
    <span className="num inline-flex items-center gap-1 whitespace-nowrap text-[12px]">
      <span className="text-muted-foreground">{label}</span>
      <span>{before ?? '—'}</span><ArrowRight className="h-3 w-3 text-muted-foreground" /><span className="font-semibold">{after ?? '—'}</span>
      <Delta v={delta} className="ml-0.5" />
    </span>
  )
}

function IterRow({ it, bookId, onOpen, canUndo, onAdopted, onUndone }: {
  it: WanbenIteration; bookId: number; onOpen: () => void; canUndo: boolean; onAdopted: (cid: number) => void; onUndone: () => void
}) {
  const { adopt, discard, undo } = useIterActions(bookId, (_i, cid) => onAdopted(cid))
  const st = IT_STATUS[it.status] ?? IT_STATUS.pending
  const sc = it.scores
  return (
    <div className={cn('flex flex-wrap items-center gap-x-3 gap-y-2 bg-surface px-3.5 py-2.5', it.status === 'discarded' && 'opacity-60')}>
      <div className="min-w-0 flex-1 basis-[220px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[13px] font-medium">第 {it.round} 轮</span>
          <Badge tone="outline">{METHOD_LABEL[it.method] ?? it.method}</Badge>
          <Badge tone={st.tone}>{st.label}</Badge>
          {it.stale && it.status === 'pending' && <Badge tone="warning" title="这一版的底稿不是当前正文（基于上一轮版本，或生成后正文又改过）；采纳会覆盖当前正文，旧正文进历史可撤回"><AlertTriangle className="h-3 w-3" />底稿非当前正文</Badge>}
        </div>
        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
          {ITER_METHODS.includes(it.method) ? <>
            <ScorePair label="审稿" before={sc?.before.overall} after={sc?.after.overall} delta={sc?.delta.overall} />
            <ScorePair label="读者" before={sc?.before.reader} after={sc?.after.reader} delta={sc?.delta.reader} />
          </> : <>
            {sc?.before.ai != null && <ScorePair label="AI 味" before={sc.before.ai} after={sc.after.ai} delta={sc.delta.ai != null ? -sc.delta.ai : null} />}
            {sc?.before.aigc != null && <ScorePair label="AI 率" before={pct(sc.before.aigc)} after={pct(sc.after.aigc)} delta={sc.delta.aigc != null ? -Math.round(sc.delta.aigc * 100) : null} />}
          </>}
          <span className="num text-[12px] text-muted-foreground">{fmtNum(it.words)} 字 · {fmtTime(it.created_at)}</span>
        </div>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        <Button size="sm" variant="ghost" icon={<Eye className="h-3.5 w-3.5" />} onClick={onOpen}>对比</Button>
        {it.status === 'pending' && <>
          <Button size="sm" variant="ghost" loading={discard.isPending} onClick={() => discard.mutate(it.id)}>弃用</Button>
          <Button size="sm" variant="soft" icon={<Check className="h-3.5 w-3.5" />} loading={adopt.isPending} onClick={() => adopt.mutate(it.id)}>采纳</Button>
        </>}
        {it.status === 'adopted' && (canUndo ? (
          <Button size="sm" variant="ghost" icon={<Undo2 className="h-3.5 w-3.5" />} loading={undo.isPending} onClick={() => undo.mutate(it.chapter_id, { onSuccess: onUndone })}>撤回</Button>
        ) : <span className="text-[12px] text-muted-foreground">可在章节页撤回</span>)}
      </div>
    </div>
  )
}

function CompareSheet({ bookId, id, onClose, onAdopted }: { bookId: number; id: number | null; onClose: () => void; onAdopted: (id: number, cid: number) => void }) {
  const q = useQuery({ queryKey: wqk.iteration(bookId, id ?? 0), queryFn: () => wanbenApi.iteration(bookId, id!), enabled: !!id })
  const it = q.data
  const [mode, setMode] = useState<'diff' | 'new' | 'old'>('diff')
  const rows = useMemo(() => (it?.content != null && it.base_content != null ? diffParas(it.base_content, it.content) : []), [it?.content, it?.base_content])
  const changed = rows.filter((r) => r.type !== 'same').length
  const { adopt, discard } = useIterActions(bookId, onAdopted)
  const issues = (it?.review?.issues ?? []).filter((x) => x.severity === 'high' || x.severity === 'mid')
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()} width={960}
      title={it ? `第 ${it.number} 章 · 第 ${it.round} 轮（${METHOD_LABEL[it.method] ?? it.method}）` : '版本对比'}
      desc={it?.scores ? `审稿 ${it.scores.before.overall ?? '—'} → ${it.scores.after.overall ?? '—'} · 读者 ${it.scores.before.reader ?? '—'} → ${it.scores.after.reader ?? '—'}` : undefined}
      footer={it?.status === 'pending' ? <>
        <Button variant="ghost" icon={<X className="h-4 w-4" />} loading={discard.isPending} onClick={() => discard.mutate(it.id, { onSuccess: onClose })}>弃用</Button>
        <Button variant="primary" icon={<Check className="h-4 w-4" />} loading={adopt.isPending} onClick={() => adopt.mutate(it.id, { onSuccess: onClose })}>采纳这一版</Button>
      </> : <Button onClick={onClose}>关闭</Button>}>
      {q.isLoading || !it ? <div className="space-y-3"><Skeleton className="h-16 rounded-xl" /><Skeleton className="h-64 rounded-xl" /></div> : (
        <div className="space-y-4">
          {it.stale && <p className="flex gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />这一版的底稿不是当前正文（基于上一轮版本，或生成后正文又改过）：下面对比的是底稿与新版，采纳会覆盖当前正文（旧正文进历史，可撤回）。</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={mode} onChange={setMode} options={[{ value: 'diff', label: `逐段对比 ${changed}` }, { value: 'new', label: '新版全文' }, { value: 'old', label: '底稿全文' }]} />
            <span className="num ml-auto text-[12px] text-muted-foreground">{fmtNum(it.words)} 字</span>
          </div>
          {it.instruction && <details className="rounded-lg bg-subtle px-3 py-2 text-[12.5px]"><summary className="cursor-pointer select-none py-1 font-medium">这一轮的修改要求</summary><p className="mt-1 whitespace-pre-wrap break-words leading-relaxed text-foreground/80">{it.instruction}</p></details>}
          {issues.length > 0 && (
            <details className="rounded-lg bg-subtle px-3 py-2 text-[12.5px]">
              <summary className="cursor-pointer select-none py-1 font-medium">新版仍有 {issues.length} 条中等以上问题</summary>
              <ul className="mt-1 space-y-1">{issues.map((x, i) => <li key={i} className="break-words leading-relaxed"><span className={x.severity === 'high' ? 'text-danger' : 'text-warning'}>●</span> {x.comment}</li>)}</ul>
            </details>
          )}
          {mode === 'diff' ? (
            changed === 0 ? <p className="py-12 text-center text-sm text-muted-foreground">这一轮没有改动段落</p> : (
              <div className="space-y-2">{rows.map((r, i) => <DiffLine key={i} r={r} />)}</div>
            )
          ) : (
            <div className="prose-zh rounded-xl bg-surface px-4 py-4 font-serif text-[15px] hairline sm:px-6">
              {(mode === 'new' ? it.content : it.base_content)?.split('\n').filter((p) => p.trim()).map((p, i) => <p key={i}>{p}</p>)}
            </div>
          )}
        </div>
      )}
    </Sheet>
  )
}

function DiffLine({ r }: { r: DiffRow }) {
  if (r.type === 'same') return <p className="prose-zh px-3 font-serif text-[14.5px] text-foreground/45">{r.text}</p>
  const before = r.type === 'changed' || r.type === 'removed' ? r.before : null
  const after = r.type === 'changed' || r.type === 'added' ? r.after : null
  return (
    <div className="grid gap-2 rounded-xl bg-surface p-2.5 shadow-card hairline md:grid-cols-2">
      <div className="rounded-lg bg-danger-soft/60 px-3 py-2">
        <div className="mb-1 text-[11px] font-medium text-muted-foreground">底稿</div>
        <p className="prose-zh break-words font-serif text-[14px] text-foreground/60 line-through decoration-danger/40">{before ?? <span className="text-muted-foreground no-underline">（无）</span>}</p>
      </div>
      <div className="rounded-lg bg-success-soft/70 px-3 py-2 ring-1 ring-success/30">
        <div className="mb-1 text-[11px] font-medium text-muted-foreground">新版</div>
        <p className="prose-zh break-words font-serif text-[14px]">{after ?? <span className="text-muted-foreground">（删除此段）</span>}</p>
      </div>
    </div>
  )
}

/** v0.13 批量处理出的待采纳版本列表（按章分组，对比 / 采纳 / 弃用 / 撤回） */
export function IterationList({ bookId, methods, active }: { bookId: number; methods: string[]; active?: boolean }) {
  const [view, setView] = useState<'pending' | 'all'>('pending')
  const [openId, setOpenId] = useState<number | null>(null)
  const [adopted, setAdopted] = useState<Record<number, number>>({})
  const list = useQuery({ queryKey: wqk.iterations(bookId), queryFn: () => wanbenApi.iterations(bookId), refetchInterval: active ? 3000 : false })
  const mine = (list.data ?? []).filter((x) => methods.includes(x.method))
  const rows = mine.filter((x) => view === 'all' || x.status === 'pending' || adopted[x.id] != null)
  const groups = useMemo(() => {
    const m = new Map<number, WanbenIteration[]>()
    for (const it of rows) m.set(it.number, [...(m.get(it.number) ?? []), it])
    return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([n, its]) => [n, [...its].sort((a, b) => b.round - a.round)] as const)
  }, [rows])
  const pending = mine.filter((x) => x.status === 'pending')
  const { adopt } = useIterActions(bookId)
  const [bulk, setBulk] = useState(false)
  const adoptAll = async () => {
    setBulk(true)
    try { for (const it of pending) await adopt.mutateAsync(it.id) } finally { setBulk(false) }
  }
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="text-[13.5px] font-semibold">待采纳版本</div>
        <div className="flex items-center gap-2">
          {pending.length > 1 && <Button size="sm" variant="soft" loading={bulk} icon={<Check className="h-3.5 w-3.5" />} onClick={() => void adoptAll()}>全部采纳</Button>}
          <Segmented size="sm" value={view} onChange={setView} options={[{ value: 'pending', label: `待采纳 ${pending.length}` }, { value: 'all', label: '全部' }]} />
        </div>
      </div>
      {list.isLoading ? <Skeleton className="h-24 rounded-xl" /> : !groups.length ? (
        <p className="rounded-xl border border-dashed px-4 py-6 text-center text-[12.5px] text-muted-foreground">{view === 'pending' ? '没有待采纳的版本' : '还没有批量改过'}</p>
      ) : (
        <div className="space-y-3">
          {groups.map(([n, its]) => (
            <div key={n} className="overflow-hidden rounded-xl hairline">
              <div className="flex items-center justify-between gap-2 border-b bg-subtle/70 px-3.5 py-2">
                <span className="text-[13px] font-semibold">第 {n} 章</span>
                <Link to={`/books/${bookId}/chapters/${its[0].chapter_id}`} className="inline-flex h-8 items-center gap-1 text-[12.5px] text-primary hover:underline">打开章节<ArrowUpRight className="h-3.5 w-3.5" /></Link>
              </div>
              <div className="divide-y">
                {its.map((it) => <IterRow key={it.id} it={it} onOpen={() => setOpenId(it.id)} canUndo={adopted[it.id] != null} bookId={bookId}
                  onAdopted={(cid) => setAdopted((m) => ({ ...m, [it.id]: cid }))} onUndone={() => setAdopted((m) => { const x = { ...m }; delete x[it.id]; return x })} />)}
              </div>
            </div>
          ))}
        </div>
      )}
      <CompareSheet bookId={bookId} id={openId} onClose={() => setOpenId(null)} onAdopted={(id, cid) => setAdopted((m) => ({ ...m, [id]: cid }))} />
    </div>
  )
}
