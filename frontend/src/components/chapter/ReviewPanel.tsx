import { useEffect, useMemo, useState } from 'react'
import * as CB from '@radix-ui/react-checkbox'
import { ArrowRight, Check, CheckCircle2, CornerDownRight, Flag, RotateCcw, RotateCw, Scales, Wand2, Wrench, XCircle } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScoreRing } from '@/components/ui/misc'
import { EmptyState } from '@/components/common/States'
import type { PatchLogEntry, PreCommitFix, RereviewInfo, Review, ReviewIssue, ReviewPatch } from '@/lib/types'
import { cn, fmtDateTime } from '@/lib/utils'
import { RadarChart } from './RadarChart'

const DIMS: [keyof Review['scores'], string][] = [['hook', '追读钩子'], ['pacing', '节奏'], ['payoff', '爽点兑现'], ['character', '人物'], ['coherence', '连贯'], ['continuity', '连续性'], ['semantics', '语义'], ['retention', '追读欲']]
const DIM_LABEL: Record<string, string> = Object.fromEntries(DIMS.map(([k, l]) => [k, l]))
const SEV = { high: { l: '严重', t: 'danger' }, mid: { l: '一般', t: 'warning' }, low: { l: '轻微', t: 'neutral' } } as const

export function ReviewPanel({ review, onQuote, onReview, reviewing, activeQuote, onApplyPatches, applyingPatches, patchDisabled, onUndo, undoLabel, undoDisabled }: {
  review: Review | null; onQuote: (q: string) => void; onReview: () => void; reviewing: boolean; activeQuote?: string
  /** v0.9：应用勾选的审稿补丁 */
  onApplyPatches?: (indices: number[]) => void; applyingPatches?: boolean; patchDisabled?: string | false
  /** v0.9.4：提交前定点修改过正文时，指向已有的「撤回到上一版」 */
  onUndo?: () => void; undoLabel?: string; undoDisabled?: boolean
}) {
  const [sev, setSev] = useState<'all' | ReviewIssue['severity']>('all')
  if (!review) return (
    <EmptyState compact kind="chapter" className="border-0 bg-transparent" title="还没有审稿结果"
      action={<Button size="sm" variant="primary" loading={reviewing} onClick={onReview}>开始审稿</Button>} />
  )
  const issues = review.issues.filter((i) => sev === 'all' || i.severity === sev)
  return (
    <div className="space-y-5">
      {review.flagged && (
        <div role="alert" className="flex gap-2.5 rounded-lg bg-danger-soft px-3.5 py-3 ring-1 ring-danger/40">
          <Flag className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <div className="min-w-0">
            <div className="text-[13.5px] font-semibold text-danger">已标记：本章未自动提交</div>
            <p className="mt-0.5 break-words text-[12.5px] leading-relaxed text-foreground/85">{review.flag_reason || '补丁后复审仍有严重问题，需要人工处理'}</p>
          </div>
        </div>
      )}
      <div className="flex items-center gap-4">
        <ScoreRing value={review.scores.overall} size={64} stroke={6} label="总分" />
        <div className="min-w-0 flex-1">
          {review.passed
            ? <div className="flex items-center gap-1.5 text-[14px] font-semibold text-success"><CheckCircle2 className="h-4 w-4" />审稿通过</div>
            : <div className="flex items-center gap-1.5 text-[14px] font-semibold text-danger"><XCircle className="h-4 w-4" />未通过，建议修改</div>}
          <p className="mt-0.5 text-xs text-muted-foreground">{review.issues.length} 条意见 · 点击引文定位到正文</p>
        </div>
        <Button size="icon-sm" variant="ghost" onClick={onReview} disabled={reviewing} aria-label="重新审稿"><RotateCw className={cn('h-3.5 w-3.5', reviewing && 'animate-spin')} /></Button>
      </div>
      {review.rereview && <RereviewCard rr={review.rereview} />}
      {review.pre_commit_fix && <PreCommitFixCard fix={review.pre_commit_fix} issues={review.issues} onQuote={onQuote} onUndo={onUndo} undoLabel={undoLabel} undoDisabled={undoDisabled} />}
      {review.reader && (
        <div className="rounded-lg bg-subtle p-3 hairline">
          <div className="flex items-baseline gap-2">
            <span className="text-xs font-medium text-muted-foreground">番茄老读者</span>
            {review.reader.score != null && (
              <span className={cn('text-[15px] font-semibold', review.reader.score >= 7 ? 'text-success' : review.reader.score >= 6 ? 'text-warning' : 'text-danger')}>
                {review.reader.score}/10
              </span>
            )}
            <span className="text-[11px] text-muted-foreground">{review.reader.score != null && review.reader.score < 6 ? '大概率划走' : '会点下一章'}</span>
          </div>
          {review.reader.verdict && <p className="mt-1 text-[12.5px] leading-relaxed text-foreground/80">{review.reader.verdict}</p>}
        </div>
      )}
      {!!review.patches?.length && (
        <PatchList patches={review.patches} issues={review.issues} onQuote={onQuote} onApply={onApplyPatches} applying={!!applyingPatches} disabled={patchDisabled} />
      )}
      {!!review.patch_log?.length && <PatchLog log={review.patch_log} />}
      <RadarChart size={232} data={DIMS.filter(([k]) => review.scores[k] !== undefined).map(([k, l]) => ({ label: l, value: review.scores[k] ?? 0 }))} />
      <div>
        <div className="mb-2 flex items-center gap-1">
          {(['all', 'high', 'mid', 'low'] as const).map((s) => (
            <button key={s} onClick={() => setSev(s)} className={cn('h-6 rounded-full px-2.5 text-xs transition', sev === s ? 'bg-foreground text-background' : 'text-muted-foreground hover:bg-muted')}>
              {s === 'all' ? '全部' : SEV[s].l} <span className="opacity-60">{s === 'all' ? review.issues.length : review.issues.filter((i) => i.severity === s).length}</span>
            </button>
          ))}
        </div>
        <div className="space-y-2">
          {issues.map((i, k) => (
            <button key={k} onClick={() => onQuote(i.quote)} className={cn('w-full rounded-lg p-3 text-left transition hairline hover:bg-subtle', activeQuote === i.quote && 'bg-warning-soft/60 ring-1 ring-warning/40')}>
              <div className="flex items-center gap-1.5">
                <Badge tone={SEV[i.severity].t} className="h-5 text-[11px]">{SEV[i.severity].l}</Badge>
                <span className="text-xs font-medium text-muted-foreground">{DIM_LABEL[i.dimension] ?? i.dimension}</span>
                {i.source === 'lint:numeric' && <Badge tone="primary" className="h-5 text-[11px]">数值一致性{i.object ? ` · ${i.object}` : ''}</Badge>}
              </div>
              {i.quote && <div className="mt-2 line-clamp-2 border-l-2 border-warning/60 pl-2 font-serif text-[12.5px] leading-relaxed text-foreground/80">{i.quote}</div>}
              <div className="mt-1.5 flex gap-1 text-[12.5px] leading-relaxed"><CornerDownRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" /><span className="min-w-0 break-words">{i.comment}</span></div>
              {i.source === 'lint:numeric' && i.related && <NumericRelatedLine issue={i} />}
            </button>
          ))}
          {!issues.length && <p className="py-4 text-center text-xs text-muted-foreground">这一档没有意见</p>}
        </div>
      </div>
    </div>
  )
}

