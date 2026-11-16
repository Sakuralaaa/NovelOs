import { useEffect, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Check, FilmSlate, Lightbulb, X } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { SevBadge } from '@/components/wanben/bits'
import { checkApi } from '@/lib/api'
import type { DuanjuCheck } from '@/lib/types'
import { cn } from '@/lib/utils'

const ISSUE_LABEL: Record<string, string> = { opening_slow: '开场慢', monologue: '心理独白偏多', scenery: '景物描写偏多', ending_flat: '章末没卡点' }
/** 本次会话内的自查结果（切换标签/章节回来还在） */
const CACHE = new Map<number, DuanjuCheck>()
const pct = (v: number) => `${Math.round(v * 100)}%`

/** 短剧分镜档单章自查（同步、纯规则，查的是已保存的正文） */
export function DuanjuPanel({ chapterId, unsaved, onLocate }: { chapterId: number; unsaved?: boolean; onLocate?: (q: string) => void }) {
  const [r, setR] = useState<DuanjuCheck | null>(() => CACHE.get(chapterId) ?? null)
  useEffect(() => setR(CACHE.get(chapterId) ?? null), [chapterId])
  const m = useMutation({
    mutationFn: () => checkApi.duanjuCheck(chapterId),
    meta: { errorTitle: '短剧自查失败' },
    onSuccess: (x) => { CACHE.set(chapterId, x); setR(x) },
  })
  const rows: { label: string; ok: boolean; value: string; hint: string }[] = r ? [
    { label: '开场切入', ok: r.opening_ok, value: r.opening_has_dialogue && r.opening_has_action ? '对白 + 动作' : r.opening_has_dialogue ? '强对白' : r.opening_has_action ? '动作' : '没有', hint: '前 100 字有对白或动作' },
    { label: '心理独白', ok: r.monologue_ratio <= 0.12, value: pct(r.monologue_ratio), hint: '≤ 12%' },
    { label: '景物描写', ok: r.scenery_ratio <= 0.08, value: pct(r.scenery_ratio), hint: '≤ 8%' },
    { label: '对白占比', ok: r.dialogue_ratio >= 0.3, value: pct(r.dialogue_ratio), hint: '参考 ≥ 30%' },
    { label: '章末卡点', ok: r.ending_cliff, value: r.ending_cliff ? '有' : '没有', hint: '停在危机 / 揭露前一刻' },
  ] : []
  return (
    <div className="space-y-3">
      <div className="flex items-start gap-2.5 rounded-xl bg-subtle/70 p-3 hairline">
        <FilmSlate className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1 text-[12.5px] leading-relaxed text-muted-foreground">按竖屏短剧分镜的要求查这一章：开场、独白、景物、对白、章末卡点。不调模型，秒出。</div>
      </div>
      <Button variant={r ? 'secondary' : 'primary'} className="w-full" loading={m.isPending} icon={<FilmSlate className="h-4 w-4" />} onClick={() => m.mutate()}>{r ? '重新自查' : '短剧自查'}</Button>
      {unsaved && <p className="text-[12px] text-warning">正文有未保存的修改，自查用的是上次保存的版本</p>}
      {r && (
        <>
          <div className="divide-y rounded-xl bg-surface hairline">
            {rows.map((x) => (
              <div key={x.label} className="flex items-center gap-2.5 px-3 py-2.5">
                <span className={cn('flex h-5 w-5 shrink-0 items-center justify-center rounded-full', x.ok ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger')}>{x.ok ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}</span>
                <span className="min-w-0 flex-1"><span className="block text-[13px] font-medium">{x.label}</span><span className="block text-[11.5px] text-muted-foreground">{x.hint}</span></span>
                <span className="num shrink-0 text-[13px] font-semibold">{x.value}</span>
              </div>
            ))}
          </div>
          {r.issues.length === 0 ? <p className="py-2 text-center text-[13px] font-medium text-success">这一章符合短剧分镜的节奏</p> : (
            <div className="space-y-2">
              {r.issues.map((i, k) => (
                <div key={k} className="rounded-xl bg-surface p-3 hairline">
                  <div className="flex items-center gap-1.5"><SevBadge s={i.severity} /><span className="text-[13px] font-semibold">{ISSUE_LABEL[i.type] ?? i.type}</span></div>
                  {i.evidence && (
                    <button type="button" disabled={!onLocate || /占约/.test(i.evidence)} onClick={() => onLocate?.(i.evidence.replace(/…$/, ''))}
                      className="mt-1.5 block w-full break-words rounded-md border-l-2 border-border py-1 pl-2.5 text-left font-serif text-[12.5px] leading-relaxed text-foreground/75 enabled:hover:bg-muted/60">{i.evidence}</button>
                  )}
                  <p className="mt-1.5 flex gap-1.5 text-[12.5px] leading-relaxed"><Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" /><span className="min-w-0 break-words">{i.suggestion}</span></p>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
