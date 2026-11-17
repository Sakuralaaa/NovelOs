import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Copy, Search, Star, Trash2 } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Segmented } from '@/components/ui/tabs'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { AskBox, useModelRoute } from '@/components/common/AiAsk'
import { Skeleton } from '@/components/ui/misc'
import { useBooks } from '@/hooks/queries'
import { api } from '@/lib/api'
import { fmtCny } from '@/lib/cost'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Generation, GenStatus } from '@/lib/types'
import { cn, fmtTime } from '@/lib/utils'

const STATUS: Record<GenStatus, { l: string; t: 'success' | 'warning' | 'danger' }> = {
  ok: { l: '成功', t: 'success' }, empty: { l: '空结果', t: 'warning' }, failed: { l: '失败', t: 'danger' },
}
const PAGE = 40

/** v0.12 生成档案：每次模型调用都在这里，成功、空结果、失败都有记录；追问出新版本，旧的保留 */
export default function HistoryPage() {
  const [sp, setSp] = useSearchParams()
  const bookId = sp.get('book') ? Number(sp.get('book')) : undefined
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState<'' | GenStatus>('')
  const [starred, setStarred] = useState(false)
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [page, setPage] = useState(0)
  const [openId, setOpenId] = useState<number | null>(null)
  const books = useBooks()
  const params = { book_id: bookId, kind: kind || undefined, status: status || undefined, q: term || undefined, starred, limit: PAGE, offset: page * PAGE }
  const list = useQuery({ queryKey: ['generations', params], queryFn: () => api.generations(params), placeholderData: keepPreviousData })
  const budget = useQuery({ queryKey: ['budget', bookId ?? 0], queryFn: () => api.budget(bookId) })
  const bookOpts = (books.data ?? []).map((b) => ({ value: String(b.id), label: b.title }))
  const kindOpts = (list.data?.kinds ?? []).map((k) => ({ value: k.kind, label: `${k.label}（${k.count}）` }))
  const total = list.data?.total ?? 0
  const reset = () => setPage(0)

  return (
    <div className="page">
      <PageHeader title="生成档案" />
      <div className="mb-4 flex flex-wrap items-center gap-2 text-[12.5px] text-muted-foreground">
        <span className="rounded-full bg-surface px-3 py-1 hairline">共 <span className="num">{total}</span> 条</span>
        <span className="rounded-full bg-surface px-3 py-1 hairline">筛选内花费 <span className="num">{fmtCny(list.data?.cost_cny ?? 0)}</span></span>
        {budget.data && <span className="rounded-full bg-surface px-3 py-1 hairline">今日 <span className="num">{fmtCny(budget.data.today_cny)}</span>{budget.data.daily_cny > 0 && <> / {fmtCny(budget.data.daily_cny)}</>}</span>}
        {budget.data?.book_spent_cny !== undefined && <span className="rounded-full bg-surface px-3 py-1 hairline">本书累计 <span className="num">{fmtCny(budget.data.book_spent_cny)}</span>{budget.data.book_cny > 0 && <> / {fmtCny(budget.data.book_cny)}</>}</span>}
      </div>
      <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-[200px_180px_auto_auto_1fr]">
        <Select value={bookId ? String(bookId) : null} onChange={(v) => { if (v) sp.set('book', v); else sp.delete('book'); setSp(sp, { replace: true }); reset() }}
          options={bookOpts} allowEmpty emptyLabel="全部作品" placeholder="全部作品" />
        <Select value={kind || null} onChange={(v) => { setKind(v ?? ''); reset() }} options={kindOpts} allowEmpty emptyLabel="全部类型" placeholder="全部类型" />
        <Segmented value={status} onChange={(v) => { setStatus(v); reset() }} options={[{ value: '', label: '全部' }, { value: 'ok', label: '成功' }, { value: 'failed', label: '失败' }, { value: 'empty', label: '空结果' }]} />
        <Button variant={starred ? 'soft' : 'ghost'} icon={<Star className="h-4 w-4" weight={starred ? 'fill' : 'regular'} />} onClick={() => { setStarred((x) => !x); reset() }}>收藏</Button>
        <form className="relative" onSubmit={(e) => { e.preventDefault(); setTerm(q.trim()); reset() }}>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜内容" className="pl-9" />
        </form>
      </div>

      {list.isLoading ? <div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-16" />)}</div>
        : list.error ? <ErrorState error={list.error} onRetry={() => list.refetch()} />
        : !list.data?.items.length ? <EmptyState kind="chapter" title="还没有记录" />
        : (
          <div className="space-y-2">
            {list.data.items.map((g) => <GenRow key={g.id} g={g} onOpen={() => setOpenId(g.id)} />)}
            {total > PAGE && (
              <div className="flex items-center justify-center gap-2 pt-2">
                <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>上一页</Button>
                <span className="num text-[12.5px] text-muted-foreground">{page + 1} / {Math.ceil(total / PAGE)}</span>
                <Button size="sm" variant="ghost" disabled={(page + 1) * PAGE >= total} onClick={() => setPage((p) => p + 1)}>下一页</Button>
              </div>
            )}
          </div>
        )}
      <GenSheet id={openId} onClose={() => setOpenId(null)} onOpen={setOpenId} />
    </div>
  )
}

