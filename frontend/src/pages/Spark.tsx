import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowRight, Check, ChevronLeft, Dice, Pin, RefreshCw, Zap } from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { JobInline } from '@/components/common/JobInline'
import { v013Api } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Gender, SparkAxis, SparkCard, SparkSessionData } from '@/lib/types'
import { cn } from '@/lib/utils'

const AXES: { key: SparkAxis; label: string }[] = [{ key: 'world', label: '世界观' }, { key: 'hero', label: '主角' }, { key: 'cheat', label: '金手指' }]
const STEPS = ['基本信息', '世界观', '主角', '金手指', '立项书']

export default function SparkPage() {
  const sid = Number(useParams().sid) || 0
  const nav = useNavigate()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['spark', sid], queryFn: () => v013Api.sparkGet(sid), enabled: !!sid })
  const d = q.data
  const reach = !d ? 0 : d.proposal ? 4 : AXES.reduce((n, a, i) => (d.picks[a.key] ? Math.max(n, i + 2) : n), 1)
  const [step, setStep] = useState<number | null>(null)
  const cur = Math.min(step ?? reach, reach)
  const set = (x: SparkSessionData) => qc.setQueryData(['spark', x.id], x)
  return (
    <div className="page max-w-[1080px]">
      <Link to="/ideas/new" className="mb-1 inline-flex h-8 items-center gap-0.5 rounded-md pr-2 text-[13px] text-muted-foreground hover:text-foreground"><ChevronLeft className="h-4 w-4" />新建立项</Link>
      <h1 className="mb-4 flex items-center gap-2 text-[22px] font-semibold tracking-tight"><Dice className="h-5 w-5 text-primary" />抽卡立项</h1>
      <ol className="-mx-1 mb-5 flex items-center gap-1 overflow-x-auto px-1 pb-1 [scrollbar-width:none]">
        {STEPS.map((s, i) => {
          const on = i === cur, ok = i <= reach && (i === 0 || !!d)
          return (
            <li key={s} className="flex shrink-0 items-center gap-1">
              {i > 0 && <span className={cn('h-px w-4 sm:w-8', ok ? 'bg-primary/40' : 'bg-border')} />}
              <button type="button" disabled={!ok || on || (i === 0 && !!d)} onClick={() => setStep(i)}
                className={cn('flex h-10 items-center gap-2 rounded-full pl-1.5 pr-3.5 text-[13px] font-medium transition disabled:cursor-default',
                  on ? 'bg-foreground text-background' : ok ? 'bg-surface hairline hover:bg-subtle' : 'text-muted-foreground/60')}>
                <span className={cn('num flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-semibold', on ? 'bg-background/15' : i < reach ? 'bg-primary text-primary-foreground' : 'bg-muted')}>
                  {i < reach && !on ? <Check className="h-3.5 w-3.5" /> : i + 1}
                </span>{s}
              </button>
            </li>
          )
        })}
      </ol>
      {!sid ? <BasicStep onCreated={(x) => { set(x); nav(`/spark/${x.id}`, { replace: true }) }} />
        : !d ? <Skeleton className="h-96 rounded-2xl" />
        : cur >= 1 && cur <= 3 ? <AxisStep key={AXES[cur - 1].key} d={d} axis={AXES[cur - 1].key} onChange={set} onNext={() => setStep(cur + 1)} />
        : <ProposalStep d={d} onChange={set} />}
    </div>
  )
}

