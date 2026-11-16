import { AlertTriangle, Highlighter, Scales, Sparkles, Wand2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Tip } from '@/components/ui/tooltip'
import type { Lint } from '@/lib/types'
import { cn, platformLabel } from '@/lib/utils'
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

      {lint && <LongParaSection lint={lint} />}
      {lint && <NumericSection lint={lint} />}

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
      {lint && <CraftSection lint={lint} />}
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

/** v0.6：重复强化词 / 陈词比喻 / 量词搭配 / 群众镜头 / 口头禅。点“人味修整”会逐句定点修这些问题。 */
function CraftSection({ lint }: { lint: Lint }) {
  const intens = (lint.intensifiers ?? []).filter((d) => d.over)
  const cliches = lint.cliche_similes ?? []
  const measures = lint.measure_errors ?? []
  const tics = [...(lint.dialogue_tics ?? []).filter((d) => d.over).map((d) => ({ label: `「${d.word}」`, count: d.count })),
    ...(lint.catchphrases ?? []).filter((d) => d.over).map((d) => ({ label: `${d.who}「${d.word}」`, count: d.count }))]
  const crowd = lint.crowd_shots ?? 0
  if (lint.intensifiers === undefined) return null
  const empty = !intens.length && !cliches.length && !measures.length && !tics.length && crowd <= 3
  const chip = 'inline-flex items-center gap-1 rounded-md bg-warning-soft px-2 py-0.5 text-[12px] text-foreground/85'
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-[13px] font-semibold">重复与搭配</h4>
        {!!lint.fix_targets?.length && <Tip content="点“人味修整”会只改这些被点名的句子"><span className="cursor-help text-[11px] text-muted-foreground">{lint.fix_targets.length} 处可定点修</span></Tip>}
      </div>
      {empty ? <p className="text-xs text-success">强化词、比喻、量词、口头禅都在正常范围 👍</p> : (
        <div className="space-y-2 text-[12.5px]">
          {intens.length > 0 && <div><div className="mb-1 text-[11.5px] text-muted-foreground">重复强化词（每词上限 {intens[0].allow} 次）</div><div className="flex flex-wrap gap-1.5">{intens.map((d) => <span key={d.word} className={chip}>{d.word}<span className="num opacity-70">×{d.count}</span></span>)}</div></div>}
          {cliches.length > 0 && <div><div className="mb-1 text-[11.5px] text-muted-foreground">陈词比喻</div><div className="flex flex-wrap gap-1.5">{cliches.map((d) => <span key={d.word} className={chip}>{d.word}<span className="num opacity-70">×{d.count}</span></span>)}</div></div>}
          {tics.length > 0 && <div><div className="mb-1 text-[11.5px] text-muted-foreground">口头禅超频（每章 1–2 次）</div><div className="flex flex-wrap gap-1.5">{tics.map((d) => <span key={d.label} className={chip}>{d.label}<span className="num opacity-70">×{d.count}</span></span>)}</div></div>}
          {measures.map((m, i) => <div key={i} className="rounded-md bg-danger-soft px-2.5 py-1.5 text-foreground/85">量词：「{m.match}」— {m.hint}</div>)}
          {crowd > 3 && <div className="rounded-md bg-subtle px-2.5 py-1.5 text-foreground/85">群众/配角反应镜头 <span className="num">{crowd}</span> 处，建议不超过 3 处</div>}
        </div>
      )}
    </div>
  )
}