function GenRow({ g, onOpen }: { g: Generation; onOpen: () => void }) {
  const st = STATUS[g.status] ?? STATUS.ok
  return (
    <button onClick={onOpen} className="focus-ring flex w-full items-start gap-3 rounded-xl bg-surface p-3.5 text-left hairline transition hover:shadow-card">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[13.5px] font-medium">{g.kind_label}</span>
          <Badge tone={st.t} className="h-5 text-[11px]">{st.l}</Badge>
          {g.short && <Badge tone="warning" className="h-5 text-[11px]">字数不足</Badge>}
          {g.parent_id && <Badge tone="outline" className="h-5 text-[11px]">追问</Badge>}
          {g.starred && <Star className="h-3.5 w-3.5 text-amber-500" weight="fill" />}
        </div>
        <p className={cn('mt-1 line-clamp-2 text-[12.5px] leading-relaxed', g.status === 'failed' ? 'text-danger' : 'text-muted-foreground')}>
          {g.status === 'failed' ? g.error : g.preview || '（无内容）'}
        </p>
      </div>
      <div className="shrink-0 text-right text-[11.5px] text-muted-foreground">
        <div>{fmtTime(g.created_at)}</div>
        <div className="num mt-0.5">{g.output_words ? `${g.output_words} 字 · ` : ''}{fmtCny(g.cost_cny)}</div>
        <div className="mt-0.5 max-w-[160px] truncate font-mono text-[11px]">{g.model}</div>
      </div>
    </button>
  )
}

