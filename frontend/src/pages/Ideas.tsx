import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { ArrowUpRight, BookPlus, Quote, Sparkles, Trash2, Wand2 } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field, Input } from '@/components/ui/input'
import { ScoreRing } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Switch } from '@/components/ui/switch'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { GridSkeleton } from './_skeleton'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Gender, Idea } from '@/lib/types'
import { GENRES_FEMALE, GENRES_MALE, cn } from '@/lib/utils'

export default function Ideas() {
  const [sp] = useSearchParams()
  const [genre, setGenre] = useState(sp.get('genre') ?? '')
  const [gender, setGender] = useState<Gender>((sp.get('gender') as Gender) || 'male')
  const [fromTrends, setFromTrends] = useState(sp.get('from_trends') !== '0')
  const [count, setCount] = useState(3)
  const [fresh, setFresh] = useState<number[]>([])
  const { start } = useJobs()
  const job = useActiveJob('ideas')
  const ideas = useQuery({ queryKey: qk.ideas, queryFn: api.ideas })
  const trends = useQuery({ queryKey: qk.radarTrends(), queryFn: () => api.radarTrends(), enabled: fromTrends })

  useEffect(() => { if (sp.get('genre')) setGenre(sp.get('genre')!) }, [sp])

  const genres = gender === 'male' ? GENRES_MALE : GENRES_FEMALE
  const other = gender === 'male' ? GENRES_FEMALE : GENRES_MALE
  // 热度榜不分频道：排除明显属于另一频道的题材
  const hot = (trends.data ?? []).map((t) => t.category).filter((c) => !other.includes(c)).slice(0, 5)
  const suggestions = Array.from(new Set([...(fromTrends ? hot : []), ...genres])).slice(0, 10)

  const generate = () =>
    start(api.generateIdeas({ genre: genre.trim() || undefined, gender, from_trends: fromTrends, count }), {
      key: 'ideas', label: '生成选题',
      successMsg: (j) => `已生成 ${(j.result?.idea_ids as number[] | undefined)?.length ?? count} 个选题`,
      onSuccess: (j) => {
        setFresh((j.result?.idea_ids as number[]) ?? [])
        setTimeout(() => document.getElementById('idea-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 300)
      },
    })

  const list = [...(ideas.data ?? [])].sort((a, b) => Number(fresh.includes(b.id)) - Number(fresh.includes(a.id)) || b.id - a.id)

  return (
    <div className="page">
      <PageHeader title="选题" />

      <Card className="overflow-hidden">
        <div className="grid gap-5 p-5 md:grid-cols-[1fr_auto] md:p-6">
          <div className="space-y-4">
            <div className="flex flex-wrap items-end gap-4">
              <Field label="频道">
                <Segmented value={gender} onChange={setGender} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
              </Field>
              <Field label="题材" className="min-w-[220px] flex-1">
                <Input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="例如：末世求生、年代重生…" onKeyDown={(e) => e.key === 'Enter' && !job && generate()} />
              </Field>
              <Field label="数量">
                <Segmented value={String(count)} onChange={(v) => setCount(Number(v))} options={[1, 3, 5].map((n) => ({ value: String(n), label: `${n} 个` }))} />
              </Field>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {suggestions.map((g) => (
                <button key={g} onClick={() => setGenre(g)} className={cn('h-7 rounded-full border px-3 text-[12.5px] transition', genre === g ? 'border-primary bg-primary-soft text-primary' : 'text-muted-foreground hover:border-foreground/25 hover:text-foreground')}>
                  {hot.includes(g) && <span className="mr-1 text-danger">●</span>}{g}
                </button>
              ))}
            </div>
            <label className="flex w-fit cursor-pointer items-center gap-2.5 text-[13px]">
              <Switch checked={fromTrends} onCheckedChange={setFromTrends} />
              <span>参考今日热点</span>
            </label>
          </div>
          <div className="flex items-end">
            <Button size="lg" variant="primary" loading={!!job} icon={<Wand2 className="h-4 w-4" />} onClick={generate} className="w-full md:w-auto">
              {job ? '生成中…' : '生成选题'}
            </Button>
          </div>
        </div>
        {job && <div className="border-t px-5 py-4 md:px-6"><JobInline job={job} /></div>}
      </Card>

      <div id="idea-results" className="mt-8 scroll-mt-6">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">选题卡 {ideas.data?.length ? <span className="ml-1 text-muted-foreground">{ideas.data.length}</span> : null}</h2>
          <ClearIdeas count={(ideas.data ?? []).filter((x) => !x.chosen).length} />
        </div>
        {ideas.isLoading ? <GridSkeleton n={3} h="h-64" /> : ideas.error ? <ErrorState error={ideas.error} onRetry={() => ideas.refetch()} /> : !list.length ? (
          <EmptyState kind="idea" title="还没有选题" />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <AnimatePresence initial={false}>
              {list.map((i, k) => <IdeaCard key={i.id} idea={i} fresh={fresh.includes(i.id)} delay={fresh.includes(i.id) ? k * 0.06 : 0} />)}
            </AnimatePresence>
          </div>
        )}
      </div>
    </div>
  )
}

function IdeaCard({ idea: i, fresh, delay }: { idea: Idea; fresh: boolean; delay: number }) {
  const nav = useNavigate()
  const qc = useQueryClient()
  const adopt = useMutation({
    mutationFn: () => api.adoptIdea(i.id),
    meta: { errorTitle: '建书失败' },
    onSuccess: (book) => {
      qc.invalidateQueries({ queryKey: ['books'] })
      qc.invalidateQueries({ queryKey: qk.ideas })
      toast.success(`《${book.title}》已建书`, { description: '下一步：生成设定库' })
      nav(`/books/${book.id}`)
    },
  })
  const rm = useMutation({
    mutationFn: () => api.deleteIdea(i.id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.setQueryData<Idea[]>(qk.ideas, (d) => d?.filter((x) => x.id !== i.id)); toast.success('选题已删除') },
  })
  return (
    <motion.div layout exit={{ opacity: 0, scale: 0.97 }} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay, duration: 0.25 }}
      className={cn('relative flex flex-col rounded-xl bg-surface p-5 hairline shadow-card transition hover:shadow-lift', fresh && 'ring-2 ring-primary/30', i.chosen && 'opacity-90')}>
      {fresh && <Badge tone="primary" className="absolute -top-2.5 left-4 shadow-card"><Sparkles className="h-3 w-3" />新生成</Badge>}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="break-words text-[16px] font-semibold leading-snug tracking-tight">{i.title}</h3>
          <div className="mt-1 text-xs text-muted-foreground">{i.genre}</div>
        </div>
        <ScoreRing value={i.scores.overall} size={50} label="综合" />
      </div>
      <p className="mt-3 break-words text-[13.5px] leading-relaxed text-foreground/85">{i.logline}</p>
      {i.selling_points.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {i.selling_points.map((s) => (
            <li key={s} className="flex gap-2 text-[12.5px] leading-relaxed text-primary/90">
              <span className="mt-[0.6em] h-1 w-1 shrink-0 rounded-full bg-primary/60" />
              <span className="min-w-0 break-words">{s}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex gap-2 rounded-lg bg-subtle px-3 py-2.5 text-[13px] leading-relaxed">
        <Quote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary/60" />
        <span className="min-w-0 break-words"><span className="text-muted-foreground">钩子：</span>{i.hook}</span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-3">
        {([['热度', i.scores.heat], ['新颖', i.scores.novelty], ['适配', i.scores.fit]] as const).map(([l, v]) => (
          <div key={l}>
            <div className="flex justify-between text-[11.5px] text-muted-foreground"><span>{l}</span><span className="num">{v}</span></div>
            <div className="mt-1 h-1 rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${v}%` }} /></div>
          </div>
        ))}
      </div>
      <div className="mt-auto flex gap-2 pt-5">
        {i.chosen && i.book_id ? (
          <Link to={`/books/${i.book_id}`} className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-md bg-success-soft text-[13px] font-medium text-success">已建书，去看看 <ArrowUpRight className="h-3.5 w-3.5" /></Link>
        ) : (
          <Button variant="primary" className="flex-1" loading={adopt.isPending} icon={<BookPlus className="h-4 w-4" />} onClick={() => adopt.mutate()}>采纳建书</Button>
        )}
        <Button variant="ghost" size="icon" aria-label="删除选题" loading={rm.isPending} onClick={() => rm.mutate()} className="shrink-0 text-muted-foreground hover:text-danger"><Trash2 className="h-4 w-4" /></Button>
      </div>
    </motion.div>
  )
}

function ClearIdeas({ count }: { count: number }) {
  const [open, setOpen] = useState(false)
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: api.clearIdeas,
    meta: { errorTitle: '清空失败' },
    onSuccess: (d) => { qc.invalidateQueries({ queryKey: qk.ideas }); setOpen(false); toast.success(`已删除 ${d.deleted} 个选题`) },
  })
  if (!count) return null
  return (
    <>
      <Button size="sm" variant="ghost" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setOpen(true)}>清空未采纳</Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title={`删除 ${count} 个未采纳的选题？`} desc="已建书的选题会保留。"
          footer={<><Button variant="ghost" onClick={() => setOpen(false)}>取消</Button><Button variant="danger" loading={m.isPending} onClick={() => m.mutate()}>删除</Button></>} />
      </Dialog>
    </>
  )
}