function BasicStep({ onCreated }: { onCreated: (x: SparkSessionData) => void }) {
  const [gender, setGender] = useState<Gender>('male')
  const [track, setTrack] = useState('')
  const [sub, setSub] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [insp, setInsp] = useState({ title: '', tags: '', synopsis: '' })
  const tq = useQuery({ queryKey: ['spark-tracks', gender], queryFn: () => v013Api.sparkTracks(gender) })
  const cur = tq.data?.tracks.find((t) => t.track === track)
  const create = useMutation({
    mutationFn: () => v013Api.sparkCreate({ gender, track, sub, tags, inspiration: insp }),
    meta: { errorTitle: '创建失败' },
    onSuccess: onCreated,
  })
  return (
    <div className="space-y-5">
      <section className="rounded-xl border bg-surface p-4 shadow-card sm:p-5">
        <Field label="频道"><Segmented value={gender} onChange={(g) => { setGender(g); setTrack(''); setSub(''); setTags([]) }} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} /></Field>
        <div className="mt-4 text-[13px] font-medium text-foreground/85">赛道</div>
        {tq.isLoading ? <Skeleton className="mt-2 h-32 rounded-xl" /> : (
          <div className="mt-2 grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,180px),1fr))]">
            {tq.data?.tracks.map((t) => (
              <button key={t.track} type="button" onClick={() => { setTrack(t.track); setSub('') }}
                className={cn('min-h-[68px] min-w-0 rounded-xl border p-3 text-left transition', track === t.track ? 'border-primary bg-primary-soft/40 ring-2 ring-primary/15' : 'hover:border-foreground/20')}>
                <div className="flex items-center gap-1.5"><span className="min-w-0 flex-1 truncate text-[14px] font-semibold">{t.track}</span>{t.heat != null && <span className="num inline-flex items-center gap-0.5 text-[12px] text-primary"><Zap className="h-3 w-3" />{t.heat}</span>}</div>
                {t.sample_titles.length > 0 ? <div className="mt-1 truncate text-[11.5px] text-muted-foreground">{t.sample_titles.join('、')}</div>
                  : t.rising ? <div className="mt-1 text-[11.5px] text-muted-foreground">{t.rising} 本在涨</div> : null}
              </button>
            ))}
          </div>
        )}
        {cur && cur.subs.length > 0 && (
          <div className="mt-4"><div className="text-[13px] font-medium text-foreground/85">细分</div>
            <div className="mt-2 flex flex-wrap gap-1.5">{cur.subs.map((x) => <Chip key={x} on={sub === x} onClick={() => setSub(sub === x ? '' : x)}>{x}</Chip>)}</div></div>
        )}
        {tq.data && (
          <div className="mt-4"><div className="text-[13px] font-medium text-foreground/85">标签</div>
            <div className="mt-2 flex flex-wrap gap-1.5">{tq.data.tag_groups.map((x) => <Chip key={x} on={tags.includes(x)} onClick={() => setTags((t) => (t.includes(x) ? t.filter((y) => y !== x) : t.length >= 6 ? t : [...t, x]))}>{x}</Chip>)}</div></div>
        )}
      </section>
      <section className="grid gap-3 rounded-xl border bg-surface p-4 shadow-card sm:grid-cols-2 sm:p-5">
        <Field label="想要的书名（可选）"><Input value={insp.title} onChange={(e) => setInsp({ ...insp, title: e.target.value })} className="h-10" /></Field>
        <Field label="想要的标签（可选）"><Input value={insp.tags} onChange={(e) => setInsp({ ...insp, tags: e.target.value })} className="h-10" /></Field>
        <Field label="一句话梗概（可选）" className="sm:col-span-2"><Textarea value={insp.synopsis} onChange={(e) => setInsp({ ...insp, synopsis: e.target.value })} className="min-h-[72px]" /></Field>
      </section>
      <div className="flex justify-end"><Button variant="primary" className="h-11" disabled={!track} loading={create.isPending} icon={<ArrowRight className="h-4 w-4" />} onClick={() => create.mutate()}>开始抽卡</Button></div>
    </div>
  )
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return <button type="button" onClick={onClick} className={cn('inline-flex h-9 items-center rounded-full border px-3 text-[13px] transition', on ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>{children}</button>
}

function AxisStep({ d, axis, onChange, onNext }: { d: SparkSessionData; axis: SparkAxis; onChange: (x: SparkSessionData) => void; onNext: () => void }) {
  const { start } = useJobs()
  const key = `spark-draw:${d.id}:${axis}`
  const active = useActiveJob(key)
  const cards = d.cards[axis] ?? []
  const [keep, setKeep] = useState<string[]>(d.keep[axis] ?? [])
  const [custom, setCustom] = useState('')
  const [own, setOwn] = useState({ title: '', desc: '' })
  const picked = d.picks[axis]
  const label = AXES.find((a) => a.key === axis)!.label
  const draw = () => start(v013Api.sparkDraw(d.id, axis, keep.filter((k) => cards.some((c) => c.id === k)), custom), {
    key, label: `抽${label}卡`, silent: true, onSuccess: (j) => onChange(j.result as SparkSessionData),
  })
  const pick = useMutation({
    mutationFn: (c: { id: string | null; own?: boolean }) => v013Api.sparkPick(d.id, axis, c.own ? null : c.id, c.own ? own : undefined),
    meta: { errorTitle: '选择失败' },
    onSuccess: (x) => onChange(x),
  })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="这一轮的要求（可选）" className="min-w-[240px] flex-1"><Input value={custom} onChange={(e) => setCustom(e.target.value)} className="h-10" placeholder={axis === 'cheat' ? '如：要能成长到后期，不要系统' : ''} /></Field>
        <Button variant="primary" className="h-10" loading={!!active} icon={cards.length ? <RefreshCw className="h-4 w-4" /> : <Dice className="h-4 w-4" />} onClick={() => void draw()}>{cards.length ? '换一批' : `抽 9 张${label}卡`}</Button>
      </div>
      {active && <JobInline job={active} />}
      {cards.length > 0 && (
        <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,280px),1fr))]">
          {cards.map((c) => <CardTile key={c.id} c={c} picked={picked?.id === c.id} kept={keep.includes(c.id)}
            onPick={() => pick.mutate({ id: c.id })} onKeep={() => setKeep((k) => (k.includes(c.id) ? k.filter((x) => x !== c.id) : [...k, c.id]))} />)}
        </div>
      )}
      <section className="rounded-xl border border-dashed p-4">
        <div className="text-[13px] font-medium">自己写一张</div>
        <div className="mt-2 grid gap-2 sm:grid-cols-[220px_minmax(0,1fr)_auto]">
          <Input value={own.title} onChange={(e) => setOwn({ ...own, title: e.target.value })} placeholder="标题" className="h-10" />
          <Input value={own.desc} onChange={(e) => setOwn({ ...own, desc: e.target.value })} placeholder="说明" className="h-10" />
          <Button disabled={!own.title.trim()} loading={pick.isPending} onClick={() => pick.mutate({ id: null, own: true })}>用这张</Button>
        </div>
      </section>
      {picked && (
        <div className="sticky bottom-0 z-10 -mx-5 flex items-center gap-3 border-t bg-background/90 px-5 py-3 backdrop-blur md:-mx-10 md:px-10">
          <span className="min-w-0 flex-1 truncate text-[13px]">已选：<b>{picked.title}</b></span>
          <Button variant="primary" className="h-11" icon={<ArrowRight className="h-4 w-4" />} onClick={onNext}>下一步</Button>
        </div>
      )}
    </div>
  )
}

