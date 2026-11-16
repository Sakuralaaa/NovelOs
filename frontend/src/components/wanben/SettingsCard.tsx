import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Settings } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Segmented } from '@/components/ui/tabs'
import { qk, wanbenApi, wqk } from '@/lib/api'
import type { RefineScope, WanbenSettings, WanbenSettingsInput } from '@/lib/types'
import { cn } from '@/lib/utils'
import { RangeEditor, compactNums, mergeRanges, wan } from './bits'

const SCOPES: { value: RefineScope; label: string }[] = [
  { value: 'first_n', label: '前 N 章' },
  { value: 'all', label: '全书' },
  { value: 'custom', label: '自选区间' },
  { value: 'none', label: '不精修' },
]

type Draft = Pick<WanbenSettings, 'target_words' | 'chapter_words' | 'batch_size' | 'refine_scope' | 'golden_chapters' | 'refine_ranges' | 'pause_on_unapproved_refine' | 'auto_continue'>
const toDraft = (s: WanbenSettings): Draft => ({
  target_words: s.target_words, chapter_words: s.chapter_words, batch_size: s.batch_size, refine_scope: s.refine_scope,
  golden_chapters: s.golden_chapters, refine_ranges: s.refine_ranges.map((r) => [r[0], r[1]] as [number, number]),
  pause_on_unapproved_refine: s.pause_on_unapproved_refine, auto_continue: s.auto_continue,
})

