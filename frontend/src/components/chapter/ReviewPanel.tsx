import { useState } from 'react'
import { CheckCircle2, CornerDownRight, RotateCw, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ScoreRing } from '@/components/ui/misc'
import { EmptyState } from '@/components/common/States'
import type { Review, ReviewIssue } from '@/lib/types'
import { cn } from '@/lib/utils'
import { RadarChart } from './RadarChart'

const DIMS: [keyof Review['scores'], string][] = [['hook', '追读钩子'], ['pacing', '节奏'], ['payoff', '爽点兑现'], ['character', '人物'], ['coherence', '连贯']]
const SEV = { high: { l: '严重', t: 'danger' }, mid: { l: '一般', t: 'warning' }, low: { l: '轻微', t: 'neutral' } } as const

export function ReviewPanel({ review, onQuote, onReview, reviewing, activeQuote }: {
  review: Review | null; onQuote: (q: string) => void; onReview: () => void; reviewing: boolean; activeQuote?: string
}) {
  const [sev, setSev] = useState<'all' | ReviewIssue['severity']>('all')
  if (!review) return (
    <EmptyState compact kind="chapter" className="border-0 bg-transparent" title="还没有审稿结果"
      action={<Button size="sm" variant="primary" loading={reviewing} onClick={onReview}>开始审稿</Button>} />
  )
  const issues = review.issues.filter((i) => sev === 'all' || i.severity === sev)
  return (
    <div className="space-y-5">
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
      <RadarChart size={232} data={DIMS.map(([k, l]) => ({ label: l, value: review.scores[k] ?? 0 }))} />
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
                <span className="text-xs font-medium text-muted-foreground">{i.dimension}</span>
              </div>
              {i.quote && <div className="mt-2 line-clamp-2 border-l-2 border-warning/60 pl-2 font-serif text-[12.5px] leading-relaxed text-foreground/80">{i.quote}</div>}
              <div className="mt-1.5 flex gap-1 text-[12.5px] leading-relaxed"><CornerDownRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />{i.comment}</div>
            </button>
          ))}
          {!issues.length && <p className="py-4 text-center text-xs text-muted-foreground">这一档没有意见</p>}
        </div>
      </div>
    </div>
  )
}
