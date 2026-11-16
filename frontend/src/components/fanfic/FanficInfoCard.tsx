import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, BookOpenCheck, Copy, Eye, Layers } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { FIDELITY_FALLBACK } from '@/components/fanfic/bits'
import { fanficApi, fqk, qk, type FanficPatchInput } from '@/lib/api'
import type { FanficDirectionId, FanficFidelity, FanficImportPart } from '@/lib/types'
import { cn, copyText, fmtDateTime } from '@/lib/utils'

/** 书概览：同人信息卡（原著、方向、遵循度可改、注入上下文预览、导入原著设定） */
export function FanficInfoCard({ bookId, className }: { bookId: number; className?: string }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: fqk.book(bookId), queryFn: () => fanficApi.bookFanfic(bookId) })
  const cat = useQuery({ queryKey: fqk.directions, queryFn: fanficApi.directions, staleTime: 3600_000 })
  const [ctxOpen, setCtxOpen] = useState(false)
  const [notes, setNotes] = useState<string | null>(null)
  const ctx = useQuery({ queryKey: fqk.context(bookId), queryFn: () => fanficApi.context(bookId), enabled: ctxOpen })

  const patch = useMutation({
    mutationFn: (b: FanficPatchInput) => fanficApi.patchFanfic(bookId, b),
    meta: { errorTitle: '修改失败' },
    onSuccess: (r) => {
      qc.setQueryData(fqk.book(bookId), r)
      qc.invalidateQueries({ queryKey: fqk.context(bookId) })
      qc.invalidateQueries({ queryKey: qk.book(bookId) })
      setNotes(null)
      toast.success('同人设置已更新')
    },
  })
  const imp = useMutation({
    mutationFn: (parts: FanficImportPart[]) => fanficApi.importCards(bookId, parts),
    meta: { errorTitle: '导入失败' },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: qk.cards(bookId) })
      qc.invalidateQueries({ queryKey: ['completeness', bookId] })
      toast.success(`已导入 ${r.cards?.length ?? 0} 条${r.skipped ? `，跳过重名 ${r.skipped} 条` : ''}`)
    },
  })

  if (q.isLoading) return <Skeleton className={cn('mt-6 h-40 rounded-xl', className)} />
  const f = q.data?.fanfic
  if (!f) return null
  const fids = cat.data?.fidelities?.length ? cat.data.fidelities : FIDELITY_FALLBACK
  const dirs = cat.data?.directions ?? []
  const dir = dirs.find((d) => d.id === f.direction)

  return (
    <Card className={cn('mt-6', className)}>
      <CardHeader icon={<BookOpenCheck />} title="同人信息" desc={`原著：${f.source?.title ?? f.source_title}`}
        action={<Button size="sm" className="h-10" icon={<Eye className="h-3.5 w-3.5" />} onClick={() => setCtxOpen(true)}>注入上下文</Button>} />
      <CardBody className="space-y-4 p-4 sm:p-5">
        {f.source_missing && (
          <p className="flex gap-1.5 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />原著资料已删除：写章时只按遵循规则把握，不再注入原著角色与时间线，OOC 检查不可用。</p>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <div className="min-w-0">
            <div className="mb-1 text-[12px] font-medium text-muted-foreground">原著资料</div>
            {f.source ? (
              <Link to={`/fanfic/${f.source.id}`} className="card-hover focus-ring flex min-h-[48px] min-w-0 items-center gap-2 rounded-lg border px-3 py-2">
                <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-semibold">{f.source.title}</span>
                  <span className="num block text-[12px] text-muted-foreground">{f.source.counts.characters} 角色 · 完整度 {f.source.completeness}</span></span>
                <span className="shrink-0 text-[12px] text-primary">设定卡 →</span>
              </Link>
            ) : <div className="rounded-lg border border-dashed px-3 py-3 text-[13px] text-muted-foreground">{f.source_title}（已删除）</div>}
            {f.extra_source_ids?.length > 0 && <p className="mt-1 text-[12px] text-muted-foreground">联动原著 {f.extra_source_ids.length} 部</p>}
          </div>
          <div className="min-w-0">
            <div className="mb-1 text-[12px] font-medium text-muted-foreground">创作方向</div>
            <Select value={f.direction} className="h-10" onChange={(v) => v && v !== f.direction && patch.mutate({ direction: v as FanficDirectionId })}
              options={dirs.length ? dirs.map((d) => ({ value: d.id, label: d.label })) : [{ value: f.direction, label: f.direction_label }]} />
            {dir && <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{dir.desc}</p>}
          </div>
        </div>
        <div>
          <div className="mb-1 text-[12px] font-medium text-muted-foreground">遵循度（改档不必重新确认版权）</div>
          <div className="grid gap-1.5 sm:grid-cols-3">
            {fids.map((x) => {
              const on = f.fidelity === x.id
              return (
                <button key={x.id} type="button" aria-pressed={on} disabled={patch.isPending}
                  onClick={() => !on && patch.mutate({ fidelity: x.id as FanficFidelity })}
                  className={cn('focus-ring min-h-[56px] min-w-0 rounded-lg border px-3 py-2 text-left transition disabled:opacity-60', on ? 'border-primary bg-primary-soft/40' : 'hover:border-foreground/20')}>
                  <span className="flex items-center gap-1.5"><span className={cn('text-[13.5px] font-semibold', on && 'text-primary')}>{x.label}</span><span className="num ml-auto text-[11px] text-muted-foreground">通过线 {x.pass_score}</span></span>
                  <span className="block text-[11.5px] leading-snug text-muted-foreground">{x.desc}</span>
                </button>
              )
            })}
          </div>
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between text-[12px] font-medium text-muted-foreground"><span>作者补充</span>
            {notes === null && <button type="button" onClick={() => setNotes(f.notes ?? '')} className="focus-ring inline-flex h-10 items-center rounded-md px-2 text-primary hover:bg-primary-soft/60">编辑</button>}</div>
          {notes === null ? (
            <p className={cn('whitespace-pre-wrap break-words text-[13px] leading-relaxed', !f.notes && 'text-muted-foreground')}>{f.notes || '（未填写）'}</p>
          ) : (
            <div className="space-y-2">
              <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value.slice(0, 1000))} />
              <div className="flex justify-end gap-2">
                <Button className="h-10" onClick={() => setNotes(null)}>取消</Button>
                <Button variant="primary" className="h-10" loading={patch.isPending} onClick={() => patch.mutate({ notes })}>保存</Button>
              </div>
            </div>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <Button variant="soft" className="h-10" loading={imp.isPending} disabled={f.source_missing} icon={<Layers className="h-4 w-4" />}
            onClick={() => imp.mutate(['characters', 'factions', 'world', 'locations'])}>导入原著设定到设定库</Button>
          <span className="text-[11.5px] text-muted-foreground">版权确认于 {fmtDateTime(f.copyright_ack_at)}</span>
        </div>
      </CardBody>

      <Dialog open={ctxOpen} onOpenChange={setCtxOpen}>
        <DialogContent wide title="同人注入上下文" desc={ctx.data ? `写大纲、写章等提示词末尾自动附上这段（${ctx.data.chars} 字）` : '加载中…'}
          footer={<Button className="h-10" icon={<Copy className="h-4 w-4" />} disabled={!ctx.data?.text} onClick={async () => { if (await copyText(ctx.data?.text ?? '')) toast.success('已复制') }}>复制</Button>}>
          {ctx.isLoading ? <Skeleton className="h-48" /> : ctx.isError ? <p className="text-[13px] text-danger">{(ctx.error as any)?.message}</p> : (
            <pre className="whitespace-pre-wrap break-words rounded-lg bg-subtle p-3 font-sans text-[12.5px] leading-relaxed">{ctx.data?.text || '（空）'}</pre>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  )
}
