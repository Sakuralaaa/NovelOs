import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Lightbulb, Radar, RefreshCw, Scales, Sparkles } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/misc'
import { JobInline } from '@/components/common/JobInline'
import { checkApi } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { HomoReport, HomoSimilar } from '@/lib/types'
import { cn, fmtNum, fmtTime } from '@/lib/utils'

const LEVEL: Record<HomoReport['level'], { label: string; tone: 'danger' | 'warning' | 'success' | 'neutral'; desc: string }> = {
  high: { label: '撞车风险高', tone: 'danger', desc: '和榜单前列有书高度相似，建议换掉重合的卖点或书名' },
  mid: { label: '有明显重合', tone: 'warning', desc: '套路或简介有重合，给它加一个别人没有的限制或场景' },
  low: { label: '差异化不错', tone: 'success', desc: '和当前榜单前列重合不多' },
  unknown: { label: '没有榜单数据', tone: 'neutral', desc: '先在热点雷达里刷新一次榜单' },
}

/** 同质化自查按钮：打开抽屉，自动跑一次规则比对（同步），可再让模型给差异化建议（任务） */
export function HomogeneityButton({ target, id, size = 'md', className }: { target: 'book' | 'idea'; id: number; size?: 'sm' | 'md'; className?: string }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size={size} className={className} icon={<Scales className="h-4 w-4" />} onClick={() => setOpen(true)}>同质化自查</Button>
      <Sheet open={open} onOpenChange={setOpen} width={680} title="同质化自查" desc={target === 'book' ? '这本书和当前榜单前列的相似书' : '这个选题和当前榜单前列的相似书'}>
        {open && <HomogeneityPanel target={target} id={id} />}
      </Sheet>
    </>
  )
}

export function HomogeneityPanel({ target, id, className }: { target: 'book' | 'idea'; id: number; className?: string }) {
  const { start } = useJobs()
  const key = `homo:${target}:${id}`
  const job = useActiveJob(key)
  const [rep, setRep] = useState<HomoReport | null>(null)
  const sync = useMutation({
    mutationFn: () => checkApi.homogeneity(target, id, false),
    meta: { errorTitle: '同质化自查失败' },
    onSuccess: (r) => { if (r.mode === 'sync') setRep(r.report) },
  })
  useEffect(() => { sync.mutate() }, [target, id]) // eslint-disable-line react-hooks/exhaustive-deps
  const deep = () => start(checkApi.homogeneity(target, id, true).then((r) => {
    if (r.mode === 'job') return r.job
    setRep(r.report)
    throw new Error('后端直接返回了结果')
  }), { key, label: '同质化自查', successMsg: '差异化建议已生成', onSuccess: (j) => j.result && setRep(j.result as HomoReport) })

  if (!rep) return <div className={cn('space-y-3', className)}><Skeleton className="h-20 rounded-xl" /><Skeleton className="h-40 rounded-xl" /></div>
  const lv = LEVEL[rep.level] ?? LEVEL.unknown
  return (
    <div className={cn('space-y-4', className)}>
      <div className={cn('rounded-xl p-4 hairline', lv.tone === 'danger' ? 'bg-danger-soft/60' : lv.tone === 'warning' ? 'bg-warning-soft/60' : lv.tone === 'success' ? 'bg-success-soft/60' : 'bg-subtle')}>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={lv.tone} dot>{lv.label}</Badge>
          {rep.similar.length > 0 && <span className="num text-[12.5px] text-muted-foreground">最高相似度 {rep.max_score}</span>}
          <span className="ml-auto flex gap-1.5">
            <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={sync.isPending} onClick={() => sync.mutate()}>重查</Button>
            {rep.similar.length > 0 && <Button size="sm" variant="soft" icon={<Sparkles className="h-3.5 w-3.5" />} loading={!!job} onClick={() => void deep()}>差异化建议</Button>}
          </span>
        </div>
        <p className="mt-1.5 text-[12.5px] text-foreground/80">{lv.desc}</p>
        {rep.snapshot && <p className="num mt-1 text-[11.5px] text-muted-foreground">比对了榜单前 {rep.snapshot.top_n} 名中的 {rep.snapshot.items_compared} 本 · 榜单 {fmtTime(rep.snapshot.taken_at)}</p>}
        {!rep.snapshot && <Link to="/radar" className="mt-2 inline-flex h-9 items-center gap-1 text-[13px] text-primary hover:underline"><Radar className="h-3.5 w-3.5" />去热点雷达刷新榜单</Link>}
      </div>
      {job && <JobInline job={job} />}

      {rep.llm && (rep.llm.overall || rep.llm.suggestions.length > 0) && (
        <div className="rounded-xl bg-primary-soft/40 p-4 hairline">
          <div className="mb-1.5 flex items-center gap-1.5 text-[13px] font-semibold text-primary"><Sparkles className="h-3.5 w-3.5" />模型的差异化建议</div>
          {rep.llm.overall && <p className="text-[13px] leading-relaxed">{rep.llm.overall}</p>}
          <ul className="mt-2 space-y-1.5">{rep.llm.suggestions.map((x, i) => <li key={i} className="flex gap-2 text-[13px] leading-relaxed"><span className="num shrink-0 text-primary">{i + 1}.</span><span className="min-w-0 break-words">{x}</span></li>)}</ul>
        </div>
      )}
      {rep.suggestions.length > 0 && (
        <div className="space-y-1.5">
          {rep.suggestions.map((x, i) => <p key={i} className="flex gap-2 rounded-lg bg-subtle px-3 py-2 text-[12.5px] leading-relaxed"><Lightbulb className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" /><span className="min-w-0 break-words">{x}</span></p>)}
        </div>
      )}
      {rep.similar.length > 0 && (
        <div>
          <div className="mb-2 text-[12.5px] font-medium text-muted-foreground">相似书 {rep.similar.length} 本</div>
          <div className="space-y-2.5">{rep.similar.map((s) => <SimilarCard key={s.rank_item_id} s={s} />)}</div>
        </div>
      )}
    </div>
  )
}

function SimilarCard({ s }: { s: HomoSimilar }) {
  const tone = s.score >= 60 ? 'bg-danger' : s.score >= 35 ? 'bg-warning' : 'bg-primary/60'
  return (
    <div className="rounded-xl bg-surface p-3.5 hairline">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="truncate text-[14px] font-semibold">《{s.title}》</div>
          <div className="num mt-0.5 truncate text-[12px] text-muted-foreground">{s.author || '佚名'} · {s.category} · {s.board === 'new' ? '新书榜' : '阅读榜'}第 {s.rank} · {fmtNum(s.read_count)} 在读</div>
        </div>
        <div className="w-16 shrink-0 text-right">
          <div className="num text-[16px] font-semibold leading-none">{s.score}</div>
          <div className="mt-1.5 h-1 rounded-full bg-muted"><div className={cn('h-full rounded-full', tone)} style={{ width: `${Math.min(100, s.score)}%` }} /></div>
        </div>
      </div>
      {s.overlaps.length > 0 && <div className="mt-2 flex flex-wrap gap-1.5">{s.overlaps.map((o, i) => <span key={i} className="rounded-md bg-warning-soft px-2 py-1 text-[11.5px] text-warning">{o}</span>)}</div>}
      {s.llm_note && <p className="mt-2 text-[12.5px] leading-relaxed text-primary">{s.llm_note}</p>}
      {s.abstract && <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-muted-foreground">{s.abstract}</p>}
    </div>
  )
}
