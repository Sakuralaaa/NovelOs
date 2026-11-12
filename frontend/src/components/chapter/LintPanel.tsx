import { AlertTriangle, Highlighter, Sparkles, Wand2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Tip } from '@/components/ui/tooltip'
import type { Lint } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Gauge } from './RadarChart'

export interface LocalStats { avg_sentence_len: number; short_sentence_ratio: number; bare_dialogue_ratio: number; summary_ratio: number; dialogue_ratio: number; bareCount: number; summaryCount: number }

interface MetricDef { key: 'avg_sentence_len' | 'short_sentence_ratio' | 'bare_dialogue_ratio' | 'summary_ratio'; label: string; unit: '字' | '%'; lo: number; hi: number; max: number; tip: string; low?: string; high: string }
const METRICS: MetricDef[] = [
  { key: 'avg_sentence_len', label: '平均句长', unit: '字', lo: 12, hi: 24, max: 40, tip: '一句话平均多少字。太短像电报、像提纲；太长读着累。', low: '句子偏短，节奏发碎，试着把动作和感受连成一句。', high: '句子偏长，手机上读着累，可以在转折处断开。' },
  { key: 'short_sentence_ratio', label: '短句占比', unit: '%', lo: 15, hi: 35, max: 80, tip: '8 字以内的句子占多少。适量短句有力量，太多就是典型 AI 腔。', low: '几乎没有短句，紧张处可以用短句收一下。', high: '短句太多，读起来一顿一顿的，像 AI 在列要点。' },
  { key: 'bare_dialogue_ratio', label: '裸对白占比', unit: '%', lo: 0, hi: 30, max: 100, tip: '对白前后没有任何动作、神态、环境描写的比例。太高就像在读剧本。', high: '很多对白“光秃秃”的，给说话的人加个动作或表情。' },
  { key: 'summary_ratio', label: '概述占比', unit: '%', lo: 0, hi: 10, max: 40, tip: '“于是几天后一切都好了”这类概述式叙述。读者想看场景，不想看总结。', high: '概述偏多，像说明书。挑一处改成具体的场景和对话。' },
]

function norm(v: number, unit: MetricDef['unit']) { return unit === '%' ? (v <= 1 ? v * 100 : v) : v }

