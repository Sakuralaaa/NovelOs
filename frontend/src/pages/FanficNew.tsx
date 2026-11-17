import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowRight, BookOpenCheck, BookPlus, Check, ChevronLeft, CloudUpload, Download, Layers, ShieldCheck, UserCircle } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { JobInline } from '@/components/common/JobInline'
import { useActiveJob, useJobs } from '@/lib/jobs'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Select } from '@/components/ui/select'
import { ErrorState } from '@/components/common/States'
import { FIDELITY_FALLBACK, Lbl, sourceLabel } from '@/components/fanfic/bits'
import { fanficApi, fqk, qk } from '@/lib/api'
import type { Book, FanficDirectionId, FanficFidelity, FanficImportPart, FanficOcType, FanficPov, FanficProtagonist, FanficTemplateStyle, Gender } from '@/lib/types'
import { GENRES_FEMALE, GENRES_MALE, cn } from '@/lib/utils'

const IMPORT_PARTS: { value: FanficImportPart; label: string; desc: string }[] = [
  { value: 'characters', label: '原著角色', desc: '人物条目，带说话方式、口癖、能力边界' },
  { value: 'factions', label: '势力', desc: '势力条目' },
  { value: 'world', label: '世界观', desc: '「原著世界观」一条' },
  { value: 'locations', label: '地点', desc: '地点条目' },
]

type Draft = {
  sourceId: number; extra: number[]; direction: FanficDirectionId | null; fidelity: FanficFidelity; fidTouched: boolean
  title: string; premise: string; notes: string; gender: Gender; genre: string; slots: Record<string, string>
  prot: FanficProtagonist; pov: FanficPov; chapterWords: number; chapters: number; perVolume: number; wanben: boolean
}
const DRAFT_KEY = 'novelos.fanfic-draft'
const EMPTY: Draft = {
  sourceId: 0, extra: [], direction: null, fidelity: 'moderate', fidTouched: false, title: '', premise: '', notes: '', gender: 'male', genre: '同人',
  slots: {}, prot: { source: 'canon' }, pov: 'third_limited', chapterWords: 2000, chapters: 600, perVolume: 60, wanben: false,
}
const POV_FALLBACK: { id: FanficPov; label: string }[] = [
  { id: 'first', label: '第一人称主角' }, { id: 'third_limited', label: '第三人称主角限知' }, { id: 'third_multi', label: '第三人称多视角' },
  { id: 'canon_pov', label: '原著角色视角' }, { id: 'omniscient', label: '全知视角' },
]
const OC_FALLBACK: { id: FanficOcType; label: string }[] = [{ id: 'transmigrator', label: '穿越者' }, { id: 'native', label: '原住民原创角色' }, { id: 'soul_swap', label: '魂穿原著角色' }]
const loadDraft = (): Draft => { try { return { ...EMPTY, ...JSON.parse(localStorage.getItem(DRAFT_KEY) || '{}') } } catch { return EMPTY } }