/** v0.9：审稿补丁：原句 → 改句，勾选后逐字替换进正文（旧正文进历史，可撤回） */
function PatchList({ patches, issues, onQuote, onApply, applying, disabled }: {
  patches: ReviewPatch[]; issues: ReviewIssue[]; onQuote: (q: string) => void; onApply?: (indices: number[]) => void; applying: boolean; disabled?: string | false
}) {
  const pending = useMemo(() => patches.filter((p) => !p.applied && !p.stale), [patches])
  const [sel, setSel] = useState<number[]>([])
  const key = patches.map((p) => `${p.index}:${p.applied ? 1 : 0}${p.stale ? 's' : ''}`).join(',')
  // 补丁变化（重新审稿 / 已应用）时清掉失效的勾选
  useEffect(() => { setSel((cur) => cur.filter((i) => pending.some((p) => p.index === i))) }, [key]) // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (i: number) => setSel((cur) => (cur.includes(i) ? cur.filter((x) => x !== i) : [...cur, i]))
  const allOn = pending.length > 0 && pending.every((p) => sel.includes(p.index))
  const n = sel.length
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-[13px] font-semibold">改稿补丁 <span className="num font-normal text-muted-foreground">{pending.length}/{patches.length} 待应用{patches.some((p) => p.stale && !p.applied) ? ` · ${patches.filter((p) => p.stale && !p.applied).length} 条已过期` : ''}</span></h4>
        {pending.length > 0 && onApply && (
          <button className="h-7 rounded-md px-2 text-[12px] text-primary hover:bg-primary-soft" onClick={() => setSel(allOn ? [] : pending.slice(0, 20).map((p) => p.index))}>
            {allOn ? '取消全选' : '全选未应用'}
          </button>
        )}
      </div>
      <div className="space-y-2">
        {patches.map((p) => {
          const sev = SEV[(p.severity as ReviewIssue['severity'])] ?? SEV.low
          const issue = p.issue_ref != null ? issues[p.issue_ref] : undefined
          const on = sel.includes(p.index)
          return (
            <div key={p.index} className={cn('rounded-lg p-3 transition hairline', p.applied ? 'bg-success-soft/30' : p.stale ? 'opacity-60' : on ? 'bg-primary-soft/40 ring-1 ring-primary/30' : '')}>
              <div className="flex items-start gap-2.5">
                {!p.applied && !p.stale && onApply ? (
                  <CB.Root checked={on} onCheckedChange={() => toggle(p.index)} disabled={!!disabled || (!on && n >= 20)} aria-label={`选择补丁 ${p.index + 1}`}
                    className="focus-ring mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-input bg-surface disabled:opacity-50 data-[state=checked]:border-primary data-[state=checked]:bg-primary">
                    <CB.Indicator><Check className="h-3.5 w-3.5 text-primary-foreground" strokeWidth={3} /></CB.Indicator>
                  </CB.Root>
                ) : p.applied ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" /> : null}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone={sev.t} className="h-5 text-[11px]">{sev.l}</Badge>
                    {issue && <span className="text-xs text-muted-foreground">{DIM_LABEL[issue.dimension] ?? issue.dimension}</span>}
                    {p.applied && <Badge tone="success" className="h-5 text-[11px]">已应用</Badge>}
                    {p.round === 1 && <Badge tone="primary" className="h-5 text-[11px]">复审补丁</Badge>}
                    {p.stale && !p.applied && <Badge tone="neutral" className="h-5 text-[11px]" title="补丁来自上一轮审稿，已过期，手动应用会被跳过">已过期</Badge>}
                  </div>
                  {p.reason && <p className="mt-1.5 text-[12.5px] leading-relaxed text-foreground/80">{p.reason}</p>}
                  <button type="button" onClick={() => onQuote(p.applied ? p.improved : p.original)} className="mt-2 block w-full space-y-1 text-left" title="点击定位到正文">
                    <p className={cn('rounded-md bg-danger-soft/50 px-2.5 py-1.5 font-serif text-[12.5px] leading-relaxed', p.applied ? 'text-foreground/45 line-through' : 'text-foreground/70 line-through decoration-danger/50')}>{p.original}</p>
                    <p className="rounded-md bg-success-soft/70 px-2.5 py-1.5 font-serif text-[12.5px] leading-relaxed">{p.improved}</p>
                  </button>
                </div>
              </div>
            </div>
          )
        })}
      </div>
      {onApply && pending.length > 0 && (
        <div className="sticky bottom-0 -mx-1 mt-2 bg-surface/95 px-1 py-2 backdrop-blur">
          <Button className="w-full" size="md" variant="primary" loading={applying} disabled={!n || !!disabled} icon={<Wand2 className="h-4 w-4" />} onClick={() => onApply(sel)}>
            {disabled ? disabled : n ? `应用所选补丁（${n}）` : '勾选要应用的补丁'}
          </Button>
          <p className="mt-1.5 text-center text-[11px] text-muted-foreground">逐字替换原句，匹配不到的会跳过；应用前的正文进历史，可撤回</p>
        </div>
      )}
    </div>
  )
}

