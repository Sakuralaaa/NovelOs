import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, ArrowUpRight, BookPlus, ChevronRight, Plus, RefreshCw, RotateCcw, Sparkles, Trash2, Wand2, X } from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { ScoreRing, Skeleton } from '@/components/ui/misc'
import { Select, type Opt } from '@/components/ui/select'
import { ErrorState } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { useChannels } from '@/hooks/queries'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Idea, IdeaField } from '@/lib/types'
import { cn } from '@/lib/utils'

type Draft = Pick<Idea, 'title' | 'genre' | 'logline' | 'hook' | 'selling_points'> & { expectations: string[]; arc: string[]; endgame: string }

const RUBRIC: [string, string][] = [
  ['gf', '金手指玩法'], ['angle', '切入点'], ['fresh', '不撞车'],
  ['opening', '开篇抓人'], ['payoff', '爽点兑现'], ['growth', '成长后劲'], ['longrun', '长线结构'], ['pitch', '书名简介'],
]
const ROUTE_KEY = 'novelos.idea-revise-route'

const toDraft = (i: Idea): Draft => ({
  title: i.title, genre: i.genre, logline: i.logline, hook: i.hook, selling_points: [...i.selling_points],
  expectations: [...(i.expectations ?? [])], arc: [...(i.arc ?? [])], endgame: i.endgame ?? '',
})
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export default function IdeaDetail() {
  const id = Number(useParams().ideaId)
  const nav = useNavigate()
  const qc = useQueryClient()
  const { start } = useJobs()
  const q = useQuery({ queryKey: qk.idea(id), queryFn: () => api.idea(id), enabled: Number.isFinite(id) })
  const idea = q.data
  const [draft, setDraft] = useState<Draft | null>(null)
  const [touched, setTouched] = useState<Set<IdeaField>>(new Set())
  const [route, setRouteState] = useState<string | null>(() => localStorage.getItem(ROUTE_KEY) || null)
  const [ask, setAsk] = useState('')
  const channels = useChannels()
  const opts: Opt[] = (channels.data ?? []).filter((c) => c.enabled).flatMap((c) => c.models.map((m) => ({ value: `${c.id}:${m}`, label: <span className="font-mono text-[12.5px]">{m}</span>, group: c.name })))
  const model = route && opts.some((o) => o.value === route) ? route : null
  const setRoute = (v: string | null) => { setRouteState(v); if (v) localStorage.setItem(ROUTE_KEY, v); else localStorage.removeItem(ROUTE_KEY) }

  const base = useMemo(() => (idea ? toDraft(idea) : null), [idea])
  const dirtyKeys = useMemo(() => (draft && base ? (Object.keys(base) as IdeaField[]).filter((k) => !same(draft[k], base[k])) : []), [draft, base])
  const dirty = dirtyKeys.length > 0

  // 服务端版本变化（保存、撤回、整体修改）时同步；有未保存内容时不覆盖
  useEffect(() => { if (base && (!draft || !dirty)) { setDraft(base); setTouched(new Set()) } }, [base]) // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = (d?: Idea) => {
    if (d) qc.setQueryData(qk.idea(id), d)
    qc.invalidateQueries({ queryKey: qk.idea(id) })
    qc.invalidateQueries({ queryKey: qk.ideas })
  }
  const save = useMutation({
    mutationFn: () => api.updateIdea(id, Object.fromEntries(dirtyKeys.map((k) => [k, draft![k]]))),
    meta: { errorTitle: '保存失败' },
    onSuccess: (d) => { setDraft(toDraft(d)); setTouched(new Set()); refresh(d); toast.success('已保存') },
  })
  const undo = useMutation({
    mutationFn: () => api.undoIdea(id), meta: { errorTitle: '撤回失败' },
    onSuccess: (d) => { setDraft(toDraft(d)); setTouched(new Set()); refresh(d); toast.success('已退回上一版') },
  })
  const adopt = useMutation({
    mutationFn: () => api.adoptIdea(id), meta: { errorTitle: '建书失败' },
    onSuccess: (book) => { qc.invalidateQueries({ queryKey: ['books'] }); refresh(); toast.success(`《${book.title}》已建书`); nav(`/books/${book.id}`) },
  })
  const rm = useMutation({
    mutationFn: () => api.deleteIdea(id), meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.ideas }); toast.success('选题已删除'); nav('/ideas') },
  })
  const reviseJob = useActiveJob(`idea-revise:${id}`)
  const scoreJob = useActiveJob(`idea-rescore:${id}`)

  if (q.isLoading || (idea && !draft)) return <div className="page"><Skeleton className="h-10 w-72" /><Skeleton className="mt-6 h-40 rounded-xl" /><Skeleton className="mt-4 h-72 rounded-xl" /></div>
  if (q.error || !idea || !draft) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>

  const locked = idea.chosen
  const set = <K extends IdeaField>(k: K, v: Draft[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d))

  const reviseAll = async () => {
    const instruction = ask.trim()
    if (!instruction) return
    if (dirty) await save.mutateAsync()
    start(api.reviseIdea(id, { instruction, route: model }), {
      key: `idea-revise:${id}`, label: `修改《${draft.title}》`,
      successMsg: (j) => (j.result?.change as string) || '选题已修改',
      onSuccess: () => { setDraft(null); refresh() },
    })
    setAsk('')
  }
  const suggest = (field: IdeaField, instruction: string) =>
    start(api.suggestIdeaField(id, { field, instruction, route: model, draft }), {
      key: `idea-field:${id}:${field}`, label: 'AI 改写', silent: true,
      onSuccess: (j) => {
        const v = j.result?.value
        if (v == null) return
        set(field, v as never)
        setTouched((t) => new Set(t).add(field))
      },
      onError: (j) => toast.error('AI 改写失败', { description: j.error ?? undefined }),
    })
  const rescore = () => start(api.rescoreIdea(id), { key: `idea-rescore:${id}`, label: '重新打分', successMsg: '分数已更新', onSuccess: () => refresh() })

  const fieldProps = (k: IdeaField) => ({ field: k, ideaId: id, locked, changed: touched.has(k) && dirtyKeys.includes(k), onSuggest: suggest })

  return (
    <div className="page pb-28">
      <div className="flex items-center gap-1 text-[12.5px] text-muted-foreground">
        <Link to="/ideas" className="hover:text-foreground">选题</Link>
        <ChevronRight className="h-3 w-3" />
        <span className="max-w-[320px] truncate text-foreground/80">{idea.title}</span>
      </div>

      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="break-words text-[24px] font-semibold leading-tight tracking-tight">{draft.title || '未命名'}</h1>
          <div className="mt-1 text-[13px] text-muted-foreground">{draft.genre}</div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {!locked && !!idea.versions && (
            <Button variant="ghost" size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={undo.isPending} disabled={!!reviseJob} onClick={() => undo.mutate()} title={idea.last_instruction ? `撤回：${idea.last_instruction}` : undefined}>撤回</Button>
          )}
          <Button variant="ghost" size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} loading={rm.isPending} onClick={() => rm.mutate()} className="hover:text-danger">删除</Button>
          {locked && idea.book_id ? (
            <Link to={`/books/${idea.book_id}`} className="flex h-9 items-center gap-1.5 rounded-md bg-success-soft px-3.5 text-[13px] font-medium text-success">已建书，去看看 <ArrowUpRight className="h-3.5 w-3.5" /></Link>
          ) : (
            <Button variant="primary" icon={<BookPlus className="h-4 w-4" />} loading={adopt.isPending} disabled={dirty || !!reviseJob} onClick={() => adopt.mutate()}>采纳建书</Button>
          )}
        </div>
      </div>

      {!locked && (
        <Card className="mt-6">
          <CardHeader icon={<Wand2 />} title="让 AI 改" action={<div className="w-[220px]"><Select value={model} onChange={setRoute} options={opts} allowEmpty emptyLabel="默认（策划模型）" placeholder="默认（策划模型）" /></div>} />
          <CardBody className="space-y-3">
            <Textarea rows={3} value={ask} disabled={!!reviseJob} onChange={(e) => setAsk(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) reviseAll() }}
              placeholder="例如：主角换成武道高考生；金手指改成能看到功法词条；第三阶段别去异界，留在本土打世家" />
            <div className="flex items-center justify-end gap-3">
              {reviseJob && <div className="min-w-0 flex-1"><JobInline job={reviseJob} /></div>}
              <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} loading={!!reviseJob || save.isPending} disabled={!ask.trim()} onClick={reviseAll}>整体修改</Button>
            </div>
          </CardBody>
        </Card>
      )}

      <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <Card><CardBody className="space-y-5">
            <FieldBlock label="书名" {...fieldProps('title')}>
              <Input value={draft.title} disabled={locked} maxLength={40} onChange={(e) => set('title', e.target.value)} />
            </FieldBlock>
            <FieldBlock label="题材" {...fieldProps('genre')}>
              <Input value={draft.genre} disabled={locked} onChange={(e) => set('genre', e.target.value)} />
            </FieldBlock>
            <FieldBlock label="简介" {...fieldProps('logline')}>
              <Textarea rows={3} value={draft.logline} disabled={locked} onChange={(e) => set('logline', e.target.value)} />
            </FieldBlock>
            <FieldBlock label="钩子" {...fieldProps('hook')}>
              <Textarea rows={2} value={draft.hook} disabled={locked} onChange={(e) => set('hook', e.target.value)} className="min-h-[64px]" />
            </FieldBlock>
          </CardBody></Card>
          <Card><CardBody className="space-y-5">
            <FieldBlock label="卖点" {...fieldProps('selling_points')}>
              <ListEdit value={draft.selling_points} disabled={locked} onChange={(v) => set('selling_points', v)} max={4} />
            </FieldBlock>
            <FieldBlock label="长期期待" {...fieldProps('expectations')}>
              <ListEdit value={draft.expectations} disabled={locked} onChange={(v) => set('expectations', v)} max={3} />
            </FieldBlock>
          </CardBody></Card>
        </div>

        <div className="space-y-5">
          <Card><CardBody className="space-y-5">
            <FieldBlock label="长线阶段" {...fieldProps('arc')}>
              <ListEdit value={draft.arc} disabled={locked} onChange={(v) => set('arc', v)} max={6} numbered multiline />
            </FieldBlock>
            <FieldBlock label="终局" {...fieldProps('endgame')}>
              <Textarea rows={2} value={draft.endgame} disabled={locked} onChange={(e) => set('endgame', e.target.value)} className="min-h-[64px]" />
            </FieldBlock>
          </CardBody></Card>
          <Card>
            <CardHeader title="评分" action={<Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={!!scoreJob} disabled={dirty} onClick={rescore}>重新打分</Button>} />
            <CardBody>
              <div className="flex items-center gap-5">
                <ScoreRing value={idea.scores.overall} size={64} label="综合" />
                <div className="grid flex-1 gap-2.5">
                  {([['热度', idea.scores.heat], ['新颖', idea.scores.novelty], ['适配', idea.scores.fit]] as const).map(([l, v]) => (
                    <div key={l}>
                      <div className="flex justify-between text-[12px] text-muted-foreground"><span>{l}</span><span className="num">{v}</span></div>
                      <div className="mt-1 h-1 rounded-full bg-muted"><div className="h-full rounded-full bg-primary/70" style={{ width: `${v}%` }} /></div>
                    </div>
                  ))}
                </div>
              </div>
              {idea.score_detail && Object.keys(idea.score_detail).length > 0 && (
                <div className="mt-4 grid grid-cols-2 gap-x-5 gap-y-2 border-t pt-4">
                  {RUBRIC.filter(([k]) => k in idea.score_detail!).map(([k, l]) => (
                    <div key={k} className="flex items-center justify-between gap-2 text-[12.5px]">
                      <span className="truncate text-muted-foreground">{l}</span>
                      <span className="flex shrink-0 gap-0.5">
                        {[1, 2, 3, 4].map((n) => <span key={n} className={cn('h-1.5 w-3 rounded-full', n <= idea.score_detail![k] ? 'bg-primary/70' : 'bg-muted')} />)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {idea.issue && <div className="mt-4 flex gap-1.5 text-[12.5px] leading-relaxed text-warning"><AlertCircle className="mt-[3px] h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words">{idea.issue}</span></div>}
            </CardBody>
          </Card>
        </div>
      </div>

      {dirty && !locked && (
        <div className="fixed inset-x-0 bottom-5 z-40 flex justify-center px-4">
          <div className="flex items-center gap-3 rounded-xl bg-popover px-4 py-2.5 shadow-pop hairline">
            <span className="text-[13px] text-muted-foreground">改了 {dirtyKeys.length} 处</span>
            <Button size="sm" variant="ghost" onClick={() => { setDraft(base); setTouched(new Set()) }}>放弃</Button>
            <Button size="sm" variant="primary" loading={save.isPending} onClick={() => save.mutate()}>保存</Button>
          </div>
        </div>
      )}
    </div>
  )
}

function FieldBlock({ label, field, ideaId, locked, changed, onSuggest, children }: {
  label: string; field: IdeaField; ideaId: number; locked: boolean; changed: boolean
  onSuggest: (f: IdeaField, instruction: string) => void; children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const job = useActiveJob(`idea-field:${ideaId}:${field}`)
  const go = () => { onSuggest(field, text.trim()); setText(''); setOpen(false) }
  return (
    <div>
      <div className="mb-1.5 flex h-7 items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[13px] font-medium text-foreground/85">
          {label}
          {changed && <span className="rounded bg-primary-soft px-1.5 py-px text-[11px] font-normal text-primary">AI 改过</span>}
        </span>
        {!locked && (
          <Button size="xs" variant="ghost" loading={!!job} icon={<Sparkles className="h-3.5 w-3.5" />} onClick={() => setOpen((v) => !v)} className={cn('text-muted-foreground hover:text-primary', open && 'bg-muted text-primary')}>
            {job ? '改写中' : 'AI 改'}
          </Button>
        )}
      </div>
      {open && !job && (
        <div className="mb-2 flex gap-2">
          <Input autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') go(); if (e.key === 'Escape') setOpen(false) }}
            placeholder={`想怎么改${label}？留空就让 AI 自己发挥`} className="h-8 text-[13px]" />
          <Button size="sm" variant="soft" onClick={go}>改写</Button>
        </div>
      )}
      <div className={cn('rounded-md transition', changed && 'ring-2 ring-primary/25')}>{children}</div>
    </div>
  )
}

function ListEdit({ value, onChange, disabled, max, numbered, multiline }: {
  value: string[]; onChange: (v: string[]) => void; disabled?: boolean; max: number; numbered?: boolean; multiline?: boolean
}) {
  const upd = (k: number, v: string) => onChange(value.map((x, i) => (i === k ? v : x)))
  return (
    <div className="space-y-2">
      {value.map((x, k) => (
        <div key={k} className="flex items-start gap-2">
          {numbered && <span className="num mt-2 w-4 shrink-0 text-right text-[12.5px] text-primary/70">{k + 1}</span>}
          {multiline ? (
            <Textarea rows={2} value={x} disabled={disabled} onChange={(e) => upd(k, e.target.value)} className="min-h-[56px] text-[13px]" />
          ) : (
            <Input value={x} disabled={disabled} onChange={(e) => upd(k, e.target.value)} className="text-[13px]" />
          )}
          {!disabled && (
            <Button size="icon" variant="ghost" aria-label="删除这一条" onClick={() => onChange(value.filter((_, i) => i !== k))} className="shrink-0 text-muted-foreground hover:text-danger"><X className="h-4 w-4" /></Button>
          )}
        </div>
      ))}
      {!disabled && value.length < max && (
        <Button size="xs" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => onChange([...value, ''])} className={cn('text-muted-foreground', numbered && 'ml-6')}>添加一条</Button>
      )}
    </div>
  )
}

