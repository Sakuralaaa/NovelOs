import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { AlertTriangle, ArrowRight, BookOpenCheck, BookPlus, Check, CloudUpload, Download, Globe2, Layers, Search, ShieldCheck, Sparkles, UserCircle, Wand2, Zap, RotateCcw } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { JobInline } from '@/components/common/JobInline'
import { useActiveJob, useJobs } from '@/lib/jobs'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { Select } from '@/components/ui/select'
import { ErrorState } from '@/components/common/States'
import { FIDELITY_FALLBACK, IDEAS, Lbl, sourceLabel } from '@/components/fanfic/bits'
import { fanficApi, fqk, qk } from '@/lib/api'
import type { Book, FanficDirection, FanficDirectionId, FanficSourceBrief, FanficTemplate, FanficFidelity, FanficImportPart, FanficOcType, FanficPov, FanficProtagonist, Gender } from '@/lib/types'
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
  const tq = useQuery({ queryKey: fqk.templates, queryFn: fanficApi.templates, staleTime: 600_000 })
  const [f, setF] = useState<Draft>(() => ({ ...loadDraft(), ...(pre ? { sourceId: pre } : {}) }))
  const up = (p: Partial<Draft>) => setF((x) => ({ ...x, ...p }))
  useEffect(() => { localStorage.setItem(DRAFT_KEY, JSON.stringify(f)) }, [f])
  const [ack, setAck] = useState(false)
  const [created, setCreated] = useState<Book | null>(null)
  const { sourceId, extra, direction, fidelity, notes } = f

  const src = sources.data?.find((s) => s.id === sourceId) ?? null
  const detail = useQuery({ queryKey: fqk.source(sourceId), queryFn: () => fanficApi.source(sourceId), enabled: !!src })
  const timeline = detail.data?.cards.timeline ?? []
  const canonChars = detail.data?.cards.characters ?? []
  const tpl = (src?.template_id && tq.data?.templates.find((t) => t.id === src.template_id)) || null
  const dirs = cat.data?.directions ?? []
  const fids = cat.data?.fidelities?.length ? cat.data.fidelities : FIDELITY_FALLBACK
  const povs = cat.data?.povs?.length ? cat.data.povs : POV_FALLBACK
  const ocTypes = cat.data?.oc_types?.length ? cat.data.oc_types : OC_FALLBACK
  const dir = dirs.find((d) => d.id === direction) ?? null
  const workName = src?.title || '原著'
  const pickDir = (id: FanficDirectionId) => {
    const d = dirs.find((x) => x.id === id)
    setF((x) => ({ ...x, direction: id, slots: {}, ...(d && !x.fidTouched ? { fidelity: d.suggested_fidelity } : {}),
      ...(['transmigration', 'multi_transmigration', 'system'].includes(id) && x.prot.source === 'canon' && !x.prot.canon_name ? { prot: { source: 'oc', oc_type: 'transmigrator' } } : {}) }))
  }
  /** 点想法/方向：把成型文字接到想法框末尾（已在框里就不重复加），并选上方向 */
  const addIdea = (text: string, id: FanficDirectionId) => {
    pickDir(id)
    setF((x) => x.premise.includes(text) ? x : ({ ...x, premise: x.premise.trim() ? `${x.premise.replace(/\s+$/, '')}\n\n${text}` : text }))
  }
  const ideaText = (t: string) => t.replace(/原著/g, workName)
  const dirText = (d: FanficDirection) => (d.template || d.desc).replace(/[（(][^）)]*[）)]/g, '').replace(/：；/g, '：……；').replace(/：$/, '：……')

  // v0.16 创作想法 AI 重写：把点选拼起来的几段想法、方向、原著拧成一段立意；结果先填进框里，可撤回
  const [rwIns, setRwIns] = useState('')
  const [rwPrev, setRwPrev] = useState<string | null>(null)
  const canRewrite = !!src && (!!f.premise.trim() || !!direction)
  const rewrite = useMutation({
    mutationFn: () => fanficApi.rewriteIdea({ source_id: sourceId, direction: direction ?? '', text: f.premise, instruction: rwIns, notes, protagonist: f.prot }),
    meta: { errorTitle: 'AI 重写失败' },
    onSuccess: (r) => { setRwPrev(f.premise); up({ premise: r.text }); toast.success('已改写，不满意可以撤回') },
  })

  const volumes = Math.max(1, Math.ceil(f.chapters / Math.max(5, f.perVolume)))
  const totalWords = f.chapters * f.chapterWords
  const missing = useMemo(() => {
    const m: string[] = []
    if (!src) m.push('选原著')
    if (!direction) m.push('选一个创作方向')
    if (!ack) m.push('勾选版权声明')
    return m
  }, [src, direction, ack])

  const create = useMutation({
    mutationFn: () => fanficApi.createBook({
      title: f.title.trim() || undefined, genre: f.genre.trim() || '同人', gender: f.gender,
      premise: f.premise.trim() || undefined,
      fanfic: { source_id: sourceId, direction: direction!, fidelity, extra_source_ids: extra.filter((x) => x !== sourceId).slice(0, 9), notes: notes.trim().slice(0, 1000),
        protagonist: f.prot, pov: f.pov, slots: {} },
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

  return (
    <div className="page max-w-[960px] !pb-0">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="flex items-center gap-2 text-[22px] font-semibold tracking-tight"><BookPlus className="h-5 w-5 text-primary" />建同人书</h1>
        <div className="ml-auto flex gap-1">
          <Button size="sm" variant="ghost" icon={<Download className="h-3.5 w-3.5" />} onClick={exportDraft}>导出草稿</Button>
          <Button size="sm" variant="ghost" icon={<CloudUpload className="h-3.5 w-3.5" />} onClick={() => importRef.current?.click()}>导入草稿</Button>
          <input ref={importRef} type="file" accept=".json,application/json" className="hidden" onChange={(e) => { importDraft(e.target.files?.[0]); e.target.value = '' }} />
        </div>
      </div>

      <Step n={1} title="原著" done={!!src}>
        <SourcePicker sources={sources.data ?? []} loading={sources.isLoading} templates={tq.data?.templates ?? []} canSearch={tq.data ? tq.data.search.available : true}
          selected={sourceId} onSelect={(id) => { const t = sources.data?.find((s2) => s2.id === id)?.title; setF((x) => ({ ...x, sourceId: id, extra: x.extra.filter((y) => y !== id), premise: t ? x.premise.replace(/《原著》/g, `《${t}》`) : x.premise })) }} />
        {src && (sources.data?.length ?? 0) > 1 && (
          <details className="mt-2 rounded-xl border bg-surface px-3 py-1.5">
            <summary className="flex min-h-[36px] cursor-pointer items-center text-[13px] text-foreground/80">融合其他原著{extra.length > 0 && <span className="num ml-1 text-primary">（已选 {extra.length}）</span>}</summary>
            <div className="flex flex-wrap gap-1.5 pb-2 pt-1">
              {sources.data!.filter((s2) => s2.id !== sourceId).map((s2) => {
                const on = extra.includes(s2.id)
                return <button key={s2.id} type="button" aria-pressed={on} onClick={() => up({ extra: on ? extra.filter((y) => y !== s2.id) : extra.length >= 9 ? extra : [...extra, s2.id] })}
                  className={cn('inline-flex h-9 max-w-full items-center gap-1 rounded-full border px-3 text-[13px]', on ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>
                  {on && <Check className="h-3.5 w-3.5 shrink-0" />}<span className="truncate">{s2.title}</span></button>
              })}
            </div>
          </details>
        )}
      </Step>

      <Step n={2} title="创作想法" done={!!direction && !!f.premise.trim()}>
        <div className="space-y-2.5">
          <div>
            <Lbl>常用想法</Lbl>
            <div className="flex flex-wrap gap-1.5">
              {tpl?.styles.map((st) => (
                <button key={`t-${st.label}`} type="button" title={st.desc} onClick={() => addIdea(`${st.label}：${st.desc}`, st.direction)}
                  className="inline-flex h-9 items-center gap-1 rounded-full border border-primary/30 bg-primary-soft/40 px-3 text-[13px] text-primary hover:bg-primary-soft"><Sparkles className="h-3.5 w-3.5" />{st.label}</button>
              ))}
              {IDEAS.map((it) => (
                <button key={it.label} type="button" title={ideaText(it.text)} onClick={() => addIdea(ideaText(it.text), it.direction)}
                  className="inline-flex h-9 items-center rounded-full border px-3 text-[13px] hover:bg-muted">{it.label}</button>
              ))}
            </div>
          </div>
          <div>
            <Lbl hint={dir ? dir.desc : '必选一个'}>方向</Lbl>
            {cat.isLoading ? <Skeleton className="h-9 rounded-full" /> : cat.isError ? <ErrorState error={cat.error} onRetry={() => cat.refetch()} /> : (
              <div className="flex flex-wrap gap-1.5">
                {dirs.map((d) => {
                  const on = direction === d.id
                  return (
                    <button key={d.id} type="button" aria-pressed={on} title={d.desc}
                      onClick={() => (on ? undefined : f.premise.trim() ? pickDir(d.id) : addIdea(dirText(d), d.id))}
                      className={cn('inline-flex h-9 items-center gap-1 rounded-full border px-3 text-[13px] transition', on ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>
                      {on && <Check className="h-3.5 w-3.5" />}{d.label}{tpl?.directions.includes(d.id) && <span className="rounded bg-primary-soft px-1 text-[10.5px] text-primary">推荐</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
          <Textarea rows={8} value={f.premise} onChange={(e) => up({ premise: e.target.value })} className="text-[14px] leading-relaxed"
            placeholder="写下你想写的故事：主角是谁、从哪里切入、想改变什么、想要什么爽点。也可以点上面的想法先填一段再改。" />
          <div className="flex flex-wrap items-center gap-2">
            <Input className="min-w-[200px] flex-1" value={rwIns} onChange={(e) => setRwIns(e.target.value.slice(0, 300))}
              placeholder="改写要求（可不填），如：主角更狠一点、节奏快一点" onKeyDown={(e) => { if (e.key === 'Enter' && canRewrite) rewrite.mutate() }} />
            {rwPrev !== null && <Button icon={<RotateCcw className="h-4 w-4" />} onClick={() => { up({ premise: rwPrev }); setRwPrev(null) }}>撤回</Button>}
            <Button variant="soft" icon={<Wand2 className="h-4 w-4" />} loading={rewrite.isPending} disabled={!canRewrite} onClick={() => rewrite.mutate()}>AI 重写</Button>
          </div>
          {dir && (dir.tips.length > 0 || dir.risks.length > 0) && (
            <details className="rounded-xl border bg-surface px-3 py-1.5">
              <summary className="flex min-h-[36px] cursor-pointer items-center text-[13px] text-foreground/80">「{dir.label}」写作要点</summary>
              <div className="grid gap-3 pb-2 pt-1 sm:grid-cols-2">
                <ul className="space-y-1 text-[12.5px] leading-relaxed">{dir.tips.map((t, i) => <li key={i} className="flex gap-1.5"><Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" /><span className="min-w-0 break-words">{t}</span></li>)}</ul>
                <ul className="space-y-1 text-[12.5px] leading-relaxed text-warning">{dir.risks.map((t, i) => <li key={i} className="flex gap-1.5"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /><span className="min-w-0 break-words">{t}</span></li>)}</ul>
              </div>
            </details>
          )}
          <div><Lbl hint={`${notes.length}/1000`}>作者补充</Lbl>
            <Textarea rows={2} value={notes} onChange={(e) => up({ notes: e.target.value.slice(0, 1000) })} placeholder="如：CP 固定为 A×B；不写原著第二卷之后的剧情" /></div>
        </div>
      </Step>

      <Step n={3} title="主角" done={f.prot.source === 'canon' ? !!f.prot.canon_name : true}>
        <div className="space-y-3 rounded-xl border bg-surface p-3.5">
          <div className="flex flex-wrap items-center gap-2">
            <Segmented value={f.prot.source} onChange={(v) => up({ prot: v === 'oc' ? { source: 'oc', oc_type: 'transmigrator' } : { source: 'canon' } })}
              options={[{ value: 'canon', label: '原著角色' }, { value: 'oc', label: '原创主角' }]} />
            {f.prot.source === 'oc' && ocTypes.map((o) => <button key={o.id} type="button" onClick={() => up({ prot: { ...f.prot, oc_type: o.id } })}
              className={cn('inline-flex h-9 items-center rounded-full border px-3 text-[13px]', f.prot.oc_type === o.id ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>{o.label}</button>)}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {f.prot.source === 'canon' ? (
              <Field label="哪个原著角色">
                <Select value={f.prot.canon_name || null} onChange={(v) => up({ prot: { ...f.prot, canon_name: v || '' } })} placeholder={src ? '选择角色' : '先选原著'} className="h-10"
                  options={canonChars.map((c) => ({ value: c.name, label: c.role ? `${c.name}（${c.role}）` : c.name }))} />
              </Field>
            ) : f.prot.oc_type === 'soul_swap' ? (
              <Field label="魂穿到谁身上">
                <Select value={f.prot.canon_name || null} onChange={(v) => up({ prot: { ...f.prot, canon_name: v || '' } })} placeholder="选择原著角色" className="h-10"
                  options={canonChars.map((c) => ({ value: c.name, label: c.name }))} />
              </Field>
            ) : (
              <Field label="名字"><Input className="h-10" value={f.prot.name ?? ''} onChange={(e) => up({ prot: { ...f.prot, name: e.target.value } })} placeholder="可不填" /></Field>
            )}
            <Field label="切入时间点">
              <Select value={f.prot.entry_event || null} onChange={(v) => up({ prot: { ...f.prot, entry_event: v || '' } })} placeholder={timeline.length ? '选原著时间线上的节点' : '原著资料没有时间线'} className="h-10"
                options={timeline.map((t) => ({ value: t.event, label: `${t.order}. ${t.event}` }))} />
            </Field>
          </div>
          {f.prot.source === 'oc' && (
            <Textarea rows={2} value={f.prot.brief ?? ''} onChange={(e) => up({ prot: { ...f.prot, brief: e.target.value } })} placeholder="主角描述，可不填，建书后 AI 按原著补全" />
          )}
        </div>
      </Step>

      <Step n={4} title="设置" done>
        <div className="space-y-2.5 rounded-xl border bg-surface p-3.5">
          <div className="grid gap-2 grid-cols-2 md:grid-cols-[1.4fr_1fr_1fr_auto_1fr]">
            <Input className="col-span-2 h-10 md:col-span-1" value={f.title} onChange={(e) => up({ title: e.target.value })} placeholder={src ? `书名，如：${src.title}之……` : '书名（可不填）'} aria-label="书名" />
            <Select value={fidelity} onChange={(v) => v && up({ fidelity: v as FanficFidelity, fidTouched: true })} className="h-10" options={fids.map((x) => ({ value: x.id, label: x.label }))} />
            <Select value={f.pov} onChange={(v) => v && up({ pov: v as FanficPov })} className="h-10" options={povs.map((x) => ({ value: x.id, label: x.label }))} />
            <Segmented value={f.gender} onChange={(g) => up({ gender: g })} className="h-10" options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
            <Select value={f.genre} onChange={(v) => up({ genre: v || '同人' })} className="h-10" options={['同人', ...(f.gender === 'male' ? GENRES_MALE : GENRES_FEMALE)].map((g) => ({ value: g, label: g }))} />
          </div>
          <div className="num grid items-center gap-2 grid-cols-2 md:grid-cols-[1fr_1fr_1fr_auto_auto]">
            <Select value={String(f.chapterWords)} onChange={(v) => v && up({ chapterWords: Number(v) })} className="h-10" options={[2000, 3000, 5000, 8000].map((n) => ({ value: String(n), label: `每章 ${n} 字` }))} />
            <label className="flex h-10 min-w-0 items-center gap-1.5 rounded-lg border bg-background px-2.5 text-[13px] text-muted-foreground">共<input type="number" min={10} max={5000} value={f.chapters} onChange={(e) => up({ chapters: Math.max(1, Number(e.target.value) || 0) })} className="min-w-0 flex-1 bg-transparent text-foreground outline-none" />章</label>
            <label className="flex h-10 min-w-0 items-center gap-1.5 rounded-lg border bg-background px-2.5 text-[13px] text-muted-foreground">每卷<input type="number" min={5} max={500} value={f.perVolume} onChange={(e) => up({ perVolume: Math.max(5, Number(e.target.value) || 0) })} className="min-w-0 flex-1 bg-transparent text-foreground outline-none" />章</label>
            <span className="whitespace-nowrap text-[12.5px] text-muted-foreground">{volumes} 卷 · 约 {(totalWords / 10000).toFixed(totalWords >= 1_000_000 ? 0 : 1)} 万字</span>
            <label className="flex h-10 cursor-pointer items-center gap-2 whitespace-nowrap text-[13px]">完本模式<Switch checked={f.wanben} onCheckedChange={(v) => up({ wanben: v })} /></label>
          </div>
        </div>
      </Step>

      <div className="sticky bottom-0 z-20 -mx-5 mt-8 border-t bg-background/95 backdrop-blur md:-mx-10">
        <div className="flex flex-wrap items-center gap-3 px-5 py-2.5 md:px-10">
          <label className="flex min-h-[44px] cursor-pointer items-center gap-2 text-[13px]" title={cat.data?.copyright_notice ?? ''}>
            <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="h-4.5 w-4.5 shrink-0 accent-[hsl(var(--primary))]" />
            <ShieldCheck className="h-4 w-4 text-primary" />同意同人版权声明
          </label>
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-muted-foreground">{missing.length ? `还差：${missing.join('、')}` : ''}</span>
          <Button variant="primary" className="h-11 shrink-0" disabled={missing.length > 0} loading={create.isPending} icon={<BookPlus className="h-4 w-4" />} onClick={() => create.mutate()}>创建同人书</Button>
        </div>
      </div>
    </div>
  )
}

const SRC_KEY = 'fanfic-source-create'
const normName = (s: string) => s.replace(/[\s·・:：《》]/g, '').toLowerCase()

/** v0.14.0 选原著：就地搜作品名，已有资料 / 热门原著点一下即选；没有资料就后台联网取材，取完自动选上 */
function SourcePicker({ sources, loading, templates, canSearch, selected, onSelect }: {
  sources: FanficSourceBrief[]; loading: boolean; templates: FanficTemplate[]; canSearch: boolean; selected: number; onSelect: (id: number) => void
}) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const running = useActiveJob(SRC_KEY)
  const [kw, setKw] = useState('')
  const k = normName(kw)
  const sel = sources.find((s) => s.id === selected) ?? null
  const mine = sources.filter((s) => !k || normName(s.title).includes(k))
  const hot = templates.filter((t) => !k || [t.title, ...t.aliases, ...t.characters].some((x) => normName(x).includes(k))).slice(0, k ? 12 : 16)
  const findSource = (title: string, tplId?: string) => sources.find((s) => (tplId && s.template_id === tplId) || normName(s.title) === normName(title))
  const fetchSource = async (title: string, t?: FanficTemplate) => {
    if (!canSearch) { toast.error('还没配置联网搜索', { description: '在 设置 → 任务路由 → 联网搜索 选好模型后再取材，或先导入原著文本。' }); return }
    await start(fanficApi.createSource({ source: 'search', title, depth: 'standard', focus: t ? t.characters.slice(0, 2) : undefined, template_id: t?.id }), {
      label: `联网取材《${title}》`, key: SRC_KEY, successMsg: `《${title}》资料已取好`,
      onSuccess: (j) => {
        const id = j.result?.source_id ?? j.result?.source?.id
        void qc.invalidateQueries({ queryKey: fqk.sources }).then(() => { if (id) onSelect(id) })
        setKw('')
      },
    })
  }
  const pickHot = (t: FanficTemplate) => { const s = findSource(t.title, t.id); if (s) onSelect(s.id); else void fetchSource(t.title, t) }
  const exact = k && (sources.some((s) => normName(s.title) === k) || templates.some((t) => normName(t.title) === k))

  return (
    <div className="min-w-0 space-y-2.5">
      {sel && (
        <div className="flex min-w-0 items-center gap-2 rounded-xl border border-primary bg-primary-soft/40 px-3 py-2.5">
          <Check className="h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0 flex-1 truncate text-[14px] font-semibold">{sel.title}</span>
          <span className="num hidden shrink-0 text-[12px] text-muted-foreground sm:inline">{sourceLabel(sel)} · {Object.values(sel.entry_counts ?? {}).reduce((a, b) => a + b, 0)} 条设定{sel.used_by.length ? ` · ${sel.used_by.length} 本书在用` : ''}</span>
          <Link to={`/fanfic/sources/${sel.id}`} className="shrink-0 text-[12.5px] text-primary hover:underline">看资料</Link>
        </div>
      )}
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input value={kw} onChange={(e) => setKw(e.target.value)} placeholder="搜作品名 / 人物，如：斗罗大陆、唐三" className="h-10 pl-8" aria-label="搜原著"
          onKeyDown={(e) => { if (e.key === 'Enter' && kw.trim() && !running) { const s = findSource(kw.trim()); if (s) onSelect(s.id); else { const t = templates.find((x) => normName(x.title) === k); void fetchSource(t?.title ?? kw.trim(), t) } } }} />
      </div>
      {running && <JobInline job={running} />}
      {k && !exact && !running && (
        <button type="button" onClick={() => void fetchSource(kw.trim())}
          className="focus-ring flex min-h-[44px] w-full items-center gap-2 rounded-xl border border-dashed px-3 text-left text-[13.5px] hover:border-primary hover:text-primary">
          <Globe2 className="h-4 w-4 shrink-0" /><span className="min-w-0 flex-1 truncate">联网取材《{kw.trim()}》，取完自动选上</span><ArrowRight className="h-4 w-4 shrink-0" />
        </button>
      )}
      {loading ? <Skeleton className="h-10 rounded-md" /> : mine.length > 0 && (
        <div>
          <Lbl>我的原著资料</Lbl>
          <div className="flex flex-wrap gap-1.5">
            {mine.map((s) => <button key={s.id} type="button" aria-pressed={s.id === selected} onClick={() => onSelect(s.id)}
              className={cn('inline-flex h-9 max-w-full items-center gap-1 rounded-full border px-3 text-[13px]', s.id === selected ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>
              {s.id === selected && <Check className="h-3.5 w-3.5 shrink-0" />}<span className="truncate">{s.title}</span></button>)}
          </div>
        </div>
      )}
      {hot.length > 0 && (
        <div>
          <Lbl>热门原著</Lbl>
          <div className="flex flex-wrap gap-1.5">
            {hot.map((t) => {
              const has = !!findSource(t.title, t.id)
              return <button key={t.id} type="button" disabled={!!running} title={t.intro} onClick={() => pickHot(t)}
                className="inline-flex h-9 items-center gap-1 rounded-full border px-3 text-[13px] hover:bg-muted disabled:opacity-50">
                {t.title}{!has && <Globe2 className="h-3.5 w-3.5 text-muted-foreground" />}</button>
            })}
          </div>
        </div>
      )}
      <p className="text-[12px] text-muted-foreground">有原著文本？<Link to="/fanfic/import" className="text-primary hover:underline">粘贴或上传 TXT 提炼</Link></p>
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

        <div className="mt-5 grid gap-2 sm:grid-cols-2">
          <Button className="h-11" icon={<ArrowRight className="h-4 w-4" />} onClick={onOpen}>去书概览</Button>
          <Link to={`/books/${book.id}/auto`} className="focus-ring inline-flex h-11 items-center justify-center gap-1.5 rounded-lg bg-primary px-4 text-[14px] font-medium text-primary-foreground hover:bg-primary/90"><Zap className="h-4 w-4" />一键成书</Link>
        </div>
      </div>
    </div>
  )
}
