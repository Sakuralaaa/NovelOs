import { forwardRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowUpRight, CheckCircle2, Gem, Plus, X } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Progress, Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { api, wanbenApi, wqk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { RefineChapter } from '@/lib/types'
import { cn, fmtNum } from '@/lib/utils'
import { ChStatus, parseRanges } from './bits'

const SCOPE_LABEL: Record<string, string> = { first_n: '前 N 章', all: '全书', custom: '自选区间', none: '不精修' }

/** 精修范围状态：每章状态、审批、读者分（低于阈值标红），审批走现有 commit；可增删章号 */
export const RefineCard = forwardRef<HTMLDivElement, { bookId: number; className?: string }>(({ bookId, className }, ref) => {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: wqk.refine(bookId), queryFn: () => wanbenApi.refine(bookId) })
  const [filter, setFilter] = useState<'all' | 'todo'>('all')
  const [add, setAdd] = useState('')
  const edit = useMutation({
    mutationFn: (p: { action: 'add' | 'remove'; ranges: [number, number][] }) => wanbenApi.editRefine(bookId, p.action, p.ranges),
    meta: { errorTitle: '修改精修范围失败' },
    onSuccess: (r, p) => {
      qc.setQueryData(wqk.refine(bookId), r)
      qc.invalidateQueries({ queryKey: wqk.settings(bookId) })
      if (p.action === 'add') setAdd('')
      toast.success(p.action === 'add' ? '已加入精修范围' : '已移出精修范围', { description: '精修范围已改为「自选区间」' })
    },
  })
  const r = q.data
  const rows = (r?.chapters ?? []).filter((c) => filter === 'all' || !c.approved)
  const addRanges = parseRanges(add)

  return (
    <div ref={ref} className={cn('scroll-mt-20', className)}><Card>
      <CardHeader icon={<Gem />} title="精修范围" desc={r ? `${SCOPE_LABEL[r.refine_scope] ?? r.refine_scope} · ${r.total} 章 · 已审批 ${r.approved}` : '…'}
        action={r && r.total > 0 ? <Segmented size="sm" value={filter} onChange={setFilter} options={[{ value: 'all', label: '全部' }, { value: 'todo', label: `待处理 ${r.total - r.approved}` }]} /> : undefined} />
      <CardBody className="space-y-3 p-4 sm:p-5">
        {q.isLoading ? <Skeleton className="h-32 rounded-xl" /> : !r ? null : (
          <>
            {r.total > 0 && (
              <div>
                <div className="num mb-1.5 flex flex-wrap items-center justify-between gap-2 text-[12.5px] text-muted-foreground">
                  <span>已写 {r.written} · 已审批 {r.approved} · 未写 {r.unwritten}</span>
                </div>
                <Progress value={(r.approved / Math.max(1, r.total)) * 100} tone={r.all_approved ? 'success' : 'primary'} />
              </div>
            )}
            {r.total === 0 ? (
              <p className="rounded-xl border border-dashed px-4 py-6 text-center text-[12.5px] text-muted-foreground">没有设精修范围：审稿通过的章节自动提交。可以在下面加几章进来。</p>
            ) : rows.length === 0 ? (
              <p className="flex items-center justify-center gap-1.5 py-6 text-[13px] text-success"><CheckCircle2 className="h-4 w-4" />精修章都审批过了</p>
            ) : (
              <div className="divide-y overflow-hidden rounded-xl hairline md:max-h-[560px] md:overflow-y-auto">
                {rows.map((c) => <RefineRow key={c.number} bookId={bookId} c={c} onRemove={() => edit.mutate({ action: 'remove', ranges: [[c.number, c.number]] })} removing={edit.isPending} />)}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Input value={add} onChange={(e) => setAdd(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && addRanges.length) edit.mutate({ action: 'add', ranges: addRanges }) }}
                placeholder="加入章号，如 11-15, 30" className="h-9 min-w-0 flex-1 basis-48" />
              <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} disabled={!addRanges.length} loading={edit.isPending && edit.variables?.action === 'add'} onClick={() => edit.mutate({ action: 'add', ranges: addRanges })}>加入精修</Button>
            </div>
          </>
        )}
      </CardBody>
    </Card></div>
  )
})
RefineCard.displayName = 'RefineCard'

function RefineRow({ bookId, c, onRemove, removing }: { bookId: number; c: RefineChapter; onRemove: () => void; removing: boolean }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const key = `commit:${c.chapter_id ?? 0}`
  const committing = useActiveJob(key)
  const approve = () => c.chapter_id && start(api.commitChapter(c.chapter_id), {
    key, label: '提交入账', successMsg: `第 ${c.number} 章已审批提交`,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['wanben', bookId] }),
  })
  return (
    <div className="flex items-center gap-2.5 bg-surface px-3 py-2.5 sm:px-3.5">
      <span className="num w-9 shrink-0 text-[12.5px] font-semibold text-muted-foreground">第{c.number}</span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13.5px] font-medium">{c.title || (c.status === 'unwritten' ? '（未写）' : `第${c.number}章`)}</div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <ChStatus status={c.status} />
          {c.iterations_pending > 0 && <Badge tone="primary">{c.iterations_pending} 版待选</Badge>}
          <span className="num text-[11.5px] text-muted-foreground">{c.words ? `${fmtNum(c.words)} 字` : ''}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        {c.chapter_id && !c.approved && <Button size="sm" variant="soft" loading={!!committing} onClick={() => void approve()}>审批<span className="hidden sm:inline">提交</span></Button>}
        {c.approved && <span title="已审批提交" className="inline-flex h-9 items-center gap-1 px-1.5 text-[12.5px] font-medium text-success"><CheckCircle2 className="h-4 w-4" /><span className="hidden sm:inline">已审批</span></span>}
        {c.chapter_id && (
          <Link to={`/books/${bookId}/chapters/${c.chapter_id}`} aria-label={`打开第${c.number}章`} title="打开章节编辑" className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"><ArrowUpRight className="h-4 w-4" /></Link>
        )}
        <button type="button" aria-label="移出精修范围" title="移出精修范围" disabled={removing} onClick={onRemove}
          className="focus-ring inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-danger-soft hover:text-danger disabled:opacity-50"><X className="h-4 w-4" /></button>
      </div>
    </div>
  )
}