function GenSheet({ id, onClose, onOpen }: { id: number | null; onClose: () => void; onOpen: (id: number) => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['generation', id], queryFn: () => api.generation(id!), enabled: id != null })
  const g = q.data
  const [tab, setTab] = useState<'output' | 'prompt'>('output')
  const [ask, setAsk] = useState('')
  const storage = useModelRoute('novelos.followup-route')
  const { start } = useJobs()
  const job = useActiveJob(id != null ? `gen-followup:${id}` : undefined)
  const [confirmDel, setConfirmDel] = useState(false)
  const refresh = () => { qc.invalidateQueries({ queryKey: ['generations'] }); qc.invalidateQueries({ queryKey: ['generation'] }) }
  const star = useMutation({ mutationFn: (v: boolean) => api.patchGeneration(id!, { starred: v }), meta: { errorTitle: '操作失败' }, onSuccess: refresh })
  const del = useMutation({
    mutationFn: () => api.deleteGeneration(id!), meta: { errorTitle: '删除失败' },
    onSuccess: () => { refresh(); setConfirmDel(false); onClose(); toast.success('已删除') },
  })
  const followup = () => {
    if (!g) return
    start(api.followupGeneration(g.id, { instruction: ask.trim(), route: storage.model }), {
      key: `gen-followup:${g.id}`, label: '追问', silent: true,
      onSuccess: (j) => { refresh(); setAsk(''); const nid = (j.result as any)?.id; toast.success('出了新版本，原来的保留着'); if (nid) onOpen(nid) },
      onError: (j) => toast.error('追问失败', { description: j.error ?? undefined }),
    })
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText((tab === 'output' ? g?.output : g?.prompt) ?? ''); toast.success('已复制') } catch { toast.error('复制失败') }
  }
  const versions = useMemo(() => g?.children ?? [], [g])
  const st = g ? STATUS[g.status] ?? STATUS.ok : null
  return (
    <Sheet open={id != null} onOpenChange={(o) => { if (!o) { onClose(); setConfirmDel(false) } }} width={720}
      title={g ? `${g.kind_label} · ${fmtTime(g.created_at)}` : '记录'}
      footer={g && <div className="flex w-full flex-wrap items-center gap-2">
        {confirmDel
          ? <Button variant="danger" className="h-10" loading={del.isPending} onClick={() => del.mutate()}>确认删除</Button>
          : <Button variant="ghost" className="h-10 text-danger hover:bg-danger-soft hover:text-danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDel(true)}>删除</Button>}
        <Button variant="ghost" className="h-10" icon={<Star className="h-4 w-4" weight={g.starred ? 'fill' : 'regular'} />} loading={star.isPending} onClick={() => star.mutate(!g.starred)}>{g.starred ? '取消收藏' : '收藏'}</Button>
        <Button variant="ghost" className="ml-auto h-10" icon={<Copy className="h-4 w-4" />} onClick={copy}>复制</Button>
      </div>}>
      {!g ? <div className="space-y-2"><Skeleton className="h-6" /><Skeleton className="h-64" /></div> : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
            {st && <Badge tone={st.t} className="h-5 text-[11px]">{st.l}</Badge>}
            {g.short && <Badge tone="warning" className="h-5 text-[11px]">字数不足：{g.output_words} / {g.target_words}</Badge>}
            <span className="font-mono">{g.model}</span>
            <span className="num">· 入 {g.in_tokens} / 出 {g.out_tokens} token · {fmtCny(g.cost_cny)} · {(g.ms / 1000).toFixed(1)} 秒</span>
          </div>
          {g.parent_id && (
            <button onClick={() => onOpen(g.parent_id!)} className="text-[12.5px] text-primary hover:underline">← 原记录{g.note && `（追问：${g.note}）`}</button>
          )}
          {g.status === 'failed' && <div className="flex items-start gap-2 rounded-lg bg-danger-soft px-3.5 py-2.5 text-[13px] text-danger"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span className="break-words">{g.error}</span></div>}
          {versions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[12.5px] text-muted-foreground">追问出的版本</span>
              {versions.map((v, i) => (
                <Button key={v.id} size="xs" variant="soft" onClick={() => onOpen(v.id)}>v{i + 2}{v.status !== 'ok' && `（${STATUS[v.status]?.l}）`}</Button>
              ))}
            </div>
          )}
          <Segmented value={tab} onChange={setTab} options={[{ value: 'output', label: '结果' }, { value: 'prompt', label: '要求' }]} />
          <pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap break-words rounded-xl bg-subtle/60 p-3.5 text-[13px] leading-relaxed hairline">
            {(tab === 'output' ? g.output : g.prompt) || '（空）'}
          </pre>
          {g.status === 'ok' && !!g.output?.trim() && (
            <AskBox title="追问" placeholder="例如：再短一点；换个开头；保留第二段其余重写" value={ask} onChange={setAsk} onSubmit={followup} job={job} storage={storage} submitLabel="出新版本" />
          )}
        </div>
      )}
    </Sheet>
  )
}
