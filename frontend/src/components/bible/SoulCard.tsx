import { useEffect, useRef, useState } from 'react'
import { Bandaids, Check, Compass, Heart, MessageSquareQuote, Skull, Sparkles } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/tabs'
import { CostButton } from '@/components/cost/CostButton'
import { JobInline } from '@/components/common/JobInline'
import { FieldAiButton } from './FieldAi'
import { api } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Soul, SoulKey, SoulResult } from '@/lib/types'
import { cn } from '@/lib/utils'

export const SOUL_DIMS: { key: SoulKey; label: string; sub: string; icon: typeof Heart; tone: string; ph: string }[] = [
  { key: 'desire', label: '欲望', sub: '他最想要什么', icon: Heart, tone: 'text-rose-500 bg-rose-500/10', ph: '例如：让东区重新有一盏不灭的灯' },
  { key: 'fear', label: '恐惧', sub: '最怕失去什么', icon: Skull, tone: 'text-violet-500 bg-violet-500/10', ph: '例如：自己的规矩有一天害死信他的人' },
  { key: 'wound', label: '伤痕', sub: '过去留下的坎', icon: Bandaids, tone: 'text-amber-600 bg-amber-500/10', ph: '例如：冰封第一夜没开门，门口冻死了母子' },
  { key: 'belief', label: '信念', sub: '绝不越过的底线', icon: Compass, tone: 'text-sky-600 bg-sky-500/10', ph: '例如：只换不卖，尊严不能白拿' },
  { key: 'voice', label: '说话方式', sub: '一开口就认得出', icon: MessageSquareQuote, tone: 'text-emerald-600 bg-emerald-500/10', ph: '例如：话少、短句、爱反问，越生气越客气' },
]
export const emptySoul = (): Soul => ({ desire: '', fear: '', wound: '', belief: '', voice: '' })
export const soulFilled = (s?: Partial<Soul> | null) => SOUL_DIMS.filter((d) => s?.[d.key]?.trim()).length