/** 完本设置：字数目标预设、每章字数、每批章数、精修范围、暂停/自动连续 */
export function SettingsCard({ bookId, settings, className }: { bookId: number; settings: WanbenSettings; className?: string }) {
  const qc = useQueryClient()
  const [d, setD] = useState<Draft>(() => toDraft(settings))
  const [dirty, setDirty] = useState(false)
  const presets = settings.presets?.length ? settings.presets : [150_000, 200_000, 300_000]
  const [custom, setCustom] = useState(() => !presets.includes(settings.target_words))
  useEffect(() => { if (!dirty) { setD(toDraft(settings)); setCustom(!presets.includes(settings.target_words)) } }, [settings]) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (p: Partial<Draft>) => { setD((x) => ({ ...x, ...p })); setDirty(true) }

  const total = Math.max(1, Math.ceil((d.target_words || 0) / Math.max(1, d.chapter_words || 1)))
  const refineCount = useMemo(() => {
    if (d.refine_scope === 'none') return 0
    if (d.refine_scope === 'all') return total
    if (d.refine_scope === 'first_n') return Math.max(0, d.golden_chapters || 0)
    return mergeRanges(d.refine_ranges.filter((r) => r[0] > 0 && r[1] > 0)).reduce((n, [a, b]) => n + Math.abs(b - a) + 1, 0)
  }, [d, total])
  const errors: string[] = []
  if (!(d.target_words >= 10_000 && d.target_words <= 10_000_000)) errors.push('字数目标在 1 万到 1000 万字之间')
  if (!(d.chapter_words >= 500 && d.chapter_words <= 20_000)) errors.push('每章字数在 500 到 20000 之间')
  if (!(d.batch_size >= 1 && d.batch_size <= 50)) errors.push('每批 1 到 50 章')

  const save = useMutation({
    mutationFn: (b: WanbenSettingsInput) => wanbenApi.saveSettings(bookId, b),
    meta: { errorTitle: '保存完本设置失败' },
    onSuccess: (s) => {
      qc.setQueryData(wqk.settings(bookId), s)
      qc.invalidateQueries({ queryKey: ['wanben', bookId] })
      qc.invalidateQueries({ queryKey: qk.book(bookId) })
      setDirty(false)
      toast.success('完本设置已保存', { description: `目标 ${wan(s.target_words)}字 · 约 ${s.total_chapters} 章 · 精修 ${s.refine_count} 章` })
    },
  })
  const submit = () => save.mutate({ ...d, refine_ranges: mergeRanges(d.refine_ranges.filter((r) => r[0] > 0 && r[1] > 0)) })

  return (
    <Card className={className}>
      <CardHeader icon={<Settings />} title="完本设置" desc={`约 ${total} 章 · 精修 ${refineCount} 章`}
        action={dirty ? <Button size="sm" variant="ghost" onClick={() => { setD(toDraft(settings)); setDirty(false) }}>还原</Button> : undefined} />
      <CardBody className="space-y-5 p-4 sm:p-5">
        <Field label="字数目标" hint="只是字数参考档位">
          <div className="grid grid-cols-4 gap-1.5">
            {presets.map((p) => (
              <button key={p} type="button" onClick={() => { setCustom(false); set({ target_words: p }) }}
                className={cn('focus-ring h-10 rounded-lg border text-[13.5px] font-medium transition num', !custom && d.target_words === p ? 'border-primary bg-primary-soft text-primary' : 'bg-surface hover:border-foreground/25')}>
                {wan(p)}
              </button>
            ))}
            <button type="button" onClick={() => setCustom(true)}
              className={cn('focus-ring h-10 rounded-lg border text-[13.5px] font-medium transition', custom ? 'border-primary bg-primary-soft text-primary' : 'bg-surface hover:border-foreground/25')}>
              自定义
            </button>
          </div>
          {custom && (
            <div className="mt-2 flex items-center gap-2">
              <Input type="number" inputMode="numeric" min={1} step={1} className="h-10 num" value={d.target_words ? d.target_words / 10000 : ''}
                onChange={(e) => set({ target_words: Math.round(Number(e.target.value) * 10000) })} aria-label="自定义字数目标（万字）" />
              <span className="shrink-0 text-[13px] text-muted-foreground">万字</span>
            </div>
          )}
        </Field>

        <div className="grid grid-cols-2 gap-3">
          <Field label="每章字数">
            <Input type="number" inputMode="numeric" min={500} max={20000} step={100} className="h-10 num" value={d.chapter_words || ''} onChange={(e) => set({ chapter_words: Number(e.target.value) })} />
          </Field>
          <Field label="每批章数">
            <Input type="number" inputMode="numeric" min={1} max={50} className="h-10 num" value={d.batch_size || ''} onChange={(e) => set({ batch_size: Number(e.target.value) })} />
          </Field>
        </div>

        <Field label="精修范围" hint="范围内的章写好后先停下等你审批">
          <Segmented block value={d.refine_scope} onChange={(v) => set({ refine_scope: v })} options={SCOPES} className="h-10" />
          <div className="mt-2.5">
            {d.refine_scope === 'first_n' && (
              <div className="flex items-center gap-2 text-[13px]">
                <span className="shrink-0 text-muted-foreground">前</span>
                <Input type="number" inputMode="numeric" min={0} max={5000} className="h-10 w-24 text-center num" value={d.golden_chapters} onChange={(e) => set({ golden_chapters: Math.max(0, Number(e.target.value)) })} aria-label="精修前几章" />
                <span className="shrink-0 text-muted-foreground">章精修（通常是黄金开篇）</span>
              </div>
            )}
            {d.refine_scope === 'all' && <p className="text-[12.5px] text-muted-foreground">每一章写完都停下等你审批，适合短篇或重点作品。</p>}
            {d.refine_scope === 'none' && <p className="text-[12.5px] text-muted-foreground">不设精修范围，审稿通过的章节自动提交。</p>}
            {d.refine_scope === 'custom' && (
              <>
                <RangeEditor value={d.refine_ranges} onChange={(v) => set({ refine_ranges: v })} />
                {refineCount > 0 && <p className="mt-2 text-[12px] text-muted-foreground">共 {refineCount} 章：{compactNums(mergeRanges(d.refine_ranges).flatMap(([a, b]) => Array.from({ length: Math.min(200, b - a + 1) }, (_, k) => a + k)), 5)}</p>}
              </>
            )}
          </div>
        </Field>

        <div className="divide-y rounded-xl hairline">
          <label className="flex min-h-[52px] cursor-pointer items-center justify-between gap-3 px-3.5 py-2.5">
            <span className="min-w-0"><span className="block text-[13.5px] font-medium">精修章待审批时暂停</span><span className="block text-[12px] text-muted-foreground">关掉后精修章写好也接着往下写，回头再审</span></span>
            <Switch checked={d.pause_on_unapproved_refine} onCheckedChange={(v) => set({ pause_on_unapproved_refine: v })} />
          </label>
          <label className="flex min-h-[52px] cursor-pointer items-center justify-between gap-3 px-3.5 py-2.5">
            <span className="min-w-0"><span className="block text-[13.5px] font-medium">自动连续</span><span className="block text-[12px] text-muted-foreground">一批写完自动接着下一批，直到写满或需要你处理</span></span>
            <Switch checked={d.auto_continue} onCheckedChange={(v) => set({ auto_continue: v })} />
          </label>
        </div>

        {errors.length > 0 && <p className="text-[12.5px] text-danger">{errors[0]}</p>}
        <Button variant="primary" className="h-10 w-full" disabled={!dirty || errors.length > 0} loading={save.isPending} onClick={submit}>{dirty ? '保存设置' : '已保存'}</Button>
      </CardBody>
    </Card>
  )
}
