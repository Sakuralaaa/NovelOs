import { useState } from 'react'
import { Check, Loader2, Wand2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Segmented } from '@/components/ui/tabs'
import { CompareRow } from '@/components/common/AiAsk'
import { EstimateBody, useEstimate } from '@/components/cost/CostButton'
import { api } from '@/lib/api'
import { useCostHint } from '@/lib/cost'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { FieldAiMode, FieldAiResult } from '@/lib/types'
import { cn } from '@/lib/utils'

export const FIELD_AI_MODES: { value: FieldAiMode; label: string; desc: string }[] = [
  { value: 'fill', label: '补全', desc: '空着就补写；已有内容给一个补全版' },
  { value: 'rewrite', label: '改写', desc: '按你的要求换个写法' },
  { value: 'expand', label: '扩写', desc: '在原内容基础上写得更具体' },
]
export const asText = (v: unknown) => (Array.isArray(v) ? v.map(String).join('；') : v == null ? '' : typeof v === 'string' ? v : JSON.stringify(v))

/**
 * 字段旁的小 AI 按钮：选「补全 / 改写 / 扩写」+ 可选指令 → 后台任务 → 对比浮层「采纳 / 放弃」。
 * 只出建议值，不直接写库；采纳由 onAdopt 决定（设定库里走 field-ai/apply 同步写入）。
 */
export function FieldAiButton({ bookId, entryId, field, label, onAdopt, disabled, className }: {
  bookId: number; entryId: number; field: string; label: string
  onAdopt: (value: unknown) => Promise<unknown> | void
  disabled?: boolean; className?: string
}) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<FieldAiMode>('fill')
  const [ins, setIns] = useState('')
  const [res, setRes] = useState<(FieldAiResult & { edited: string }) | null>(null)
  const [adopting, setAdopting] = useState(false)
  const hint = useCostHint()
  const est = useEstimate({ kind: 'field_ai', bookId }, hint && open)
  const { start } = useJobs()
  const key = `field-ai:${entryId}:${field}`
  const job = useActiveJob(key)

  const go = () => {
    setOpen(false)
    start(api.fieldAi(bookId, entryId, { field, mode, ...(ins.trim() ? { instruction: ins.trim() } : {}) }), {
      key, label: `AI ${FIELD_AI_MODES.find((m) => m.value === mode)!.label}「${label}」`, silent: true,
      onSuccess: (j) => {
        const r = j.result as FieldAiResult | null
        if (!r) return
        setRes({ ...r, edited: asText(r.value) })
      },
    })
  }
  const adopt = async () => {
    if (!res) return
    const v = Array.isArray(res.value) ? res.edited.split(/[；;]/).map((x) => x.trim()).filter(Boolean) : res.edited
    setAdopting(true)
    try { await onAdopt(v); setRes(null); setIns('') } catch { /* 报错由 mutation 统一 toast */ } finally { setAdopting(false) }
  }

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button type="button" disabled={disabled || !!job} aria-label={`AI 处理${label}`}
            className={cn('focus-ring inline-flex h-8 items-center gap-1 rounded-md px-2 text-[12px] font-normal text-muted-foreground transition hover:bg-primary-soft hover:text-primary disabled:opacity-50 [@media(pointer:coarse)]:h-10 [@media(pointer:coarse)]:px-2.5', job && 'text-primary', className)}>
            {job ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}{job ? `${Math.round(job.progress)}%` : 'AI'}
          </button>
        </PopoverTrigger>
        <PopoverContent align="end" className="w-[320px]">
          <div className="mb-2 text-[13px] font-semibold">AI 处理「{label}」</div>
          <Segmented block value={mode} onChange={setMode} options={FIELD_AI_MODES.map((m) => ({ value: m.value, label: m.label }))} className="h-10" />
          <p className="mt-1.5 text-[12px] text-muted-foreground">{FIELD_AI_MODES.find((m) => m.value === mode)!.desc}</p>
          <Input value={ins} onChange={(e) => setIns(e.target.value.slice(0, 500))} className="mt-2.5 h-10 text-[13px]" placeholder="可选：写要求，如「更狠一点」「不超过 30 字」"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing) go() }} />
          {hint && <div className="mt-3 rounded-lg bg-subtle px-3 py-2.5"><EstimateBody q={est} compact /></div>}
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" className="h-10" onClick={() => setOpen(false)}>取消</Button>
            <Button variant="primary" className="h-10" icon={<Wand2 className="h-4 w-4" />} onClick={go}>生成建议</Button>
          </div>
        </PopoverContent>
      </Popover>
      <Dialog open={!!res} onOpenChange={(o) => !o && setRes(null)}>
        {res && (
          <DialogContent wide title={`AI ${FIELD_AI_MODES.find((m) => m.value === res.mode)?.label ?? ''}建议 · ${label}`} desc="左边是现在的内容，右边是建议（可以再手改）。采纳后立即写入设定库，写前自动存快照。"
            footer={<><Button variant="ghost" className="h-10" onClick={() => setRes(null)}>放弃</Button><Button variant="primary" className="h-10" loading={adopting} icon={<Check className="h-4 w-4" />} onClick={adopt}>采纳</Button></>}>
            <CompareRow label={label} before={asText(res.before)} after={res.edited} onChange={(v) => setRes({ ...res, edited: v })} multiline />
            {res.note && <p className="mt-3 text-[12.5px] text-muted-foreground">{res.note}</p>}
          </DialogContent>
        )}
      </Dialog>
    </>
  )
}