export default function FanficNewPage() {
  const [sp] = useSearchParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const pre = Number(sp.get('source')) || 0
  const sources = useQuery({ queryKey: fqk.sources, queryFn: fanficApi.sources })
  const cat = useQuery({ queryKey: fqk.directions, queryFn: fanficApi.directions, staleTime: 3600_000 })
  const [f, setF] = useState<Draft>(() => ({ ...loadDraft(), ...(pre ? { sourceId: pre } : {}) }))
  const up = (p: Partial<Draft>) => setF((x) => ({ ...x, ...p }))
  useEffect(() => { localStorage.setItem(DRAFT_KEY, JSON.stringify(f)) }, [f])
  const [stepN, setStepN] = useState(1)
  const [ack, setAck] = useState(false)
  const [created, setCreated] = useState<Book | null>(null)
  const { sourceId, extra, direction, fidelity, notes } = f

  useEffect(() => { if (!sourceId && sources.data?.length && !pre) up({ sourceId: sources.data[0].id }) }, [sources.data, sourceId, pre])
  const src = sources.data?.find((s) => s.id === sourceId) ?? null
  const detail = useQuery({ queryKey: fqk.source(sourceId), queryFn: () => fanficApi.source(sourceId), enabled: !!sourceId })
  const timeline = detail.data?.cards.timeline ?? []
  const canonChars = detail.data?.cards.characters ?? []
  const tq = useQuery({ queryKey: fqk.templates, queryFn: fanficApi.templates, staleTime: 600_000, enabled: !!src?.template_id })
  const tpl = (src?.template_id && tq.data?.templates.find((t) => t.id === src.template_id)) || null
  const styleLine = (st: FanficTemplateStyle) => `【写法】${st.label}：${st.desc}`
  const styleOn = (st: FanficTemplateStyle) => notes.split('\n').includes(styleLine(st))
  const toggleStyle = (st: FanficTemplateStyle) => {
    const line = styleLine(st)
    if (styleOn(st)) { up({ notes: notes.split('\n').filter((x) => x !== line).join('\n') }); return }
    up({ notes: (notes.trim() ? `${notes.replace(/\s+$/, '')}\n${line}` : line).slice(0, 1000) })
    if (!direction) pickDir(st.direction)
  }
  const dirs = cat.data?.directions ?? []
  const fids = cat.data?.fidelities?.length ? cat.data.fidelities : FIDELITY_FALLBACK
  const povs = cat.data?.povs?.length ? cat.data.povs : POV_FALLBACK
  const ocTypes = cat.data?.oc_types?.length ? cat.data.oc_types : OC_FALLBACK
  const dir = dirs.find((d) => d.id === direction) ?? null
  const pickDir = (id: FanficDirectionId) => {
    const d = dirs.find((x) => x.id === id)
    setF((x) => ({ ...x, direction: id, slots: x.direction === id ? x.slots : {}, ...(d && !x.fidTouched ? { fidelity: d.suggested_fidelity } : {}),
      ...(['transmigration', 'multi_transmigration', 'system'].includes(id) && x.prot.source === 'canon' && !x.prot.canon_name ? { prot: { source: 'oc', oc_type: 'transmigrator' } } : {}) }))
  }
  const volumes = Math.max(1, Math.ceil(f.chapters / Math.max(5, f.perVolume)))
  const totalWords = f.chapters * f.chapterWords
  const missing = useMemo(() => {
    const m: string[] = []
    if (!src) m.push('选原著')
    if (!direction) m.push('选方向')
    if (!ack) m.push('勾选版权声明')
    return m
  }, [src, direction, ack])
  const slotText = dir?.slots?.length ? dir.slots.filter((x) => f.slots[x.key]?.trim()).map((x) => `${x.label}：${f.slots[x.key].trim()}`).join('；') : ''

  const create = useMutation({
    mutationFn: () => fanficApi.createBook({
      title: f.title.trim() || undefined, genre: f.genre.trim() || '同人', gender: f.gender,
      premise: [f.premise.trim(), slotText].filter(Boolean).join('\n') || undefined,
      fanfic: { source_id: sourceId, direction: direction!, fidelity, extra_source_ids: extra.filter((x) => x !== sourceId).slice(0, 9), notes: notes.trim().slice(0, 1000),
        protagonist: f.prot, pov: f.pov, slots: f.slots },
      copyright_ack: ack, target_words: totalWords, chapter_words: f.chapterWords, mode: f.wanben ? 'wanben' : 'serial', volume_chapters: f.perVolume,
    }),
    meta: { errorTitle: '建书失败' },
    onSuccess: (b) => {
      qc.invalidateQueries({ queryKey: qk.books })
      qc.invalidateQueries({ queryKey: fqk.sources })
      setCreated(b)
      localStorage.removeItem(DRAFT_KEY)
      toast.success(`已创建《${b.title}》`)
      window.scrollTo({ top: 0 })
    },
  })
  const exportDraft = () => {
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([JSON.stringify(f, null, 2)], { type: 'application/json' }))
    a.download = '同人立项草稿.json'
    a.click()
  }
  const importRef = useRef<HTMLInputElement>(null)
  const importDraft = (file?: File) => file && void file.text().then((t) => { try { setF({ ...EMPTY, ...JSON.parse(t) }); toast.success('已载入草稿') } catch { toast.error('文件不是有效的草稿') } })

  if (created) return <Created book={created} oc={f.prot.source === 'oc'} onOpen={() => nav(`/books/${created.id}`)} />

  const STEP_NAMES = ['选原著', '创作想法', '确认设置']
  return (
    <div className="page max-w-[960px] !pb-0">
      <Link to={pre ? `/fanfic/${pre}` : '/fanfic'} className="focus-ring -ml-1 inline-flex h-10 items-center gap-0.5 rounded-md pr-2 text-[13px] text-muted-foreground hover:text-foreground"><ChevronLeft className="h-4 w-4" />同人</Link>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <h1 className="flex items-center gap-2 text-[22px] font-semibold tracking-tight"><BookPlus className="h-5 w-5 text-primary" />建同人书</h1>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={exportDraft}>导出草稿</Button>
          <Button size="sm" variant="ghost" icon={<CloudUpload className="h-3.5 w-3.5" />} onClick={() => importRef.current?.click()}>导入草稿</Button>
          <input ref={importRef} type="file" accept=".json,application/json" className="hidden" onChange={(e) => { importDraft(e.target.files?.[0]); e.target.value = '' }} />
        </div>
      </div>
      <ol className="mt-4 flex items-center gap-1 overflow-x-auto pb-1 [scrollbar-width:none]">
        {STEP_NAMES.map((s2, i) => {
          const n = i + 1, on = n === stepN, ok = n === 1 || (n === 2 && !!src) || (n === 3 && !!src && !!direction)
          return (
            <li key={s2} className="flex shrink-0 items-center gap-1">
              {i > 0 && <span className={cn('h-px w-4 sm:w-8', ok ? 'bg-primary/40' : 'bg-border')} />}
              <button type="button" disabled={!ok || on} onClick={() => setStepN(n)}
                className={cn('flex h-10 items-center gap-2 rounded-full pl-1.5 pr-3.5 text-[13px] font-medium transition disabled:cursor-default', on ? 'bg-foreground text-background' : ok ? 'bg-surface hairline hover:bg-subtle' : 'text-muted-foreground/60')}>
                <span className={cn('num flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-semibold', on ? 'bg-background/15' : n < stepN ? 'bg-primary text-primary-foreground' : 'bg-muted')}>{n < stepN ? <Check className="h-3.5 w-3.5" /> : n}</span>{s2}
              </button>
            </li>
          )
        })}
      </ol>

      {stepN === 1 && (
        <Step n={1} title="选原著" done={!!src}>
          {sources.isLoading ? <Skeleton className="h-10 rounded-md" /> : sources.isError ? <ErrorState error={sources.error} onRetry={() => sources.refetch()} /> : !sources.data?.length ? (
            <p className="rounded-xl border border-dashed px-4 py-6 text-center text-[13px] text-muted-foreground">还没有原著资料。<Link to="/fanfic" className="text-primary underline-offset-2 hover:underline">先去导入一份 →</Link></p>
          ) : (
            <div className="space-y-4">
              <div>
                <Lbl>主原著</Lbl>
                <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))]">
                  {sources.data.map((s2) => (
                    <button key={s2.id} type="button" onClick={() => up({ sourceId: s2.id, extra: extra.filter((x) => x !== s2.id) })}
                      className={cn('min-h-[72px] min-w-0 rounded-xl border bg-surface p-3 text-left transition', sourceId === s2.id ? 'border-primary bg-primary-soft/40 ring-2 ring-primary/15' : 'hover:border-foreground/20')}>
                      <span className="flex items-center gap-1.5"><span className="min-w-0 flex-1 truncate text-[14px] font-semibold">{s2.title || `原著 #${s2.id}`}</span>{sourceId === s2.id && <Check className="h-4 w-4 text-primary" />}</span>
                      <span className="num mt-1 block text-[12px] text-muted-foreground">{sourceLabel(s2)} · {s2.counts.characters} 角色 · 完整度 {s2.completeness}</span>
                    </button>
                  ))}
                </div>
              </div>
              {sources.data.length > 1 && (
                <div>
                  <Lbl hint="最多 9 部">融合原著</Lbl>
                  <div className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(min(100%,220px),1fr))]">
                    {sources.data.filter((s2) => s2.id !== sourceId).map((s2) => {
                      const on = extra.includes(s2.id)
                      return (
                        <button key={s2.id} type="button" onClick={() => up({ extra: on ? extra.filter((y) => y !== s2.id) : extra.length >= 9 ? extra : [...extra, s2.id] })}
                          className={cn('flex min-h-[48px] min-w-0 items-center gap-2 rounded-xl border bg-surface px-3 text-left transition', on ? 'border-primary bg-primary-soft/40' : 'hover:border-foreground/20')}>
                          <span className={cn('flex h-4 w-4 shrink-0 items-center justify-center rounded border', on ? 'border-primary bg-primary text-primary-foreground' : 'border-foreground/25')}>{on && <Check className="h-3 w-3" />}</span>
                          <span className="min-w-0 flex-1 truncate text-[13.5px]">{s2.title}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}
              {src && <Link to={`/fanfic/${src.id}`} className="inline-flex h-10 items-center text-[13px] text-primary underline-offset-2 hover:underline">查看/修改设定卡</Link>}
            </div>
          )}
        </Step>
      )}

      {stepN === 2 && (
        <>
          <Step n={2} title="创作方向" done={!!direction}>
            {tpl && (
              <div className="mb-3 rounded-xl border bg-surface p-3" data-testid="template-styles">
                <div className="text-[13.5px] font-semibold">《{tpl.title}》常见同人写法</div>
                <div className="mt-2 grid gap-1.5 grid-cols-[repeat(auto-fill,minmax(min(100%,240px),1fr))]">
                  {tpl.styles.map((st) => {
                    const on = styleOn(st)
                    const dl = dirs.find((d) => d.id === st.direction)?.label ?? st.direction
                    return (
                      <button key={st.label} type="button" aria-pressed={on} onClick={() => toggleStyle(st)}
                        className={cn('focus-ring flex min-h-[56px] min-w-0 items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition', on ? 'border-primary bg-primary-soft/40' : 'hover:border-foreground/20')}>
                        <span className={cn('mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border', on ? 'border-primary bg-primary text-primary-foreground' : 'border-foreground/25')}>{on && <Check className="h-3 w-3" />}</span>
                        <span className="min-w-0 flex-1">
                          <span className="flex min-w-0 items-center gap-1.5"><span className={cn('min-w-0 truncate text-[13px] font-semibold', on && 'text-primary')}>{st.label}</span>
                            <span className="ml-auto shrink-0 whitespace-nowrap rounded bg-muted px-1.5 text-[10.5px] leading-[17px] text-muted-foreground">{dl}</span></span>
                          <span className="mt-0.5 block text-[12px] leading-snug text-muted-foreground">{st.desc}</span>
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
            {cat.isLoading ? <Skeleton className="h-40 rounded-xl" /> : cat.isError ? <ErrorState error={cat.error} onRetry={() => cat.refetch()} /> : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {dirs.map((d) => {
                    const on = direction === d.id
                    return (
                      <button key={d.id} type="button" onClick={() => pickDir(d.id)} aria-pressed={on} title={d.desc}
                        className={cn('inline-flex h-9 items-center gap-1 rounded-full border px-3 text-[13px] transition', on ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>
                        {d.label}{tpl?.directions.includes(d.id) && <span className="rounded bg-primary-soft px-1 text-[10.5px] text-primary">推荐</span>}
                      </button>
                    )
                  })}
                </div>
                {dir && (
                  <div className="mt-3 space-y-3 rounded-xl border bg-surface p-3.5">
                    <p className="text-[13px] text-foreground/80">{dir.desc}</p>
                    {!!dir.slots?.length && (
                      <div className="grid gap-2 sm:grid-cols-2">
                        {dir.slots.map((x) => (
                          <Field key={x.key} label={x.label}><Input className="h-10" value={f.slots[x.key] ?? ''} placeholder={x.placeholder || '可不填'} onChange={(e) => up({ slots: { ...f.slots, [x.key]: e.target.value } })} /></Field>
                        ))}
                      </div>
                    )}
                    <div className="grid gap-3 sm:grid-cols-2">
                      <ul className="space-y-1 text-[12.5px] leading-relaxed">{dir.tips.map((t, i) => <li key={i} className="flex gap-1.5"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /><span className="min-w-0 break-words">{t}</span></li>)}</ul>
                      <ul className="space-y-1 text-[12.5px] leading-relaxed text-warning">{dir.risks.map((t, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words">{t}</span></li>)}</ul>
                    </div>
                  </div>
                )}
              </>
            )}
          </Step>
          <Step n={3} title="主角" done={f.prot.source === 'canon' ? !!f.prot.canon_name : true}>
            <div className="space-y-3 rounded-xl border bg-surface p-3.5">
              <Segmented value={f.prot.source} onChange={(v) => up({ prot: v === 'oc' ? { source: 'oc', oc_type: 'transmigrator' } : { source: 'canon' } })}
                options={[{ value: 'canon', label: '原著角色' }, { value: 'oc', label: '原创主角' }]} />
              {f.prot.source === 'canon' ? (
                <Field label="哪个原著角色">
                  <Select value={f.prot.canon_name || null} onChange={(v) => up({ prot: { ...f.prot, canon_name: v || '' } })} placeholder="选择角色" className="h-10"
                    options={canonChars.map((c) => ({ value: c.name, label: c.role ? `${c.name}（${c.role}）` : c.name }))} />
                </Field>
              ) : (
                <>
                  <div className="flex flex-wrap gap-1.5">
                    {ocTypes.map((o) => <button key={o.id} type="button" onClick={() => up({ prot: { ...f.prot, oc_type: o.id } })}
                      className={cn('inline-flex h-9 items-center rounded-full border px-3 text-[13px]', f.prot.oc_type === o.id ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>{o.label}</button>)}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2">
                    <Field label="名字"><Input className="h-10" value={f.prot.name ?? ''} onChange={(e) => up({ prot: { ...f.prot, name: e.target.value } })} placeholder="可不填" /></Field>
                    {f.prot.oc_type === 'soul_swap' && (
                      <Field label="魂穿到谁身上">
                        <Select value={f.prot.canon_name || null} onChange={(v) => up({ prot: { ...f.prot, canon_name: v || '' } })} placeholder="选择原著角色" className="h-10"
                          options={canonChars.map((c) => ({ value: c.name, label: c.name }))} />
                      </Field>
                    )}
                  </div>
                  <Field label="描述"><Textarea rows={2} value={f.prot.brief ?? ''} onChange={(e) => up({ prot: { ...f.prot, brief: e.target.value } })} placeholder="可不填，建书后 AI 按原著补全" /></Field>
                </>
              )}
              <Field label="切入时间点">
                <Select value={f.prot.entry_event || null} onChange={(v) => up({ prot: { ...f.prot, entry_event: v || '' } })} placeholder={timeline.length ? '选原著时间线上的节点' : '原著资料没有时间线'} className="h-10"
                  options={timeline.map((t) => ({ value: t.event, label: `${t.order}. ${t.event}` }))} />
              </Field>
            </div>
          </Step>
          <Step n={4} title="简介与补充" done={!!f.premise.trim()}>
            <div className="space-y-3">
              <Textarea rows={3} value={f.premise} onChange={(e) => up({ premise: e.target.value })} placeholder="一句话简介，或你想写的故事" />
              <div><Lbl hint={`${notes.length}/1000`}>作者补充</Lbl>
                <Textarea rows={3} value={notes} onChange={(e) => up({ notes: e.target.value.slice(0, 1000) })} placeholder="如：CP 固定为 A×B；不写原著第二卷之后的剧情" /></div>
            </div>
          </Step>
        </>
      )}

      {stepN === 3 && (
        <>
          <Step n={1} title="遵循度" done>
            <div className="grid gap-2 sm:grid-cols-3">
              {fids.map((x) => {
                const on = fidelity === x.id
                return (
                  <button key={x.id} type="button" aria-pressed={on} onClick={() => up({ fidelity: x.id, fidTouched: true })}
                    className={cn('focus-ring min-h-[72px] min-w-0 rounded-xl border bg-surface p-3 text-left transition', on ? 'border-primary bg-primary-soft/40' : 'hover:border-foreground/20')}>
                    <span className="flex items-center gap-1.5"><span className={cn('text-[14px] font-semibold', on && 'text-primary')}>{x.label}</span>{on && <Check className="h-4 w-4 text-primary" />}
                      <span className="num ml-auto text-[11.5px] text-muted-foreground">OOC 通过线 {x.pass_score}</span></span>
                    <span className="mt-1 block text-[12.5px] leading-relaxed text-muted-foreground">{x.desc}</span>
                  </button>
                )
              })}
            </div>
          </Step>
          <Step n={2} title="视角与篇幅" done>
            <div className="space-y-4 rounded-xl border bg-surface p-3.5">
              <div className="flex flex-wrap gap-1.5">
                {povs.map((x) => <button key={x.id} type="button" onClick={() => up({ pov: x.id })}
                  className={cn('inline-flex h-9 items-center rounded-full border px-3 text-[13px]', f.pov === x.id ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>{x.label}</button>)}
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="每章字数"><Segmented block value={String(f.chapterWords)} onChange={(v) => up({ chapterWords: Number(v) })} options={[2000, 3000, 5000, 8000].map((n) => ({ value: String(n), label: String(n) }))} /></Field>
                <Field label="总章数"><Input type="number" min={10} max={5000} className="h-10 num" value={f.chapters} onChange={(e) => up({ chapters: Math.max(1, Number(e.target.value) || 0) })} /></Field>
                <Field label="每卷章数"><Input type="number" min={5} max={500} className="h-10 num" value={f.perVolume} onChange={(e) => up({ perVolume: Math.max(5, Number(e.target.value) || 0) })} /></Field>
              </div>
              <div className="num flex flex-wrap gap-2 text-[12.5px]">
                <span className="rounded-full bg-subtle px-3 py-1">{volumes} 卷</span>
                <span className="rounded-full bg-subtle px-3 py-1">约 {(totalWords / 10000).toFixed(totalWords >= 1_000_000 ? 0 : 1)} 万字</span>
              </div>
              <label className="flex min-h-[44px] cursor-pointer items-center justify-between gap-3 text-[13.5px] font-medium">完本模式<Switch checked={f.wanben} onCheckedChange={(v) => up({ wanben: v })} /></label>
            </div>
          </Step>
          <Step n={3} title="书名" done={!!f.title.trim()}>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="sm:col-span-2"><Input className="h-10" value={f.title} onChange={(e) => up({ title: e.target.value })} placeholder={src ? `如：${src.title}之……` : '书名'} /></div>
              <Segmented block value={f.gender} onChange={(g) => up({ gender: g })} className="h-10" options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
              <Select value={f.genre} onChange={(v) => up({ genre: v || '同人' })} className="h-10" options={['同人', ...(f.gender === 'male' ? GENRES_MALE : GENRES_FEMALE)].map((g) => ({ value: g, label: g }))} />
            </div>
          </Step>
          <Step n={4} title="版权声明" done={ack}>
            <div className="rounded-xl border bg-surface p-3.5">
              <p className="flex gap-2 text-[13px] leading-relaxed text-foreground/85"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" /><span className="min-w-0 break-words">{cat.data?.copyright_notice ?? '同人创作仅供个人创作与学习交流使用，对外发布前请自行确认原著授权范围，不得用于商业用途。'}</span></p>
              <label className="mt-3 flex min-h-[44px] cursor-pointer items-center gap-2.5 rounded-lg bg-subtle px-3">
                <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-5 w-5 shrink-0 accent-[hsl(var(--primary))]" />
                <span className="text-[13.5px] font-medium">我已阅读并同意以上声明</span>
              </label>
            </div>
          </Step>
        </>
      )}

      <div className="sticky bottom-0 z-20 -mx-5 mt-8 border-t bg-background/95 backdrop-blur md:-mx-10">
        <div className="flex items-center gap-3 px-5 py-2.5 md:px-10">
          {stepN > 1 && <Button variant="ghost" className="h-11" onClick={() => setStepN(stepN - 1)}>上一步</Button>}
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">{stepN === 3 ? (missing.length ? `还差：${missing.join('、')}` : '可以创建了') : ''}</span>
          {stepN < 3 ? (
            <Button variant="primary" className="h-11 shrink-0" disabled={stepN === 1 ? !src : !direction} icon={<ArrowRight className="h-4 w-4" />} onClick={() => setStepN(stepN + 1)}>下一步</Button>
          ) : (
            <Button variant="primary" className="h-11 shrink-0" disabled={missing.length > 0} loading={create.isPending} icon={<BookPlus className="h-4 w-4" />} onClick={() => create.mutate()}>创建同人书</Button>
          )}
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

function Created({ book, oc, onOpen }: { book: Book; oc: boolean; onOpen: () => void }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const ocKey = `fanfic-oc:${book.id}`
  const ocJob = useActiveJob(ocKey)
  const [ocRes, setOcRes] = useState<{ name: string; summary: string; ai_filled: string[] } | null>(null)
  const runOc = () => start(fanficApi.generateOc(book.id), { key: ocKey, label: '原创主角', successMsg: '原创主角已写进设定库',
    onSuccess: (j) => { setOcRes(j.result as { name: string; summary: string; ai_filled: string[] }); qc.invalidateQueries({ queryKey: qk.cards(book.id) }) } })
  const fired = useRef(false)
  useEffect(() => { if (oc && !fired.current) { fired.current = true; void runOc() } }, [oc]) // eslint-disable-line react-hooks/exhaustive-deps
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

        {oc && (
          <div className="mt-5 border-t pt-4">
            <h2 className="flex items-center gap-1.5 text-[14px] font-semibold"><UserCircle className="h-4 w-4 text-primary" />原创主角</h2>
            {ocJob ? <JobInline job={ocJob} className="mt-2" /> : ocRes ? (
              <div className="mt-2 rounded-lg bg-subtle px-3 py-2.5 text-[13px]"><b>{ocRes.name}</b>：{ocRes.summary}</div>
            ) : <Button variant="soft" className="mt-2 h-11 w-full" onClick={() => void runOc()}>按原著生成原创主角</Button>}
          </div>
        )}

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