/** v0.9：平台档与超长段落（番茄档 >70 字算长段，人味修整会定点拆段） */
function LongParaSection({ lint }: { lint: Lint }) {
  if (lint.platform === undefined && lint.long_paragraphs === undefined) return null
  const n = lint.long_paragraphs ?? 0
  const quotes = (lint.fix_targets ?? []).filter((t) => t.kind === '长段')
  const fanqie = lint.lint_tier ? lint.lint_tier === 'fanqie' : (lint.platform ?? 'fanqie') === 'fanqie'
  // v0.9.4 起番茄档长段阈值改为 >100 字（带 lint_tier 的结果）
  const lim = lint.lint_tier ? 100 : 70
  return (
    <div className={cn('rounded-lg p-3 hairline', n > 0 && 'bg-warning-soft/40')}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[13px] font-medium">长段落</span>
        <span className="flex items-center gap-1.5">
          <span className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{lint.lint_tier ? `${lint.lint_tier === 'fanqie' ? '番茄' : '出版'}档阈值` : `按${platformLabel(lint.platform)}档检查`}</span>
          {fanqie && <span className={cn('rounded px-1.5 py-0.5 text-[11px] font-medium', n ? 'bg-warning-soft text-warning' : 'bg-success-soft text-success')}>{n ? `${n} 段` : '健康'}</span>}
        </span>
      </div>
      <p className="mt-1.5 text-[12px] leading-relaxed text-foreground/75">
        {!fanqie ? '这一档不查长段。' : n ? `超过 ${lim} 字的段落在手机上读着累，读者容易划走。${lint.lint_tier ? '长段 ≥3 段且占比 ≥10% 才算问题；' : ''}点「人味修整」会把点名的长段拆开。` : `没有超过 ${lim} 字的段落。`}
      </p>
      {quotes.length > 0 && (
        <ul className="mt-2 space-y-1">
          {quotes.slice(0, 3).map((q, i) => (
            <li key={i} className="line-clamp-2 border-l-2 border-warning/60 pl-2 font-serif text-[12px] leading-relaxed text-foreground/70"><span className="num mr-1 font-sans text-warning">{q.word}</span>{q.quote}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

const NUM_KIND: Record<string, string> = { weight: '重量', height: '身高/高度', length: '长度', width: '宽度', thick: '厚度', depth: '深度', range: '距离', power: '功率', speed: '速度', age: '年龄', days: '期限', realm: '境界' }

/** v0.9.4：数值一致性冲突（年龄、身高、境界、期限…与前文 / 账本 / 设定卡对不上） */
function NumericSection({ lint }: { lint: Lint }) {
  const list = lint.numeric_conflicts
  if (list === undefined) return null
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-1.5 text-[13px] font-semibold"><Scales className="h-3.5 w-3.5 text-muted-foreground" />数值一致性</h4>
        {!!list.length && <span className="rounded bg-warning-soft px-1.5 py-0.5 text-[11px] font-medium text-warning">{list.length} 处冲突</span>}
      </div>
      {!list.length ? <p className="text-xs text-success">年龄、身高、境界、期限等数值和前文一致 👍</p> : (
        <div className="space-y-2">
          {list.map((i, k) => {
            const rel = i.related
            const ledger = !!(rel && (rel.label || (rel.source && rel.source !== 'chapter')))
            return (
              <div key={k} className="rounded-lg p-3 text-[12.5px] hairline">
                <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-muted-foreground">
                  {i.object && <span className="font-medium text-foreground">{i.object}</span>}
                  {i.kind && <span className="rounded bg-muted px-1.5 py-0.5">{NUM_KIND[i.kind] ?? i.kind}</span>}
                  {i.position?.paragraph != null && <span>第 {i.position.paragraph + 1} 段</span>}
                </div>
                {i.quote && <div className="mt-1.5 line-clamp-2 break-words border-l-2 border-warning/60 pl-2 font-serif leading-relaxed text-foreground/80">{i.quote}</div>}
                {rel && (ledger
                  ? <div className="mt-1.5 break-words rounded-md bg-subtle px-2.5 py-1.5 text-[12px]"><span className="text-muted-foreground">对照 {rel.label || '事实账本'}：</span><span className="font-serif">{rel.value}</span></div>
                  : rel.quote ? <div className="mt-1.5 break-words rounded-md bg-subtle px-2.5 py-1.5 text-[12px]"><span className="text-muted-foreground">对照前文{rel.paragraph != null ? `（第 ${rel.paragraph + 1} 段）` : ''}：</span><span className="font-serif">{rel.quote}</span></div> : null)}
                <p className="mt-1.5 break-words leading-relaxed text-foreground/85">{i.comment}</p>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