function CardTile({ c, picked, kept, onPick, onKeep }: { c: SparkCard; picked: boolean; kept: boolean; onPick: () => void; onKeep: () => void }) {
  return (
    <div className={cn('flex min-h-[170px] flex-col rounded-xl border bg-surface p-3.5 shadow-card transition', picked ? 'border-primary ring-2 ring-primary/20' : 'hover:border-foreground/20')}>
      <div className="flex items-start gap-2">
        <span className="min-w-0 flex-1 text-[15px] font-semibold leading-snug">{c.title}</span>
        <button type="button" onClick={onKeep} aria-label="保留" className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition', kept ? 'bg-primary-soft text-primary' : 'text-muted-foreground hover:bg-muted')}><Pin className="h-4 w-4" /></button>
      </div>
      <p className="mt-1.5 flex-1 text-[12.5px] leading-relaxed text-foreground/75">{c.desc}</p>
      <div className="mt-2 flex flex-wrap gap-1">
        {c.heat != null && <Badge tone="primary"><Zap className="h-3 w-3" />{c.heat}</Badge>}
        <Badge tone={c.similarity >= 40 ? 'warning' : 'outline'} title={c.similar_to ? `最像《${c.similar_to}》` : undefined}>相似 {c.similarity}%</Badge>
        {c.trope_hits.map((t) => <Badge key={t} tone="danger"><AlertTriangle className="h-3 w-3" />{t}</Badge>)}
      </div>
      <Button size="sm" variant={picked ? 'primary' : 'soft'} className="mt-2.5 h-9" icon={picked ? <Check className="h-3.5 w-3.5" /> : undefined} onClick={onPick}>{picked ? '已选' : '选这张'}</Button>
    </div>
  )
}

