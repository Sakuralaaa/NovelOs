import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowRight, BookOpenCheck, BookPlus, Check, ChevronLeft, Layers, ShieldCheck, Wand2 } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Select } from '@/components/ui/select'
import { ErrorState } from '@/components/common/States'
import { FIDELITY_FALLBACK, Lbl, sourceLabel } from '@/components/fanfic/bits'
import { fanficApi, fqk, qk } from '@/lib/api'
import type { Book, FanficDirectionId, FanficFidelity, FanficImportPart, FanficTemplateStyle, Gender } from '@/lib/types'
import { GENRES_FEMALE, GENRES_MALE, cn } from '@/lib/utils'

const IMPORT_PARTS: { value: FanficImportPart; label: string; desc: string }[] = [
  { value: 'characters', label: '原著角色', desc: '人物条目，带说话方式、口癖、能力边界' },
  { value: 'factions', label: '势力', desc: '势力条目' },
  { value: 'world', label: '世界观', desc: '「原著世界观」一条' },
  { value: 'locations', label: '地点', desc: '地点条目' },
]

export default function FanficNewPage() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const pre = Number(sp.get('source')) || 0
  const sources = useQuery({ queryKey: fqk.sources, queryFn: fanficApi.sources })
  const cat = useQuery({ queryKey: fqk.directions, queryFn: fanficApi.directions, staleTime: 3600_000 })

  const [sourceId, setSourceId] = useState<number>(pre)
  const [extra, setExtra] = useState<number[]>([])
  const [direction, setDirection] = useState<FanficDirectionId | null>(null)
  const [fidelity, setFidelity] = useState<FanficFidelity>('moderate')
  const [fidTouched, setFidTouched] = useState(false)
  const [ack, setAck] = useState(false)
  const [title, setTitle] = useState('')
  const [premise, setPremise] = useState('')
  const [notes, setNotes] = useState('')
  const [gender, setGender] = useState<Gender>('male')
  const [genre, setGenre] = useState('同人')
  const [created, setCreated] = useState<Book | null>(null)

  useEffect(() => { if (!sourceId && sources.data?.length && !pre) setSourceId(sources.data[0].id) }, [sources.data, sourceId, pre])
  const src = sources.data?.find((s) => s.id === sourceId) ?? null
  // v0.11.1 来源资料带热门模板时：展示该题材的常见写法，选中写进作者补充（notes）
  const tq = useQuery({ queryKey: fqk.templates, queryFn: fanficApi.templates, staleTime: 600_000, enabled: !!src?.template_id })
  const tpl = (src?.template_id && tq.data?.templates.find((t) => t.id === src.template_id)) || null
  const styleLine = (st: FanficTemplateStyle) => `【写法】${st.label}：${st.desc}`
  const styleOn = (st: FanficTemplateStyle) => notes.split('\n').includes(styleLine(st))
  const toggleStyle = (st: FanficTemplateStyle) => {
    const line = styleLine(st)
    if (styleOn(st)) { setNotes((n) => n.split('\n').filter((x) => x !== line).join('\n')); return }
    setNotes((n) => (n.trim() ? `${n.replace(/\s+$/, '')}\n${line}` : line).slice(0, 1000))
    if (!direction) pickDir(st.direction)
  }
  const dirs = cat.data?.directions ?? []
  const fids = cat.data?.fidelities?.length ? cat.data.fidelities : FIDELITY_FALLBACK
  const dir = dirs.find((d) => d.id === direction) ?? null
  const pickDir = (id: FanficDirectionId) => {
    setDirection(id)
    const d = dirs.find((x) => x.id === id)
    if (d && !fidTouched) setFidelity(d.suggested_fidelity)
  }
  const missing = useMemo(() => {
    const m: string[] = []
    if (!src) m.push('选原著')
    if (!direction) m.push('选方向')
    if (!ack) m.push('勾选版权声明')
    return m
  }, [src, direction, ack])

  const create = useMutation({
    mutationFn: () => fanficApi.createBook({
      title: title.trim() || undefined, genre: genre.trim() || '同人', gender, premise: premise.trim() || undefined,
      fanfic: { source_id: sourceId, direction: direction!, fidelity, extra_source_ids: extra.filter((x) => x !== sourceId).slice(0, 9), notes: notes.trim().slice(0, 1000) },
      copyright_ack: ack,
    }),
    meta: { errorTitle: '建书失败' },
    onSuccess: (b) => {
      qc.invalidateQueries({ queryKey: qk.books })
      qc.invalidateQueries({ queryKey: fqk.sources })
      setCreated(b)
      toast.success(`已创建《${b.title}》`)
      window.scrollTo({ top: 0 })
    },
  })

  if (created) return <Created book={created} onOpen={() => nav(`/books/${created.id}`)} />

  return (
    <div className="page max-w-[960px] !pb-0">
      <Link to={pre ? `/fanfic/sources/${pre}` : '/fanfic/sources'} className="focus-ring -ml-1 inline-flex h-10 items-center gap-0.5 rounded-md pr-2 text-[13px] text-muted-foreground hover:text-foreground"><ChevronLeft className="h-4 w-4" />同人</Link>
      <h1 className="mt-1 flex items-center gap-2 text-[22px] font-semibold tracking-tight"><BookPlus className="h-5 w-5 text-primary" />建同人书</h1>
      <p className="mt-1 text-[13px] text-muted-foreground">选原著、方向和遵循度。建好后写大纲、写章、审稿都会自动带上原著设定。</p>

      {/* 1 原著 */}
      <Step n={1} title="选原著" done={!!src}>
        {sources.isLoading ? <Skeleton className="h-10 rounded-md" /> : sources.isError ? <ErrorState error={sources.error} onRetry={() => sources.refetch()} /> : !sources.data?.length ? (
          <p className="rounded-xl border border-dashed px-4 py-6 text-center text-[13px] text-muted-foreground">还没有原著资料。<Link to="/fanfic" className="text-primary underline-offset-2 hover:underline">先去导入一份 →</Link></p>
        ) : (
          <div className="space-y-2">
            <Select value={sourceId ? String(sourceId) : null} onChange={(v) => setSourceId(Number(v) || 0)} placeholder="选择原著资料" className="h-10"
              options={sources.data.map((s) => ({ value: String(s.id), label: `${s.title || `原著 #${s.id}`}（${s.counts.characters} 角色 · 完整度 ${s.completeness}）` }))} />
            {src && (
              <div className="num flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted-foreground">
                <span className="whitespace-nowrap rounded bg-muted px-1.5 leading-[18px]">{sourceLabel(src)}</span>
                <span>{src.counts.characters} 角色</span><span>{src.counts.factions} 势力</span><span>{src.counts.timeline} 时间线节点</span><span>{src.counts.scenes} 名场面</span>
                <Link to={`/fanfic/sources/${src.id}`} className="inline-flex h-10 items-center text-primary underline-offset-2 hover:underline">查看/修改设定卡</Link>
              </div>
            )}
            {sources.data.length > 1 && (direction === 'crossover' || extra.length > 0) && (
              <div className="rounded-xl border bg-surface p-3">
                <Lbl hint="最多 9 部">联动原著（跨作品联动用）</Lbl>
                <div className="space-y-0.5">
                  {sources.data.filter((s) => s.id !== sourceId).map((s) => (
                    <label key={s.id} className="flex min-h-[40px] cursor-pointer items-center gap-2.5 rounded-lg px-2 hover:bg-muted/60">
                      <input type="checkbox" className="h-4 w-4 shrink-0 accent-[hsl(var(--primary))]" checked={extra.includes(s.id)}
                        onChange={() => setExtra((x) => (x.includes(s.id) ? x.filter((y) => y !== s.id) : x.length >= 9 ? x : [...x, s.id]))} />
                      <span className="min-w-0 flex-1 truncate text-[13.5px]">{s.title}</span>
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Step>

      {/* 2 方向 */}
      <Step n={2} title="选创作方向" done={!!direction}>
        {tpl && (
          <div className="mb-3 rounded-xl border bg-surface p-3" data-testid="template-styles">
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span className="text-[13.5px] font-semibold">《{tpl.title}》常见同人写法</span>
              <span className="text-[11.5px] text-muted-foreground">可多选，会写进「作者补充」；第一次选会顺带选上对应方向</span>
            </div>
            <div className="mt-2 grid gap-1.5 grid-cols-[repeat(auto-fill,minmax(min(100%,240px),1fr))]">
              {tpl.styles.map((st) => {
                const on = styleOn(st)
                const dl = dirs.find((d) => d.id === st.direction)?.label ?? st.direction
                return (
                  <button key={st.label} type="button" aria-pressed={on} onClick={() => toggleStyle(st)}
                    className={cn('focus-ring flex min-h-[56px] min-w-0 items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition', on ? 'border-primary bg-primary-soft/40' : 'hover:border-foreground/20')}>
                    <span className={cn('mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border', on ? 'border-primary bg-primary text-primary-foreground' : 'border-foreground/25')}>{on && <Check className="h-3 w-3" />}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className={cn('min-w-0 truncate text-[13px] font-semibold', on && 'text-primary')}>{st.label}</span>
                        <span className="ml-auto shrink-0 whitespace-nowrap rounded bg-muted px-1.5 text-[10.5px] leading-[17px] text-muted-foreground">{dl}</span>
                      </span>
                      <span className="mt-0.5 block text-[12px] leading-snug text-muted-foreground">{st.desc}</span>
                    </span>
                  </button>
                )
              })}
            </div>
          </div>
        )}
        {cat.isLoading ? <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,240px),1fr))]">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)}</div>
          : cat.isError ? <ErrorState error={cat.error} onRetry={() => cat.refetch()} /> : (
            <>
              <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,240px),1fr))]">
                {dirs.map((d) => {
                  const on = direction === d.id
                  return (
                    <button key={d.id} type="button" onClick={() => pickDir(d.id)} aria-pressed={on}
                      className={cn('focus-ring min-h-[88px] min-w-0 rounded-xl border bg-surface p-3 text-left transition', on ? 'border-primary bg-primary-soft/40 ring-2 ring-primary/15' : 'hover:border-foreground/20')}>
                      <span className="flex items-center gap-1.5">
                        <span className={cn('text-[14px] font-semibold', on && 'text-primary')}>{d.label}</span>
                        {on && <Check className="h-4 w-4 text-primary" />}
                        {tpl?.directions.includes(d.id) && <span className="shrink-0 whitespace-nowrap rounded bg-primary-soft px-1.5 text-[11px] leading-[18px] text-primary">推荐</span>}
                        <span className="ml-auto shrink-0 whitespace-nowrap rounded bg-muted px-1.5 text-[11px] leading-[18px] text-muted-foreground">建议{fids.find((f) => f.id === d.suggested_fidelity)?.label ?? d.suggested_fidelity}</span>
                      </span>
                      <span className="mt-1 block text-[12.5px] leading-relaxed text-muted-foreground">{d.desc}</span>
                    </button>
                  )
                })}
              </div>
              {dir && (
                <div className="mt-3 grid gap-3 rounded-xl border bg-subtle/50 p-3.5 sm:grid-cols-2">
                  <div className="min-w-0">
                    <div className="mb-1 text-[12.5px] font-semibold">写作要点</div>
                    <ul className="space-y-1 text-[12.5px] leading-relaxed">{dir.tips.map((t, i) => <li key={i} className="flex gap-1.5"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /><span className="min-w-0 break-words">{t}</span></li>)}</ul>
                  </div>
                  <div className="min-w-0">
                    <div className="mb-1 text-[12.5px] font-semibold">常见风险</div>
                    <ul className="space-y-1 text-[12.5px] leading-relaxed text-warning">{dir.risks.map((t, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words">{t}</span></li>)}</ul>
                  </div>
                </div>
              )}
            </>
          )}
      </Step>

      {/* 3 遵循度 */}
      <Step n={3} title="遵循度" done>
        <div className="grid gap-2 sm:grid-cols-3">
          {fids.map((f) => {
            const on = fidelity === f.id
            return (
              <button key={f.id} type="button" aria-pressed={on} onClick={() => { setFidelity(f.id); setFidTouched(true) }}
                className={cn('focus-ring min-h-[72px] min-w-0 rounded-xl border bg-surface p-3 text-left transition', on ? 'border-primary bg-primary-soft/40' : 'hover:border-foreground/20')}>
                <span className="flex items-center gap-1.5"><span className={cn('text-[14px] font-semibold', on && 'text-primary')}>{f.label}</span>{on && <Check className="h-4 w-4 text-primary" />}
                  <span className="num ml-auto text-[11.5px] text-muted-foreground">OOC 通过线 {f.pass_score}</span></span>
                <span className="mt-1 block text-[12.5px] leading-relaxed text-muted-foreground">{f.desc}</span>
              </button>
            )
          })}
        </div>
        {dir && fidelity !== dir.suggested_fidelity && <p className="mt-2 text-[12px] text-muted-foreground">「{dir.label}」一般建议「{fids.find((f) => f.id === dir.suggested_fidelity)?.label}」，按你的选择也可以。</p>}
      </Step>

      {/* 4 书名简介 */}
      <Step n={4} title="书名与简介" done={!!title.trim()}>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2"><Lbl>书名（可选）</Lbl><Input className="h-10" value={title} onChange={(e) => setTitle(e.target.value)} placeholder={src ? `如：${src.title}之……` : '书名'} /></div>
          <div>
            <Lbl>频道</Lbl>
            <Segmented block value={gender} onChange={setGender} className="h-10" options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
          </div>
          <div>
            <Lbl>题材</Lbl>
            <Select value={genre} onChange={(v) => setGenre(v || '同人')} className="h-10"
              options={['同人', ...(gender === 'male' ? GENRES_MALE : GENRES_FEMALE)].map((g) => ({ value: g, label: g }))} />
          </div>
          <div className="sm:col-span-2">
            <Lbl hint={dir ? <button type="button" onClick={() => setPremise((p) => (p.trim() ? `${p.trim()}\n${dir.template}` : dir.template))} className="focus-ring inline-flex h-10 items-center gap-1 rounded-md px-2 text-primary hover:bg-primary-soft/60"><Wand2 className="h-3.5 w-3.5" />填入方向模板</button> : undefined}>简介 / 创作想法</Lbl>
            <Textarea rows={4} value={premise} onChange={(e) => setPremise(e.target.value)} placeholder="一句话简介，或你想写的故事" />
          </div>
          <div className="sm:col-span-2">
            <Lbl hint={`${notes.length}/1000`}>作者补充（可选，会注入写作上下文）</Lbl>
            <Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value.slice(0, 1000))} placeholder="如：CP 固定为 A×B；不写原著第二卷之后的剧情" />
          </div>
        </div>
      </Step>

      {/* 5 版权 */}
      <Step n={5} title="版权声明" done={ack}>
        <div className="rounded-xl border bg-surface p-3.5">
          <p className="flex gap-2 text-[13px] leading-relaxed text-foreground/85"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span className="min-w-0 break-words">{cat.data?.copyright_notice ?? '同人创作仅供个人创作与学习交流使用，对外发布前请自行确认原著授权范围，不得用于商业用途。'}</span></p>
          <label className="mt-3 flex min-h-[44px] cursor-pointer items-center gap-2.5 rounded-lg bg-subtle px-3">
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-5 w-5 shrink-0 accent-[hsl(var(--primary))]" />
            <span className="text-[13.5px] font-medium">我已阅读并同意以上声明</span>
          </label>
        </div>
      </Step>

      <div className="sticky bottom-0 z-20 -mx-5 mt-8 border-t bg-background/95 backdrop-blur md:-mx-10">
        <div className="flex items-center gap-3 px-5 py-2.5 md:px-10">
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">{missing.length ? `还差：${missing.join('、')}` : '可以创建了'}</span>
          <Button variant="primary" className="h-11 shrink-0" disabled={missing.length > 0} loading={create.isPending} icon={<BookPlus className="h-4 w-4" />} onClick={() => create.mutate()}>创建同人书</Button>
        </div>
      </div>
    </div>
  )
}

function Step({ n, title, done, children }: { n: number; title: string; done?: boolean; children: React.ReactNode }) {
  return (
    <section className="mt-6 min-w-0">
      <h2 className="mb-2.5 flex items-center gap-2 text-[15px] font-semibold">
        <span className={cn('num flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[12px]', done ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground')}>{done ? <Check className="h-3.5 w-3.5" /> : n}</span>
        {title}
      </h2>
      {children}
    </section>
  )
}

function Created({ book, onOpen }: { book: Book; onOpen: () => void }) {
  const qc = useQueryClient()
  const [parts, setParts] = useState<FanficImportPart[]>(['characters'])
  const [res, setRes] = useState<{ n: number; skipped: number } | null>(null)
  const imp = useMutation({
    mutationFn: () => fanficApi.importCards(book.id, parts),
    meta: { errorTitle: '导入失败' },
    onSuccess: (r) => {
      setRes({ n: r.cards?.length ?? 0, skipped: r.skipped ?? 0 })
      qc.invalidateQueries({ queryKey: qk.cards(book.id) })
      qc.invalidateQueries({ queryKey: ['completeness', book.id] })
      toast.success(`已导入 ${r.cards?.length ?? 0} 条设定`)
    },
  })
  const toggle = (p: FanficImportPart) => setParts((ps) => (ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p]))
  return (
    <div className="page max-w-[640px]">
      <div className="rounded-2xl border bg-surface p-5">
        <div className="flex items-center gap-2 text-success"><Check className="h-5 w-5" /><span className="text-[15px] font-semibold">同人书已创建</span></div>
        <h1 className="mt-2 break-words text-[22px] font-semibold tracking-tight">{book.title}</h1>
        <p className="mt-1 text-[13px] text-muted-foreground">原著：{book.fanfic?.source_title ?? '—'}</p>

        <div className="mt-5 border-t pt-4">
          <h2 className="flex items-center gap-1.5 text-[14px] font-semibold"><Layers className="h-4 w-4 text-primary" />把原著设定导入设定库</h2>
          <p className="mt-0.5 text-[12px] text-muted-foreground">写前自动存设定快照；和已有条目重名的会跳过。</p>
          <div className="mt-2 space-y-0.5">
            {IMPORT_PARTS.map((p) => (
              <label key={p.value} className="flex min-h-[44px] cursor-pointer items-center gap-2.5 rounded-lg px-2 hover:bg-muted/60">
                <input type="checkbox" checked={parts.includes(p.value)} onChange={() => toggle(p.value)} className="h-4 w-4 shrink-0 accent-[hsl(var(--primary))]" />
                <span className="text-[13.5px]">{p.label}</span>
                <span className="min-w-0 flex-1 truncate text-right text-[11.5px] text-muted-foreground">{p.desc}</span>
              </label>
            ))}
          </div>
          {res ? (
            <div className="mt-2 rounded-lg bg-subtle px-3 py-2.5 text-[12.5px]">
              导入 <b className="num">{res.n}</b> 条{res.skipped > 0 && <>，跳过重名 <b className="num text-warning">{res.skipped}</b> 条</>}
              <Link to={`/books/${book.id}/bible`} className="ml-2 inline-flex h-10 items-center text-primary underline-offset-2 hover:underline">去设定库 →</Link>
            </div>
          ) : (
            <Button variant="soft" className="mt-2 h-11 w-full" disabled={!parts.length} loading={imp.isPending} icon={<BookOpenCheck className="h-4 w-4" />} onClick={() => imp.mutate()}>一键导入</Button>
          )}
        </div>

        <Button variant="primary" className="mt-5 h-11 w-full" icon={<ArrowRight className="h-4 w-4" />} onClick={onOpen}>去书概览</Button>
      </div>
    </div>
  )
}
