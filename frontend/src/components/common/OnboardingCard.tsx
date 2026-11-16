import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { ArrowRight, Check, Layers, Plug, PenLine, Sparkles, X, Lightbulb } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { api, qk } from '@/lib/api'
import type { OnboardingKey, OnboardingState } from '@/lib/types'
import { cn } from '@/lib/utils'

const DEFAULT_ORDER: OnboardingKey[] = ['model', 'project', 'bible_outline', 'first_chapter']
const META: Record<OnboardingKey, { label: string; desc: string; cta: string; icon: typeof Plug }> = {
  model: { label: '配置模型', desc: '接入一个 OpenAI 兼容渠道，选好写作模型', cta: '去设置', icon: Plug },
  project: { label: '立项', desc: '从热点、灵感或参考书开一本新书', cta: '新建作品', icon: Lightbulb },
  bible_outline: { label: '生成设定与大纲', desc: '世界观、人物、总纲和前几章章纲', cta: '去生成', icon: Layers },
  first_chapter: { label: '写第一章', desc: '按章纲写出第 1 章，再审稿、修人味', cta: '去写作', icon: PenLine },
}

/** 首页新手引导：四步，按实际数据自动打勾，可关闭（存后端 /onboarding） */
export function OnboardingCard({ latestBookId, onCreate, onNavigate }: { latestBookId?: number; onCreate: () => void; onNavigate: (to: string) => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: qk.onboarding, queryFn: api.onboarding, retry: false, refetchOnWindowFocus: true })
  const dismiss = useMutation({
    mutationFn: () => api.saveOnboarding({ dismissed: true }),
    meta: { errorTitle: '关闭引导失败' },
    onMutate: () => qc.setQueryData<OnboardingState>(qk.onboarding, (o) => (o ? { ...o, dismissed: true } : o)),
    onSuccess: (d) => qc.setQueryData(qk.onboarding, d),
    onError: () => qc.invalidateQueries({ queryKey: qk.onboarding }),
  })
  const d = q.data
  if (!d || d.dismissed) return null
  const order = d.order?.length ? d.order : DEFAULT_ORDER
  const doneN = order.filter((k) => d.steps[k]).length
  const allDone = doneN === order.length
  const go = (k: OnboardingKey) => {
    if (k === 'model') onNavigate('/settings')
    else if (k === 'project') onCreate()
    else if (k === 'bible_outline') onNavigate(latestBookId ? `/books/${latestBookId}` : '/books')
    else onNavigate(latestBookId ? `/books/${latestBookId}/chapters` : '/books')
  }

  return (
    <Card className="relative mb-6 overflow-hidden" aria-label="新手引导">
      <div aria-hidden className="pointer-events-none absolute -right-16 -top-20 h-56 w-56 rounded-full bg-primary/10 blur-3xl" />
      <div className="relative flex flex-wrap items-center gap-3 px-5 pb-2 pt-4">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-soft text-primary"><Sparkles className="h-4 w-4" weight="duotone" /></span>
        <div className="min-w-0 flex-1">
          <div className="text-[14.5px] font-semibold tracking-tight">{allDone ? '新手四步都完成了' : '新手引导 · 从零写出第一章'}</div>
          <div className="text-[12.5px] text-muted-foreground">{allDone ? '之后有问题随时去书的概览页看「作品完整度」' : `已完成 ${doneN}/${order.length}，做完的步骤会自动打勾`}</div>
        </div>
        <div className="hidden h-1.5 w-28 overflow-hidden rounded-full bg-muted sm:block" aria-hidden><div className="h-full rounded-full bg-primary transition-[width] duration-700" style={{ width: `${(doneN / order.length) * 100}%` }} /></div>
        <button onClick={() => dismiss.mutate()} aria-label="关闭新手引导" title="关闭（以后不再显示）"
          className="focus-ring -mr-1.5 flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-muted hover:text-foreground"><X className="h-4 w-4" /></button>
      </div>
      <ol className="relative grid gap-2 p-3 pt-1 sm:grid-cols-2 xl:grid-cols-4">
        {order.map((k, i) => {
          const m = META[k] ?? { label: d.labels?.[k] ?? k, desc: '', cta: '去完成', icon: ArrowRight }
          const done = !!d.steps[k]
          const cur = d.current === k
          const needsBook = (k === 'bible_outline' || k === 'first_chapter') && !latestBookId
          return (
            <motion.li key={k} layout className={cn('flex min-h-[76px] items-center gap-3 rounded-xl px-3.5 py-3 transition-colors', cur ? 'bg-primary-soft ring-1 ring-primary/25' : 'bg-subtle/60')}>
              <span className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[13px] font-semibold transition-colors',
                done ? 'bg-success text-white' : cur ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>
                {done ? <Check className="h-4 w-4" strokeWidth={2.5} /> : i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className={cn('truncate text-[14px] font-medium', done && 'text-muted-foreground line-through decoration-foreground/20')}>{d.labels?.[k] || m.label}</div>
                {!done && <div className="mt-0.5 line-clamp-2 text-[12px] leading-snug text-muted-foreground">{m.desc}</div>}
              </div>
              {!done && <Button size="sm" variant={cur ? 'primary' : 'secondary'} className="h-10 shrink-0" disabled={needsBook} title={needsBook ? '先立项' : undefined} onClick={() => go(k)}>{m.cta}</Button>}
            </motion.li>
          )
        })}
      </ol>
    </Card>
  )
}