function ProposalStep({ d, onChange }: { d: SparkSessionData; onChange: (x: SparkSessionData) => void }) {
  const nav = useNavigate()
  const { start } = useJobs()
  const key = `spark-proposal:${d.id}`
  const active = useActiveJob(key)
  const p = d.proposal
  const gen = () => start(v013Api.sparkProposal(d.id), { key, label: '写立项书', silent: true, onSuccess: (j) => onChange(j.result as SparkSessionData) })
  const save = useMutation({ mutationFn: (b: Record<string, unknown>) => v013Api.sparkPatchProposal(d.id, b), meta: { errorTitle: '保存失败' }, onSuccess: onChange })
  const adopt = useMutation({
    mutationFn: () => v013Api.sparkAdopt(d.id),
    meta: { errorTitle: '保存失败' },
    onSuccess: (r) => { toast.success('已存为选题'); nav(`/ideas/${r.idea_id}`) },
  })
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-3">
        {AXES.map((a) => <div key={a.key} className="rounded-xl bg-subtle px-3.5 py-2.5"><div className="text-[11.5px] text-muted-foreground">{a.label}</div><div className="mt-0.5 text-[13.5px] font-semibold">{d.picks[a.key]?.title}</div></div>)}
      </div>
      {!p ? (
        <div className="rounded-xl border border-dashed px-4 py-10 text-center">
          {active ? <JobInline job={active} /> : <Button variant="primary" className="h-11" icon={<Zap className="h-4 w-4" />} onClick={() => void gen()}>生成立项书</Button>}
        </div>
      ) : (
        <>
          {active && <JobInline job={active} />}
          <section className="rounded-xl border bg-surface p-4 shadow-card sm:p-5">
            <div className="flex items-center justify-between gap-2"><span className="text-[13px] font-medium">书名</span><Badge tone={p.completeness >= 90 ? 'success' : 'warning'}>完成度 {p.completeness}%</Badge></div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {p.titles.map((t) => <Chip key={t.title} on={p.title === t.title} onClick={() => save.mutate({ title: t.title })}>{t.title}<span className="num ml-1 text-[11px] text-muted-foreground">{t.score}</span></Chip>)}
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {([['tagline', '一句话卖点'], ['hook', '开篇钩子'], ['logline', '故事梗概'], ['conflict', '核心冲突'], ['style', '文风标准'], ['endgame', '终局目标']] as const).map(([k, lab]) => (
                <Field key={k} label={lab}><Textarea defaultValue={p[k]} onBlur={(e) => e.target.value !== p[k] && save.mutate({ [k]: e.target.value })} className="min-h-[72px]" /></Field>
              ))}
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <ListBox label="卖点" items={p.selling_points} />
              <ListBox label="长线阶段" items={p.arc} />
              <ListBox label={`力量体系 · ${p.power.name || '—'}`} items={p.power.levels} />
            </div>
          </section>
          <section className="rounded-xl border bg-surface p-4 shadow-card sm:p-5">
            <div className="text-[13px] font-medium">种子设定（建书时直接进设定库）</div>
            <div className="mt-2 grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,240px),1fr))]">
              {p.seed_cards.map((c) => (
                <div key={c.name} className="rounded-lg bg-subtle px-3 py-2.5">
                  <div className="text-[13.5px] font-semibold">{c.name}</div>
                  <p className="mt-0.5 line-clamp-3 text-[12.5px] text-muted-foreground">{c.summary}</p>
                </div>
              ))}
            </div>
          </section>
          <div className="flex flex-wrap justify-end gap-2">
            <Button loading={!!active} icon={<RefreshCw className="h-4 w-4" />} onClick={() => void gen()}>重写立项书</Button>
            <Button variant="primary" className="h-11" loading={adopt.isPending} icon={<Check className="h-4 w-4" />} onClick={() => adopt.mutate()}>{d.idea_id ? '打开选题' : '存为选题'}</Button>
          </div>
        </>
      )}
    </div>
  )
}

function ListBox({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="rounded-lg bg-subtle px-3 py-2.5">
      <div className="text-[12px] text-muted-foreground">{label}</div>
      <ul className="mt-1 space-y-0.5 text-[13px]">{items.map((x, i) => <li key={i}>· {x}</li>)}</ul>
    </div>
  )
}
