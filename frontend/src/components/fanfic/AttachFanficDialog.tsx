import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ShieldCheck } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { FIDELITY_FALLBACK, Lbl } from '@/components/fanfic/bits'
import { fanficApi, fqk, qk } from '@/lib/api'
import type { FanficDirectionId, FanficFidelity } from '@/lib/types'
import { cn } from '@/lib/utils'

/** v0.11：把已有原创书设为同人（POST /books/{id}/fanfic，需勾选版权声明）；设好后概览出现同人信息卡 */
export function AttachFanficDialog({ bookId, open, onOpenChange }: { bookId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const sources = useQuery({ queryKey: fqk.sources, queryFn: fanficApi.sources, enabled: open })
  const cat = useQuery({ queryKey: fqk.directions, queryFn: fanficApi.directions, staleTime: 3600_000, enabled: open })
  const [sourceId, setSourceId] = useState(0)
  const [direction, setDirection] = useState<FanficDirectionId | null>(null)
  const [fidelity, setFidelity] = useState<FanficFidelity>('moderate')
  const [notes, setNotes] = useState('')
  const [ack, setAck] = useState(false)
  useEffect(() => { if (open && !sourceId && sources.data?.length) setSourceId(sources.data[0].id) }, [open, sources.data, sourceId])
  const dirs = cat.data?.directions ?? []
  const fids = cat.data?.fidelities?.length ? cat.data.fidelities : FIDELITY_FALLBACK
  const dir = dirs.find((d) => d.id === direction)
  const m = useMutation({
    mutationFn: () => fanficApi.attachFanfic(bookId, { source_id: sourceId, direction: direction!, fidelity, notes: notes.trim().slice(0, 1000), copyright_ack: true }),
    meta: { errorTitle: '设为同人失败' },
    onSuccess: (r) => {
      qc.setQueryData(fqk.book(bookId), r)
      qc.invalidateQueries({ queryKey: qk.book(bookId) })
      qc.invalidateQueries({ queryKey: qk.books })
      qc.invalidateQueries({ queryKey: fqk.sources })
      toast.success('已设为同人书', { description: '写大纲、写章、审稿会带上原著设定；可在同人信息卡导入原著角色' })
      onOpenChange(false)
    },
  })
  const missing = !sourceId ? '选原著' : !direction ? '选方向' : !ack ? '勾选版权声明' : ''
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent wide title="设为同人书" desc="给这本原创书绑定原著资料。已写的设定、大纲和正文都不动，之后的生成会按原著设定来。"
        footer={<>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
          <Button variant="primary" disabled={!!missing} title={missing ? `还需要：${missing}` : undefined} loading={m.isPending} onClick={() => m.mutate()}>{missing ? `还需要${missing}` : '设为同人'}</Button>
        </>}>
        {sources.isLoading ? <Skeleton className="h-40 rounded-xl" /> : !sources.data?.length ? (
          <p className="rounded-xl border border-dashed px-4 py-8 text-center text-[13px] text-muted-foreground">还没有原著资料。<Link to="/fanfic" className="text-primary underline-offset-2 hover:underline" onClick={() => onOpenChange(false)}>先去同人页导入一份 →</Link></p>
        ) : (
          <div className="space-y-4">
            <div>
              <Lbl>原著</Lbl>
              <Select value={sourceId ? String(sourceId) : null} onChange={(v) => setSourceId(Number(v) || 0)} className="h-10" placeholder="选择原著资料"
                options={sources.data.map((s) => ({ value: String(s.id), label: `${s.title || `原著 #${s.id}`}（${s.counts.characters} 角色）` }))} />
            </div>
            <div>
              <Lbl>创作方向</Lbl>
              {cat.isLoading ? <Skeleton className="h-20 rounded-lg" /> : (
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  {dirs.map((d) => (
                    <button key={d.id} type="button" onClick={() => { setDirection(d.id); setFidelity(d.suggested_fidelity) }}
                      className={cn('focus-ring min-h-[40px] rounded-lg border px-2.5 py-2 text-left text-[13px] font-medium transition', direction === d.id ? 'border-primary bg-primary-soft text-primary' : 'bg-surface hover:border-foreground/25')}>
                      {d.label}
                    </button>
                  ))}
                </div>
              )}
              {dir && <p className="mt-1.5 text-[12px] leading-relaxed text-muted-foreground">{dir.desc}</p>}
            </div>
            <div>
              <Lbl>遵循度</Lbl>
              <Segmented block value={fidelity} onChange={setFidelity} className="h-10" options={fids.map((f) => ({ value: f.id, label: f.label }))} />
              <p className="mt-1.5 text-[12px] text-muted-foreground">{fids.find((f) => f.id === fidelity)?.desc}</p>
            </div>
            <div>
              <Lbl hint="可选">补充说明</Lbl>
              <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={1000} className="min-h-[64px]" placeholder="例如：从原著第 30 章之后分岔；主角是原创角色" />
            </div>
            <label className="flex min-h-[44px] cursor-pointer items-start gap-2.5 rounded-xl bg-subtle px-3.5 py-3">
              <input type="checkbox" className="mt-0.5 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              <span className="flex gap-1.5 text-[12.5px] leading-relaxed text-foreground/85"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />{cat.data?.copyright_notice ?? '同人创作仅供个人创作与学习交流使用，对外发布前请自行确认原著授权范围，不得用于商业用途。'}</span>
            </label>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