function PatchLog({ log }: { log: PatchLogEntry[] }) {
  return (
    <div>
      <h4 className="mb-1.5 text-[13px] font-semibold">补丁记录</h4>
      <ul className="space-y-1">
        {[...log].reverse().map((e, i) => (
          <li key={i} className="rounded-md bg-subtle px-2.5 py-1.5 text-[12px] leading-relaxed">
            <div className="flex flex-wrap items-center gap-x-2">
              <span className="font-medium">{e.label}</span>
              <span className="num text-muted-foreground">{fmtDateTime(e.at)}</span>
              <span className="text-success">应用 {e.applied.length} 处</span>
              {!!e.skipped.length && <span className="text-warning">跳过 {e.skipped.length} 处</span>}
            </div>
            {!!e.skipped.length && <div className="mt-0.5 text-muted-foreground">{e.skipped.map((k) => `#${k.index + 1} ${k.reason}`).join('；')}</div>}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** v0.9.4：数值冲突的对照来源（前文原句 / 事实账本 / 设定卡） */
function NumericRelatedLine({ issue }: { issue: ReviewIssue }) {
  const rel = issue.related!
  const fromLedger = Boolean(rel.label || (rel.source && rel.source !== 'chapter'))
  return (
    <div className="mt-2 rounded-md bg-subtle px-2.5 py-1.5 text-[12px] leading-relaxed">
      <div className="flex flex-wrap items-center gap-x-1.5 text-muted-foreground">
        <Scales className="h-3.5 w-3.5 shrink-0" />
        <span>对照{fromLedger ? (rel.label || (rel.source === 'ledger' ? '事实账本' : rel.source)) : `本章前文${rel.paragraph != null ? `（第 ${rel.paragraph + 1} 段）` : ''}`}</span>
        {issue.position?.match && <span>· 这里写「<b className="font-medium text-foreground">{issue.position.match}</b>」</span>}
      </div>
      {fromLedger
        ? rel.value && <div className="mt-0.5 break-words font-serif text-foreground/85">{rel.value}</div>
        : rel.quote && <div className="mt-0.5 line-clamp-2 break-words border-l-2 border-primary/40 pl-2 font-serif text-foreground/80">{rel.quote}</div>}
    </div>
  )
}

/** v0.9.4：补丁后复审：首审 vs 复审总分 */
function RereviewCard({ rr }: { rr: RereviewInfo }) {
  const delta = Math.round((rr.after_overall - rr.before_overall) * 10) / 10
  return (
    <div className="rounded-lg p-3 hairline">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <h4 className="text-[13px] font-semibold">补丁后复审</h4>
        <span className="num text-[11px] text-muted-foreground">{fmtDateTime(rr.at)}</span>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <div className="flex-1 rounded-md bg-subtle px-2 py-1.5 text-center">
          <div className="text-[11px] text-muted-foreground">首审</div>
          <div className="num text-[17px] font-semibold">{rr.before_overall}</div>
        </div>
        <ArrowRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        <div className={cn('flex-1 rounded-md px-2 py-1.5 text-center', rr.passed ? 'bg-success-soft' : 'bg-danger-soft')}>
          <div className="text-[11px] text-muted-foreground">复审</div>
          <div className={cn('num text-[17px] font-semibold', rr.passed ? 'text-success' : 'text-danger')}>{rr.after_overall}</div>
        </div>
        <span className={cn('num w-12 shrink-0 text-right text-[12.5px] font-medium', delta > 0 ? 'text-success' : delta < 0 ? 'text-danger' : 'text-muted-foreground')}>{delta > 0 ? `+${delta}` : delta}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-muted-foreground">
        <span className={rr.passed ? 'text-success' : 'text-danger'}>{rr.passed ? '复审通过' : '复审未通过'}</span>
        <span>剩余严重问题 <b className={cn('num font-medium', rr.high_left ? 'text-danger' : 'text-foreground')}>{rr.high_left}</b></span>
        <span>已解决 <b className="num font-medium text-foreground">{rr.dropped_issues}</b> 条</span>
      </div>
    </div>
  )
}

/** v0.9.4：提交前定点修中等问题的记录；改过正文时可撤回（复用章节历史 /undo） */
function PreCommitFixCard({ fix, issues, onQuote, onUndo, undoLabel, undoDisabled }: {
  fix: PreCommitFix; issues: ReviewIssue[]; onQuote: (q: string) => void; onUndo?: () => void; undoLabel?: string; undoDisabled?: boolean
}) {
  const canUndo = fix.changed && !!onUndo && (!undoLabel || undoLabel.includes('提交前修中等问题'))
  const fixed = fix.issues.map((i) => issues[i]).filter(Boolean)
  return (
    <div className={cn('rounded-lg p-3 hairline', fix.changed && 'bg-primary-soft/30')}>
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <h4 className="flex items-center gap-1.5 text-[13px] font-semibold"><Wrench className="h-3.5 w-3.5 text-primary" />提交前定点修</h4>
        {fix.at && <span className="num text-[11px] text-muted-foreground">{fmtDateTime(fix.at)}</span>}
      </div>
      {fix.skipped ? (
        <p className="mt-1.5 text-[12.5px] leading-relaxed text-foreground/80">未改正文：{fix.skipped}</p>
      ) : (
        <>
          <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[12.5px]">
            <span>处理 <b className="num font-medium">{fix.issues.length}</b> 个一般问题</span>
            <span className="text-success">应用补丁 <b className="num font-medium">{fix.patches_applied.length}</b> 处</span>
            <span>改写原句 <b className="num font-medium">{fix.rewritten}</b> 句</span>
            {!!fix.patches_skipped.length && <span className="text-warning">跳过 <b className="num font-medium">{fix.patches_skipped.length}</b> 处</span>}
          </div>
          {!!fix.patches_skipped.length && <p className="mt-1 break-words text-[12px] text-muted-foreground">{fix.patches_skipped.map((k) => `#${k.index + 1} ${k.reason}`).join('；')}</p>}
          {!fix.changed && <p className="mt-1 text-[12px] text-muted-foreground">正文没有变化</p>}
          {!!fixed.length && (
            <ul className="mt-2 space-y-1">
              {fixed.slice(0, 4).map((i, k) => (
                <li key={k}><button type="button" onClick={() => onQuote(i.quote)} className="line-clamp-2 w-full break-words border-l-2 border-primary/40 pl-2 text-left text-[12px] leading-relaxed text-foreground/75 hover:text-foreground">{i.comment}</button></li>
              ))}
            </ul>
          )}
        </>
      )}
      {fix.changed && (
        canUndo ? (
          <button type="button" disabled={undoDisabled} onClick={onUndo} className="mt-2 inline-flex h-7 items-center gap-1 rounded-md px-2 text-[12px] font-medium text-primary hover:bg-primary-soft disabled:opacity-50">
            <RotateCcw className="h-3.5 w-3.5" />撤回到「提交前修中等问题前」
          </button>
        ) : <p className="mt-2 text-[11px] text-muted-foreground">修改前的正文已存进历史（标签「提交前修中等问题前」），可在工具栏「撤回」里恢复</p>
      )}
    </div>
  )
}
