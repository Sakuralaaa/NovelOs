import { useState } from 'react'
import { AlertTriangle, ArrowRight, FlagCheckered, ListTree, Target, Zap } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Sheet } from '@/components/ui/dialog'
import { JobInline } from '@/components/common/JobInline'
import { useKindJob } from '@/hooks/useKindJob'
import { wanbenApi } from '@/lib/api'
import { useJobs } from '@/lib/jobs'
import type { WanbenPlanDiff, WanbenPlanResult, WanbenPlanSummary, WanbenVolume } from '@/lib/types'
import { cn, fmtTime } from '@/lib/utils'

const FIELD_LABEL: Record<string, string> = { start: '起始章', end: '结束章', crisis: '本卷危机', climax_chapter: '高潮章', closure: '收束', finale: '结局', title: '卷名', summary: '概要' }
const ACTION: Record<WanbenPlanDiff['action'], { label: string; tone: 'success' | 'primary' | 'neutral' | 'danger' }> = {
  added: { label: '新增', tone: 'success' }, updated: { label: '调整', tone: 'primary' }, unchanged: { label: '不变', tone: 'neutral' }, removed: { label: '删除', tone: 'danger' },
}
const rng = (v?: Pick<WanbenVolume, 'start' | 'end'> | null) => (v?.start && v?.end ? `第${v.start}–${v.end}章` : '未定')

/** 卷纲倒推：规划按钮 + 卷列表（区间、危机、高潮章、收束，末卷结局）+ 规划后的差异 */
export function PlanCard({ bookId, plan, enabled, className }: { bookId: number; plan: WanbenPlanSummary; enabled: boolean; className?: string }) {
  const { start } = useJobs()
  const [diff, setDiffState] = useState<WanbenPlanResult | null>(null)
  const [open, setOpen] = useState(false)
  const setDiff = (r: WanbenPlanResult) => { setDiffState(r); setOpen(true) }
  const { active } = useKindJob(bookId, 'wanben_plan', `wanben-plan:${bookId}`, '完本规划', { onSuccess: (j) => j.result && setDiff(j.result as WanbenPlanResult) })
  const run = () => start(wanbenApi.plan(bookId), {
    key: `wanben-plan:${bookId}`, label: '完本规划', successMsg: '卷纲已按字数目标倒推好',
    onSuccess: (j) => { if (j.result) setDiff(j.result as WanbenPlanResult) },
  })
  const vols = plan.volumes ?? []

  return (
    <Card className={className}>
      <CardHeader icon={<ListTree />} title="卷纲倒推" desc={plan.planned ? `共 ${plan.total_chapters ?? '—'} 章 · ${vols.length} 卷${plan.planned_at ? ` · ${fmtTime(plan.planned_at)}规划` : ''}` : '按字数目标算总章数，分卷定危机与高潮'}
        action={<Button size="sm" variant={plan.planned ? 'secondary' : 'primary'} loading={!!active} disabled={!enabled} title={enabled ? undefined : '先开启完本模式'} onClick={() => void run()}>{plan.planned ? '重新规划' : '规划'}</Button>} />
      <CardBody className="space-y-3 p-4 sm:p-5">
        {active && <JobInline job={active} />}
        {!vols.length ? (
          <div className="rounded-xl border border-dashed px-4 py-8 text-center">
            <Target className="mx-auto h-7 w-7 text-primary/70" />
            <p className="mt-2 text-[13.5px] font-medium">还没有完本规划</p>
            <p className="mt-1 text-[12.5px] leading-relaxed text-muted-foreground">点「规划」：没有大纲会先生成大纲；已有大纲只补缺、按目标调整卷区间，并给出差异。</p>
          </div>
        ) : (
          <ol className="space-y-2.5">
            {vols.map((v, i) => <VolumeRow key={v.node_id} v={v} last={i === vols.length - 1} />)}
          </ol>
        )}
        {plan.ending && (
          <div className="rounded-xl bg-primary-soft/50 px-3.5 py-3 text-[13px] leading-relaxed">
            <div className="mb-0.5 flex items-center gap-1.5 text-[12px] font-medium text-primary"><FlagCheckered className="h-3.5 w-3.5" />全书结局</div>
            <p className="break-words">{plan.ending}</p>
          </div>
        )}
        {diff && !active && (
          <Button size="sm" variant="ghost" className="w-full" onClick={() => setOpen(true)}>查看最近一次规划差异</Button>
        )}
      </CardBody>
      <PlanDiffSheet result={open ? diff : null} onClose={() => setOpen(false)} />
    </Card>
  )
}