/** 角色灵魂五维：五格卡片，每格可编辑 + 单格 AI；整卡「AI 补全」先对比再采纳 */
export function SoulCard({ bookId, entryId, value, onChange, onAdoptField, onAdoptAll, autoFill, aiOff }: {
  bookId: number
  /** 新建、还没保存的人物没有 id：只能手填 */
  entryId?: number
  value: Soul
  onChange: (s: Soul) => void
  onAdoptField: (key: SoulKey, v: string) => Promise<unknown>
  onAdoptAll: (s: Soul) => Promise<unknown>
  /** 打开时自动发起一次补全（从完整度待办跳过来） */
  autoFill?: boolean
  /** v0.12：设定已锁定时隐藏 AI 入口 */
  aiOff?: boolean
}) {
  const { start } = useJobs()
  const aiId = aiOff ? undefined : entryId
  const key = `soul:${entryId ?? 0}`
  const job = useActiveJob(key)
  const [mode, setMode] = useState<'fill' | 'rewrite'>('fill')
  const [ins, setIns] = useState('')
  const [res, setRes] = useState<(SoulResult & { pick: Record<SoulKey, boolean>; edited: Soul }) | null>(null)
  const [adopting, setAdopting] = useState(false)
  const n = soulFilled(value)

  const run = (m: 'fill' | 'rewrite' = mode) => {
    if (!entryId) return
    start(api.soulAi(bookId, entryId, { mode: m, ...(ins.trim() ? { instruction: ins.trim() } : {}) }), {
      key, label: m === 'fill' ? 'AI 补全灵魂五维' : 'AI 重写灵魂五维', silent: true,
      onSuccess: (j) => {
        const r = j.result as SoulResult | null
        if (!r?.soul) return
        const before = { ...emptySoul(), ...(r.before ?? value) }
        const soul = { ...emptySoul(), ...r.soul }
        setRes({ ...r, before, soul, edited: soul, pick: Object.fromEntries(SOUL_DIMS.map((d) => [d.key, soul[d.key] !== before[d.key]])) as Record<SoulKey, boolean> })
      },
    })
  }
  const auto = useRef(false)
  useEffect(() => { if (autoFill && aiId && !auto.current) { auto.current = true; run('fill') } }, [autoFill, aiId]) // eslint-disable-line react-hooks/exhaustive-deps

  const adopt = async () => {
    if (!res) return
    const next: Soul = { ...value }
    SOUL_DIMS.forEach((d) => { if (res.pick[d.key]) next[d.key] = res.edited[d.key] })
    setAdopting(true)
    try { await onAdoptAll(next); setRes(null) } catch { /* toast 由 mutation 处理 */ } finally { setAdopting(false) }
  }
  const picked = res ? SOUL_DIMS.filter((d) => res.pick[d.key]).length : 0

  return (
    <section aria-label="灵魂五维" className="rounded-xl bg-gradient-to-br from-rose-500/[0.05] via-surface to-sky-500/[0.05] p-4 hairline">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-1.5 text-[13.5px] font-semibold"><Sparkles className="h-4 w-4 text-primary" />灵魂五维<span className="num ml-1 rounded-full bg-muted px-2 text-[11.5px] font-normal leading-5 text-muted-foreground">{n}/5</span></div>
          <p className="mt-0.5 text-[12px] text-muted-foreground">写作时本章出场人物会带上这五项，人物不走样</p>
        </div>
        {aiId ? (
          <CostButton target={{ kind: 'soul', bookId }} label={mode === 'fill' ? 'AI 补全空着的几项' : 'AI 重写全部五项'} onRun={() => run()} confirmLabel="开始"
            size="sm" variant="soft" className="h-10" loading={!!job} icon={<Sparkles className="h-4 w-4" />}>AI 补全</CostButton>
        ) : !entryId ? <span className="text-[12px] text-muted-foreground">保存后可用 AI 补全</span> : null}
      </div>
      {aiId && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Segmented size="sm" value={mode} onChange={setMode} options={[{ value: 'fill', label: '只补空项' }, { value: 'rewrite', label: '全部重写' }]} className="h-10" />
          <Input value={ins} onChange={(e) => setIns(e.target.value.slice(0, 500))} placeholder="可选：要求，如「伤痕和父亲有关」" className="h-10 min-w-0 flex-1 bg-surface text-[13px]" />
        </div>
      )}
      {job && <JobInline job={job} className="mt-3" />}
      <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
        {SOUL_DIMS.map((d, i) => (
          <div key={d.key} className={cn('flex flex-col rounded-xl bg-surface p-3 hairline transition focus-within:ring-2 focus-within:ring-primary/25', i === 4 && 'sm:col-span-2')}>
            <div className="mb-1.5 flex items-center gap-2">
              <span className={cn('flex h-7 w-7 shrink-0 items-center justify-center rounded-lg', d.tone)}><d.icon className="h-4 w-4" weight="duotone" /></span>
              <div className="min-w-0 flex-1 leading-tight">
                <div className="text-[13px] font-semibold">{d.label}</div>
                <div className="truncate text-[11.5px] text-muted-foreground">{d.sub}</div>
              </div>
              {aiId && <FieldAiButton bookId={bookId} entryId={aiId} field={`soul.${d.key}`} label={`灵魂·${d.label}`} onAdopt={(v) => onAdoptField(d.key, String(v ?? ''))} />}
            </div>
            <textarea value={value[d.key] ?? ''} onChange={(e) => onChange({ ...value, [d.key]: e.target.value })} rows={2} placeholder={d.ph} aria-label={d.label}
              className="min-h-[56px] w-full resize-none rounded-md bg-transparent text-[13px] leading-relaxed outline-none placeholder:text-muted-foreground/60" />
          </div>
        ))}
      </div>
      <Dialog open={!!res} onOpenChange={(o) => !o && setRes(null)}>
        {res && (
          <DialogContent wide title={res.mode === 'fill' ? 'AI 补全的灵魂五维' : 'AI 重写的灵魂五维'} desc={res.note || '勾选要采纳的项，右侧可以再手改；采纳后立即保存。'}
            footer={<><Button variant="ghost" className="h-10" onClick={() => setRes(null)}>放弃</Button><Button variant="primary" className="h-10" disabled={!picked} loading={adopting} icon={<Check className="h-4 w-4" />} onClick={adopt}>采纳 {picked} 项</Button></>}>
            <div className="space-y-3">
              {SOUL_DIMS.map((d) => {
                const before = res.before[d.key] ?? '', after = res.edited[d.key] ?? '', same = before === res.soul[d.key]
                return (
                  <div key={d.key} className={cn('rounded-xl p-3 hairline transition', res.pick[d.key] ? 'bg-primary-soft/30' : 'bg-subtle/50 opacity-75')}>
                    <label className="flex min-h-[32px] cursor-pointer items-center gap-2 text-[13px] font-semibold">
                      <input type="checkbox" checked={res.pick[d.key]} onChange={(e) => setRes({ ...res, pick: { ...res.pick, [d.key]: e.target.checked } })} className="h-4 w-4 accent-[hsl(var(--primary))]" />
                      <d.icon className={cn('h-4 w-4', d.tone.split(' ')[0])} />{d.label}
                      {same && <span className="text-[11.5px] font-normal text-muted-foreground">未改</span>}
                    </label>
                    <div className="mt-1.5 grid gap-2 md:grid-cols-2">
                      <p className="rounded-lg bg-surface/70 px-3 py-2 text-[12.5px] leading-relaxed text-foreground/60">{before || <span className="text-muted-foreground">（空）</span>}</p>
                      <textarea value={after} rows={2} onChange={(e) => setRes({ ...res, edited: { ...res.edited, [d.key]: e.target.value } })}
                        className="min-h-[56px] w-full rounded-lg border border-success/30 bg-success-soft/40 px-3 py-2 text-[13px] leading-relaxed outline-none focus:border-primary/50" />
                    </div>
                  </div>
                )
              })}
            </div>
          </DialogContent>
        )}
      </Dialog>
    </section>
  )
}