export function LintPanel({ lint, local, showBare, showSummary, onToggleBare, onToggleSummary, onHumanize, onThicken, busy, thickening, humanizing }: {
  lint: Lint | null; local: LocalStats; showBare: boolean; showSummary: boolean; onToggleBare: (v: boolean) => void; onToggleSummary: (v: boolean) => void
  onHumanize: () => void; onThicken: () => void; busy: boolean; thickening: boolean; humanizing: boolean
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl bg-subtle p-4">
        <Gauge value={lint?.ai_score ?? 0} label={lint ? 'AI 味（越低越好）' : '尚未检测'} invert />
        <div className="mt-3">
          <div className="mb-1 flex justify-between text-[11.5px] text-muted-foreground">
            <span>叙述 {Math.round((1 - (lint?.dialogue_ratio ?? local.dialogue_ratio)) * 100)}%</span>
            <span>对话占比 {Math.round((lint?.dialogue_ratio ?? local.dialogue_ratio) * 100)}%</span>
          </div>
          <div className="flex h-2 overflow-hidden rounded-full"><div className="bg-primary/55" style={{ width: `${(1 - (lint?.dialogue_ratio ?? local.dialogue_ratio)) * 100}%` }} /><div className="flex-1 bg-amber-400/80" /></div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <Tip content="只改写干巴巴的对白和概述段落：补动作、神态、环境、心理，情节不变。完成后可逐段对比、接受或撤销。">
          <Button variant="primary" size="sm" loading={thickening} disabled={busy && !thickening} icon={<Sparkles className="h-3.5 w-3.5" />} onClick={onThicken}>描写增厚</Button>
        </Tip>
        <Tip content="定点重写 AI 腔片段（口癖、禁用词、重复句式），每章 2–5 处。">
          <Button size="sm" loading={humanizing} disabled={busy && !humanizing} icon={<Wand2 className="h-3.5 w-3.5" />} onClick={onHumanize}>人味修整</Button>
        </Tip>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-[13px] font-semibold">文字健康度</h4>
          <span className="text-[11px] text-muted-foreground">{lint?.avg_sentence_len !== undefined ? '上次检测' : '实时估算'}</span>
        </div>
        <div className="space-y-2.5">
          {METRICS.map((m) => {
            const raw = (lint?.[m.key] as number | undefined) ?? local[m.key]
            const v = norm(raw, m.unit)
            const state = v < m.lo ? 'low' : v > m.hi ? 'high' : 'ok'
            const pos = (x: number) => `${Math.min(100, (x / m.max) * 100)}%`
            const hl = m.key === 'bare_dialogue_ratio' ? { on: showBare, set: onToggleBare, n: local.bareCount, c: 'bg-amber-400' } : m.key === 'summary_ratio' ? { on: showSummary, set: onToggleSummary, n: local.summaryCount, c: 'bg-sky-400' } : null
            return (
              <div key={m.key} className="rounded-lg p-3 hairline">
                <div className="flex items-center justify-between gap-2">
                  <Tip content={m.tip}><span className="cursor-help text-[13px] font-medium underline decoration-dotted decoration-muted-foreground/50 underline-offset-4">{m.label}</span></Tip>
                  <div className="flex items-center gap-2">
                    <span className="num text-[15px] font-semibold">{m.unit === '%' ? `${Math.round(v)}%` : `${v.toFixed(1)} 字`}</span>
                    <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', state === 'ok' ? 'bg-success-soft text-success' : 'bg-warning-soft text-warning')}>{state === 'ok' ? '健康' : state === 'high' ? '偏高' : '偏低'}</span>
                  </div>
                </div>
                <div className="relative mt-2.5 h-1.5 rounded-full bg-muted">
                  <div className="absolute inset-y-0 rounded-full bg-success/30" style={{ left: pos(m.lo), width: `calc(${pos(m.hi)} - ${pos(m.lo)})` }} />
                  <div className={cn('absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface shadow', state === 'ok' ? 'bg-success' : 'bg-warning')} style={{ left: pos(v) }} />
                </div>
                <div className="mt-1.5 flex justify-between text-[11px] text-muted-foreground">
                  <span>健康区间 {m.lo}–{m.hi}{m.unit === '%' ? '%' : ' 字'}</span>
                </div>
                {state !== 'ok' && <p className="mt-1.5 text-[12px] leading-relaxed text-foreground/75">{state === 'high' ? m.high : m.low}</p>}
                {hl && (
                  <label className="mt-2 flex cursor-pointer items-center justify-between gap-2 rounded-md bg-subtle px-2.5 py-1.5 text-[12px]">
                    <span className="flex items-center gap-1.5"><Highlighter className="h-3.5 w-3.5 text-muted-foreground" />在正文中标出 <span className={cn('inline-block h-2 w-2 rounded-sm', hl.c)} /> <span className="num text-muted-foreground">{hl.n} 段</span></span>
                    <Switch checked={hl.on} onCheckedChange={hl.set} />
                  </label>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {lint && lint.warnings.length > 0 && (
        <div className="space-y-1.5">
          <h4 className="text-[13px] font-semibold">提醒</h4>
          {lint.warnings.map((w, i) => <div key={i} className="flex gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] leading-relaxed text-foreground/85"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />{w}</div>)}
        </div>
      )}
      {lint && lint.repeated_ngrams.length > 0 && (
        <div>
          <h4 className="mb-2 text-[13px] font-semibold">重复片段</h4>
          <div className="space-y-1">{lint.repeated_ngrams.slice(0, 8).map((r) => <div key={r.text} className="flex items-center justify-between rounded-md px-2 py-1 text-[12.5px] hover:bg-subtle"><span className="font-serif">“{r.text}”</span><span className="num text-muted-foreground">×{r.count}</span></div>)}</div>
        </div>
      )}
      {lint && (
        <div>
          <h4 className="mb-2 text-[13px] font-semibold">禁用词命中</h4>
          {lint.banned_hits.length ? <div className="flex flex-wrap gap-1.5">{lint.banned_hits.map((b) => <span key={b.word} className="inline-flex items-center gap-1 rounded-md bg-danger-soft px-2 py-0.5 text-[12px] text-danger">{b.word}<span className="num opacity-70">×{b.count}</span></span>)}</div> : <p className="text-xs text-success">没有命中禁用词 👍</p>}
        </div>
      )}
    </div>
  )
}