function VolumeRow({ v, last }: { v: WanbenVolume; last: boolean }) {
  const [open, setOpen] = useState(last)
  return (
    <li className={cn('rounded-xl bg-surface hairline', last && 'ring-1 ring-primary/25')}>
      <button type="button" onClick={() => setOpen((x) => !x)} className="focus-ring flex min-h-[48px] w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-left">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted text-[12px] font-semibold num">{v.order}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13.5px] font-semibold">{v.title || `第${v.order}卷`}</span>
          <span className="num block text-[12px] text-muted-foreground">{rng(v)}{v.climax_chapter ? ` · 高潮第${v.climax_chapter}章` : ''}</span>
        </span>
        {last && <Badge tone="primary">末卷</Badge>}
      </button>
      {open && (
        <div className="space-y-2 border-t px-3.5 py-3 text-[12.5px] leading-relaxed">
          {v.crisis && <p><span className="mr-1.5 font-medium text-danger">危机</span>{v.crisis}</p>}
          {v.climax_chapter && <p><span className="mr-1.5 font-medium text-warning">高潮</span>第{v.climax_chapter}章正面爆发</p>}
          {v.closure && <p><span className="mr-1.5 font-medium text-success">收束</span>{v.closure}</p>}
          {v.finale && (
            <div className="rounded-lg bg-subtle px-3 py-2.5">
              <div className="mb-1 flex items-center gap-1.5 font-medium"><FlagCheckered className="h-3.5 w-3.5 text-primary" />结局安排{v.finale.last_chapter ? `（第${v.finale.last_chapter}章完结）` : ''}</div>
              {v.finale.resolution && <p>主线了结：{v.finale.resolution}</p>}
              {!!v.finale.payoffs?.length && <p className="mt-1">伏笔回收：{v.finale.payoffs.join('；')}</p>}
              {!!v.finale.endings?.length && <p className="mt-1">人物归宿：{v.finale.endings.join('；')}</p>}
              {v.finale.last_chapter_beat && <p className="mt-1 text-muted-foreground">{v.finale.last_chapter_beat}</p>}
            </div>
          )}
        </div>
      )}
    </li>
  )
}

function PlanDiffSheet({ result, onClose }: { result: WanbenPlanResult | null; onClose: () => void }) {
  const r = result
  return (
    <Sheet open={!!r} onOpenChange={(o) => !o && onClose()} width={640} title="规划差异" desc={r ? `总章数：${r.total_chapters.before ?? '未规划'} → ${r.total_chapters.after} 章（每章约 ${r.chapter_words} 字）` : undefined}
      footer={<Button variant="primary" onClick={onClose}>知道了</Button>}>
      {r && (
        <div className="space-y-3">
          {r.warnings.map((w, i) => <p key={i} className="flex gap-2 rounded-lg bg-warning-soft px-3 py-2 text-[12.5px] text-warning"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{w}</p>)}
          {r.diff.map((d) => {
            const a = ACTION[d.action]
            return (
              <div key={`${d.action}-${d.node_id}-${d.order}`} className={cn('rounded-xl p-3.5 hairline', d.action === 'removed' ? 'bg-danger-soft/40' : 'bg-surface')}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13.5px] font-semibold">第{d.order}卷 {(d.after ?? d.before)?.title}</span>
                  <Badge tone={a.tone}>{a.label}</Badge>
                  {d.changed?.length ? <span className="text-[12px] text-muted-foreground">改了：{d.changed.map((k) => FIELD_LABEL[k] ?? k).join('、')}</span> : null}
                </div>
                <div className="num mt-1.5 flex flex-wrap items-center gap-1.5 text-[12.5px]">
                  {d.before && <span className={cn(d.action !== 'unchanged' && 'text-muted-foreground line-through decoration-danger/40')}>{rng(d.before)}</span>}
                  {d.before && d.after && d.action !== 'unchanged' && <ArrowRight className="h-3 w-3 text-muted-foreground" />}
                  {d.after && d.action !== 'unchanged' && <span className="font-medium">{rng(d.after)}</span>}
                </div>
                {d.after && d.action !== 'unchanged' && (
                  <div className="mt-2 space-y-1 text-[12.5px] leading-relaxed text-foreground/85">
                    {d.after.crisis && <p><span className="mr-1 text-danger">危机</span>{d.after.crisis}</p>}
                    {d.after.climax_chapter && <p><Zap className="mr-1 inline h-3 w-3 text-warning" />高潮第{d.after.climax_chapter}章</p>}
                    {d.after.closure && <p><span className="mr-1 text-success">收束</span>{d.after.closure}</p>}
                    {d.after.finale?.resolution && <p><span className="mr-1 text-primary">结局</span>{d.after.finale.resolution}</p>}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}
    </Sheet>
  )
}
