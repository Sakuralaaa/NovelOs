import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Check, ClipboardPaste, Feather, Info, Save, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Segmented } from '@/components/ui/tabs'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import { analyzeText } from '@/lib/textAnalysis'
import type { Style } from '@/lib/types'
import { cn, countWords } from '@/lib/utils'

const LIMIT = 5000
const TONES = ['冷峻写实', '轻松幽默', '热血燃', '细腻温柔', '悬疑压抑', '古风典雅', '爽快直白']
const pctFmt = (v: unknown) => (typeof v === 'number' ? `${Math.round(v * (v <= 1 ? 100 : 1))}%` : '—')

export default function StylePage() {
  const id = useBookId()
  const q = useQuery({ queryKey: qk.style(id), queryFn: () => api.style(id) })
  const [f, setF] = useState<Style | null>(null)
  const [dirty, setDirty] = useState(false)
  const qc = useQueryClient()
  const { start } = useJobs()
  const job = useActiveJob(`style:${id}`)

  useEffect(() => { if (q.data && !dirty) setF(q.data) }, [q.data, dirty])

  const save = useMutation({
    mutationFn: (s: Style) => api.saveStyle(id, { sample_text: s.sample_text, voice_notes: s.voice_notes, pov: s.pov, tone: s.tone }),
    meta: { errorTitle: '保存失败' },
    onSuccess: (s) => { qc.setQueryData(qk.style(id), s); setDirty(false) },
  })

  const words = countWords(f?.sample_text ?? '')
  const over = words > LIMIT
  const local = useMemo(() => (f?.sample_text ? analyzeText(f.sample_text) : null), [f?.sample_text])

  if (q.isLoading || !f) return <div className="page"><Skeleton className="h-8 w-48" /><div className="mt-6 grid gap-6 lg:grid-cols-2"><Skeleton className="h-[520px] rounded-xl" /><Skeleton className="h-[520px] rounded-xl" /></div></div>
  if (q.error) return <div className="page"><ErrorState error={q.error} onRetry={() => q.refetch()} /></div>

  const set = (p: Partial<Style>) => { setF({ ...f, ...p }); setDirty(true) }
  const extract = async () => {
    if (!f.sample_text.trim()) return toast.error('先粘贴一段范文')
    if (over) return toast.error(`范文最多 ${LIMIT} 字，当前 ${words} 字`)
    if (dirty) await save.mutateAsync(f)
    start(api.extractStyle(id), { key: `style:${id}`, label: '提炼文风', successMsg: '文风已提炼，之后写作都会参照它' })
  }
  const ex = f.extracted

  return (
    <div className="page">
      <BookCrumb bookId={id} page="文风" />
      <PageHeader className="mt-3" title="文风" desc="贴一段你喜欢的文字（自己写的或喜欢的作者），AI 会学习它的句子长短、描写密度和对话写法，让这本书读起来像“人写的”。"
        actions={<>
          <Button icon={dirty ? <Save className="h-4 w-4" /> : <Check className="h-4 w-4" />} disabled={!dirty} loading={save.isPending} onClick={() => save.mutate(f, { onSuccess: () => toast.success('已保存') })}>{dirty ? '保存' : '已保存'}</Button>
          <Button variant="primary" loading={!!job} icon={<Sparkles className="h-4 w-4" />} onClick={extract}>提炼文风</Button>
        </>} />
      {job && <JobInline job={job} className="mb-5" />}

      <div className="grid gap-6 lg:grid-cols-[1.1fr_1fr]">
        <Card>
          <CardHeader title="范文与设定" icon={<Feather className="h-4 w-4" />} />
          <CardBody className="space-y-5">
            <div>
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[13px] font-medium">范文</span>
                <span className={cn('num text-xs', over ? 'font-medium text-danger' : 'text-muted-foreground')}>{words.toLocaleString()} / {LIMIT.toLocaleString()} 字</span>
              </div>
              <div className="relative">
                <Textarea value={f.sample_text} onChange={(e) => set({ sample_text: e.target.value })}
                  className={cn('min-h-[300px] resize-y font-serif text-[14.5px] leading-[1.9]', over && 'border-danger focus:border-danger')}
                  placeholder="把范文粘贴到这里。建议 1000–3000 字、包含对话和场景描写的一段，效果最好。" />
                {!f.sample_text && (
                  <button onClick={async () => { try { const t = await navigator.clipboard.readText(); if (t) set({ sample_text: t }) } catch { toast.info('请用 Ctrl/⌘+V 粘贴') } }}
                    className="absolute bottom-3 right-3 flex items-center gap-1.5 rounded-md bg-muted px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground">
                    <ClipboardPaste className="h-3.5 w-3.5" />从剪贴板粘贴
                  </button>
                )}
              </div>
              <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted"><div className={cn('h-full rounded-full transition-all', over ? 'bg-danger' : 'bg-primary/60')} style={{ width: `${Math.min(100, (words / LIMIT) * 100)}%` }} /></div>
              {over && <p className="mt-1.5 text-xs text-danger">超出 {words - LIMIT} 字，请删减后再提炼。</p>}
            </div>
            <div className="grid gap-4 sm:grid-cols-[auto_1fr]">
              <Field label="叙述视角">
                <Segmented value={f.pov} onChange={(v) => set({ pov: v })} options={[{ value: 'first', label: '第一人称' }, { value: 'third', label: '第三人称' }]} />
              </Field>
              <Field label="基调">
                <Input value={f.tone} onChange={(e) => set({ tone: e.target.value })} placeholder="例如：冷峻写实" />
              </Field>
            </div>
            <div className="-mt-2 flex flex-wrap gap-1.5">
              {TONES.map((t) => <button key={t} onClick={() => set({ tone: t })} className={cn('h-6 rounded-full border px-2.5 text-xs transition', f.tone === t ? 'border-primary bg-primary-soft text-primary' : 'text-muted-foreground hover:text-foreground')}>{t}</button>)}
            </div>
            <Field label="文风笔记" hint="写给 AI 的额外要求">
              <Textarea value={f.voice_notes} onChange={(e) => set({ voice_notes: e.target.value })} className="min-h-[90px]" placeholder="例如：多用动作代替心理描写；对白短，前后要有动作或环境；不要用“不禁”“仿佛”。" />
            </Field>
          </CardBody>
        </Card>

        <div className="space-y-6">
          {ex ? <Extracted ex={ex} /> : (
            <EmptyState kind="style" title="还没有提炼结果" desc="粘贴范文后点「提炼文风」，这里会显示句长分布、对话比例、描写密度和写作规则。" />
          )}
          {local && (
            <Card>
              <CardHeader title="范文实时速览" desc="前端即时估算，仅供参考" icon={<Info className="h-4 w-4" />} />
              <CardBody>
                <div className="grid grid-cols-3 gap-3 text-center">
                  <Mini label="平均句长" value={`${local.avg_sentence_len.toFixed(1)} 字`} />
                  <Mini label="对话占比" value={pctFmt(local.dialogue_ratio)} />
                  <Mini label="短句占比" value={pctFmt(local.short_sentence_ratio)} />
                </div>
                <Hist className="mt-4" data={local.sentence_hist} />
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function Mini({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-subtle px-2 py-2.5"><div className="text-[11.5px] text-muted-foreground">{label}</div><div className="num mt-0.5 text-[17px] font-semibold">{value}</div></div>
}

export function Hist({ data, className }: { data: { bucket: string; ratio: number }[]; className?: string }) {
  const max = Math.max(0.01, ...data.map((d) => d.ratio))
  return (
    <div className={className}>
      <div className="mb-2 text-[12px] font-medium text-muted-foreground">句长分布（字）</div>
      <div className="flex h-[110px] items-end gap-2">
        {data.map((d, i) => (
          <div key={d.bucket} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
            <span className="num text-[10.5px] text-muted-foreground">{Math.round(d.ratio * 100)}%</span>
            <motion.div initial={{ height: 0 }} animate={{ height: `${(d.ratio / max) * 78}%` }} transition={{ delay: i * 0.05, duration: 0.5 }}
              className="w-full rounded-t-md bg-gradient-to-t from-primary/70 to-violet-400/70" style={{ minHeight: 2 }} />
            <span className="text-[11px] text-muted-foreground">{d.bucket}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

const TEXT_KEYS: [string, string][] = [['summary', '整体写法'], ['dialogue_style', '对话写法'], ['description_style', '描写方式'], ['narration', '叙述方式'], ['rhythm', '节奏']]
const LIST_KEYS: [string, string, 'ok' | 'no'][] = [['techniques', '可模仿的手法', 'ok'], ['rules', '写作规则', 'ok'], ['avoid', '刻意避开', 'no']]

/** 兼容两种结构：后端 {stats, llm, excerpt}，或扁平对象 */
function Extracted({ ex }: { ex: Record<string, any> }) {
  const st: Record<string, any> = ex.stats && typeof ex.stats === 'object' ? ex.stats : ex
  const llm: Record<string, any> = ex.llm && typeof ex.llm === 'object' ? ex.llm : ex
  const rawHist = st.sentence_len_hist
  const hist: { bucket: string; ratio: number }[] | null = Array.isArray(rawHist)
    ? rawHist.map((d: any) => ({ bucket: String(d.bucket ?? d.label ?? d.range ?? ''), ratio: Number(d.ratio ?? d.value ?? 0) }))
    : rawHist && typeof rawHist === 'object' && Object.keys(rawHist).length
      ? Object.entries(rawHist).map(([k, v]) => ({ bucket: k, ratio: Number(v) }))
      : null
  const dr = typeof st.dialogue_ratio === 'number' ? st.dialogue_ratio : null
  const density = typeof st.descriptor_per_k === 'number' ? `${st.descriptor_per_k}/千字` : pctFmt(st.description_density)
  const texts = TEXT_KEYS.filter(([k]) => typeof llm[k] === 'string' && llm[k])
  const lists = LIST_KEYS.filter(([k]) => Array.isArray(llm[k]) && llm[k].length)
  const [showEx, setShowEx] = useState(false)
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <Card>
        <CardHeader title="提炼结果" desc="写作每一章时都会注入这些特征" icon={<Sparkles className="h-4 w-4 text-primary" />} action={<Badge tone="success" dot>已生效</Badge>} />
        <CardBody className="space-y-5">
          <div className="grid grid-cols-3 gap-2.5">
            <Mini label="平均句长" value={typeof st.avg_sentence_len === 'number' ? `${st.avg_sentence_len} 字` : '—'} />
            <Mini label="短句占比" value={pctFmt(st.short_sentence_ratio)} />
            <Mini label="对话比例" value={pctFmt(st.dialogue_ratio)} />
            <Mini label="描写密度" value={density} />
            <Mini label="裸对白" value={pctFmt(st.bare_dialogue_ratio)} />
            <Mini label="概述占比" value={pctFmt(st.summary_ratio)} />
          </div>
          {hist && <Hist data={hist} />}
          {dr !== null && (
            <div>
              <div className="mb-1.5 flex justify-between text-[12px] text-muted-foreground"><span>叙述 {Math.round((1 - dr) * 100)}%</span><span>对话 {Math.round(dr * 100)}%</span></div>
              <div className="flex h-2.5 overflow-hidden rounded-full"><div className="bg-primary/60" style={{ width: `${(1 - dr) * 100}%` }} /><div className="flex-1 bg-amber-400/80" /></div>
            </div>
          )}
          {texts.length > 0 && (
            <div className="space-y-2.5">
              {texts.map(([k, l]) => (
                <div key={k} className="rounded-lg bg-subtle px-3.5 py-3">
                  <div className="text-[12px] font-medium text-muted-foreground">{l}</div>
                  <p className="mt-1 text-[13.5px] leading-relaxed">{String(llm[k])}</p>
                </div>
              ))}
            </div>
          )}
          {lists.map(([k, l, tone]) => (
            <div key={k}>
              <div className="mb-2 text-[12px] font-medium text-muted-foreground">{l}</div>
              <ul className="space-y-1.5">
                {(llm[k] as string[]).map((r, i) => (
                  <li key={i} className="flex gap-2 text-[13.5px] leading-relaxed">
                    {tone === 'ok' ? <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-success" /> : <span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-danger/70" />}{r}
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {typeof ex.excerpt === 'string' && ex.excerpt && (
            <div className="border-t pt-4">
              <button onClick={() => setShowEx(!showEx)} className="text-[12.5px] font-medium text-primary hover:underline">
                {showEx ? '收起' : '查看'}选作范例的片段{typeof ex.excerpt_words === 'number' ? `（${ex.excerpt_words} 字）` : ''}
              </button>
              {showEx && <p className="prose-zh mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-lg bg-subtle p-3 font-serif text-[13.5px]">{ex.excerpt}</p>}
            </div>
          )}
        </CardBody>
      </Card>
    </motion.div>
  )
}
