import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as P from '@radix-ui/react-popover'
import { Check, ChevronDown, ChevronRight, Layers3, Loader2, PenLine, Pencil, Sparkles } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CostButton } from '@/components/cost/CostButton'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Segmented } from '@/components/ui/tabs'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { OutlineNode } from '@/lib/types'
import { cn, countWords } from '@/lib/utils'

type V = 1 | 2 | 3
const LS = 'novelos-variants'

const QUICK_DIRECTIVES = [
  '开头前三句直接进高情绪冲突对白，不铺垫背景',
  '加强人物外貌、微动作与具体道具画面，适合短剧镜头',
  '全程大白话，杜绝专业黑话和翻译腔，每段不超过65字',
  '节奏再紧一拍，章末卡在反转刚露头的半拍上',
]

/** v0.20 写下一章：默认 1 版走 SSE 流式边写边显示、一次写成；选 2/3 版时走后台多版本任务 */
export function WriteNextButton({ bookId, size = 'md', className, buttonClassName, label = '写下一章', navigateOnDone = true }: {
  bookId: number; size?: 'sm' | 'md' | 'lg'; className?: string; navigateOnDone?: boolean
  buttonClassName?: string; label?: string
}) {
  const [variants, setVariants] = useState<V>(() => (Number(localStorage.getItem(LS)) as V) || 1)
  const [streaming, setStreaming] = useState(false)
  const [streamOpen, setStreamOpen] = useState(false)
  const [streamMeta, setStreamMeta] = useState<{ number?: number; title?: string; status?: string }>({})
  const [streamText, setStreamText] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  useEffect(() => () => { abortRef.current?.abort() }, [])

  const { start } = useJobs()
  const qc = useQueryClient()
  const job = useActiveJob(`write-next:${bookId}`)
  const batch = useActiveJob(`write-batch:${bookId}`)
  const nav = useNavigate()
  const set = (v: V) => { setVariants(v); localStorage.setItem(LS, String(v)) }

  const goStream = async (instruction = '') => {
    const ac = new AbortController()
    abortRef.current = ac
    setStreaming(true)
    setStreamOpen(true)
    setStreamText('')
    setStreamMeta({ status: '准备上下文…' })
    let finishedId: number | null = null
    try {
      await api.writeStream(bookId, instruction, (ev) => {
        if (ev.type === 'status') setStreamMeta((m) => ({ ...m, status: ev.message || '准备中…' }))
        else if (ev.type === 'start') setStreamMeta({ number: ev.number, title: ev.title, status: '正在写作…' })
        else if (ev.type === 'delta') setStreamText((t) => t + ev.text)
        else if (ev.type === 'done') {
          finishedId = ev.chapter_id
          setStreamMeta({ number: ev.number, title: ev.title, status: ev.committed ? '已写完并提交入账' : '已存为草稿' })
          qc.invalidateQueries({ queryKey: qk.chapters(bookId) })
          qc.invalidateQueries({ queryKey: qk.book(bookId) })
          qc.invalidateQueries({ queryKey: qk.outline(bookId) })
          const warn = (ev as any).commit_warning as string | undefined
          if (warn) toast.warning(`第 ${ev.number} 章已存为草稿`, { description: warn })
          else toast.success(`第 ${ev.number} 章《${ev.title}》已写完（${ev.words} 字）`)
        } else if (ev.type === 'error') {
          setStreamOpen(false)
          toast.error('写章失败', { description: ev.detail })
        }
      }, ac.signal)
      if (finishedId && navigateOnDone) {
        setStreamOpen(false)
        nav(`/books/${bookId}/chapters/${finishedId}`)
      }
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        setStreamOpen(false)
      } else {
        setStreamOpen(false)
        toast.error('写章失败', { description: e?.message })
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  const go = () => {
    if (variants === 1) {
      void goStream()
      return
    }
    start(api.writeNext(bookId, variants), {
      key: `write-next:${bookId}`,
      label: `写下一章（${variants} 个版本）`,
      successMsg: `新章节已生成 ${variants} 个版本，挑一个吧`,
      onSuccess: (j) => { if (navigateOnDone && j.result?.chapter_id) nav(`/books/${bookId}/chapters/${j.result.chapter_id}`) },
    })
  }

  const busy = !!job || streaming
  return (
    <>
      <div className={cn('inline-flex', className)}>
        <CostButton target={{ kind: 'chapter_write', bookId }} label={variants > 1 ? `写下一章（${variants} 个版本）` : '写下一章'} confirmLabel="开始写"
          variant="primary" size={size} loading={busy} disabled={!!batch} icon={<PenLine className="h-4 w-4" />} onRun={go} className={cn('rounded-r-none', buttonClassName)}>
          {streaming ? '边写边显…' : job ? `写作中 ${Math.round(job.progress)}%` : variants > 1 ? `${label} ×${variants}版` : label}
        </CostButton>
        <P.Root>
          <P.Trigger asChild>
            <Button variant="primary" size={size} disabled={busy || !!batch} className={cn('rounded-l-none border-l border-white/20 px-2', buttonClassName)} aria-label="版本数设置">
              <ChevronDown className="h-4 w-4" />
            </Button>
          </P.Trigger>
          <P.Portal>
            <P.Content align="end" sideOffset={6} className="z-50 w-[280px] rounded-xl bg-popover p-4 shadow-pop hairline animate-zoom-in">
              <div className="text-[13px] font-semibold">一次写几个版本？</div>
              <p className="mt-1 text-xs text-muted-foreground">1 版默认实时流式输出，一次写成。</p>
              <Segmented className="mt-3 w-full" value={String(variants) as '1' | '2' | '3'} onChange={(v) => set(Number(v) as V)} options={[{ value: '1', label: '1 版（流式）' }, { value: '2', label: '2 版' }, { value: '3', label: '3 版' }]} />
            </P.Content>
          </P.Portal>
        </P.Root>
      </div>

      <Dialog open={streamOpen} onOpenChange={(o) => { if (!o && streaming) abortRef.current?.abort(); setStreamOpen(o) }}>
        <DialogContent wide title={streamMeta.number ? `第 ${streamMeta.number} 章 · ${streamMeta.title || ''}` : '正在写下一章'}
          desc={`${streamMeta.status || ''} · 已生成 ${countWords(streamText)} 字`}
          footer={streaming
            ? <Button variant="ghost" onClick={() => abortRef.current?.abort()}>取消</Button>
            : <Button variant="primary" onClick={() => setStreamOpen(false)}>关闭</Button>}>
          <div className="max-h-[60vh] overflow-y-auto whitespace-pre-wrap rounded-xl bg-subtle/60 p-4 text-[14.5px] leading-8 text-foreground/90">
            {streamText || <span className="inline-flex items-center gap-2 text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{streamMeta.status || '等待模型输出…'}</span>}
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}

/** v0.21 续写审记 / 批量连写：写前核对并现场改接下来 1–5 章的起承转合章纲 + 临时补充写作要求 */
export function BatchWriteButton({ bookId, size = 'md' }: { bookId: number; size?: 'sm' | 'md' }) {
  const [open, setOpen] = useState(false)
  const [n, setN] = useState(3)
  const [instruction, setInstruction] = useState('')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [draft, setDraft] = useState<{ title: string; summary: string; stage_qi: string; stage_cheng: string; stage_zhuan: string; stage_he: string }>({
    title: '', summary: '', stage_qi: '', stage_cheng: '', stage_zhuan: '', stage_he: '',
  })
  const { start } = useJobs()
  const qc = useQueryClient()
  const job = useActiveJob(`write-batch:${bookId}`)
  const single = useActiveJob(`write-next:${bookId}`)

  const outlineQ = useQuery({
    queryKey: qk.outline(bookId),
    queryFn: () => api.outline(bookId),
    enabled: open,
  })
  const upcoming = useMemo(() => {
    const nodes = (outlineQ.data ?? [])
      .filter((x) => x.level === 'chapter' && x.status !== 'written' && !x.chapter_id)
      .sort((a, b) => a.order - b.order)
    return nodes.slice(0, n)
  }, [outlineQ.data, n])

  const openEditor = (node: OutlineNode) => {
    const b = (node.beats ?? {}) as Record<string, any>
    setEditingId(node.id)
    setDraft({
      title: node.title || '',
      summary: node.summary || '',
      stage_qi: String(b.stage_qi || ''),
      stage_cheng: String(b.stage_cheng || ''),
      stage_zhuan: String(b.stage_zhuan || ''),
      stage_he: String(b.stage_he || ''),
    })
  }

  const saveNode = useMutation({
    mutationFn: (node: OutlineNode) => {
      const nextBeats: Record<string, any> = {
        ...(node.beats ?? {}),
        stage_qi: draft.stage_qi.trim(),
        stage_cheng: draft.stage_cheng.trim(),
        stage_zhuan: draft.stage_zhuan.trim(),
        stage_he: draft.stage_he.trim(),
      }
      return api.updateOutline(node.id, { title: draft.title, summary: draft.summary, beats: nextBeats, instruction: '续写审记写前微调' })
    },
    meta: { errorTitle: '保存章纲失败' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.outline(bookId) })
      toast.success('章纲已更新，马上按新纲写作')
      setEditingId(null)
    },
  })

  const launch = () => {
    const inst = instruction.trim()
    setOpen(false)
    if (n === 1) {
      start(api.writeNext(bookId, 1, inst), {
        key: `write-next:${bookId}`,
        label: '续写下一章',
        successMsg: '新章节已写完',
      })
      return
    }
    start(api.writeBatch(bookId, n, inst), {
      key: `write-batch:${bookId}`,
      label: `续写连写 ${n} 章`,
      successMsg: `${n} 章已写完`,
    })
  }

  const appendChip = (chip: string) => {
    setInstruction((prev) => (prev.includes(chip) ? prev : prev.trim() ? `${prev.trim()}；${chip}` : chip))
  }

  return (
    <>
      <Button size={size} loading={!!job} disabled={!!single} icon={<Layers3 className="h-4 w-4" />} onClick={() => setOpen(true)}>
        {job ? `连写中 ${Math.round(job.progress)}%` : '续写审记'}
      </Button>
      <Sheet open={open} onOpenChange={setOpen} title="续写审记 · 批量连写" width={640}
        footer={
          <div className="flex w-full items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">写前确认章纲与节奏要求，按 1:2 比例扩写更稳</span>
            <div className="flex gap-2">
              <Button variant="ghost" onClick={() => setOpen(false)}>取消</Button>
              <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={launch}>开始连写 {n} 章</Button>
            </div>
          </div>
        }>
        <div className="space-y-5">
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[13px] font-medium">一次连写章数</span>
              <div className="flex gap-1.5">
                {[1, 2, 3, 5].map((k) => (
                  <button key={k} type="button" onClick={() => setN(k)}
                    className={cn('rounded-full px-2.5 py-0.5 text-xs font-medium transition',
                      n === k ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:text-foreground')}>
                    {k} 章
                  </button>
                ))}
              </div>
            </div>
            <div className="flex items-center gap-4">
              <input type="range" min={1} max={10} value={n} onChange={(e) => setN(Number(e.target.value))} className="flex-1 accent-[hsl(var(--primary))]" />
              <div className="num w-16 rounded-md bg-muted py-1 text-center text-base font-semibold">{n}<span className="ml-0.5 text-xs font-normal text-muted-foreground">章</span></div>
            </div>
          </div>

          <Field label="本轮临时写作要求（可选）" hint="例如强化开场对话冲突、镜头画面或收紧字数">
            <Textarea rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)}
              placeholder="例如：开头三句强情绪冲突对话；人物外貌与动作写具体；不要用专业黑话…" />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {QUICK_DIRECTIVES.map((chip) => (
                <button key={chip} type="button" onClick={() => appendChip(chip)}
                  className="rounded-full bg-subtle px-2.5 py-1 text-[11.5px] text-muted-foreground hairline transition hover:bg-muted hover:text-foreground">
                  + {chip.slice(0, 14)}…
                </button>
              ))}
            </div>
          </Field>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[13px] font-medium">即将写作的章纲预览（可现场微调）</span>
              <Badge tone="neutral">{upcoming.length} / {n} 章已备纲</Badge>
            </div>
            {outlineQ.isLoading ? (
              <div className="rounded-xl bg-subtle/60 p-4 text-xs text-muted-foreground">读取章纲中…</div>
            ) : upcoming.length === 0 ? (
              <div className="rounded-xl bg-subtle/60 p-4 text-xs text-muted-foreground">
                暂无待写章细纲（开写时将按滚动规划自动展开；你也可以先去「大纲 → 批量章纲」一次生成 10 章千字起承转合详纲）。
              </div>
            ) : (
              <div className="space-y-2">
                {upcoming.map((nd) => {
                  const b = (nd.beats ?? {}) as Record<string, any>
                  const isEd = editingId === nd.id
                  const hasStages = !!(b.stage_qi || b.stage_cheng || b.stage_zhuan || b.stage_he)
                  return (
                    <div key={nd.id} className="rounded-xl border bg-surface p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <Badge tone="primary" className="h-5 text-[11px]">第 {nd.order} 章</Badge>
                            <span className="truncate text-[13.5px] font-medium">{nd.title}</span>
                            {hasStages && <Badge tone="success" className="h-5 text-[10.5px]">起承转合</Badge>}
                          </div>
                          {!isEd && nd.summary && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{nd.summary}</p>}
                          {!isEd && hasStages && (
                            <div className="mt-1.5 space-y-0.5 text-[11.5px] text-foreground/75">
                              {b.stage_qi && <p className="line-clamp-1"><span className="font-medium text-primary">起：</span>{b.stage_qi}</p>}
                              {b.stage_zhuan && <p className="line-clamp-1"><span className="font-medium text-primary">转：</span>{b.stage_zhuan}</p>}
                            </div>
                          )}
                        </div>
                        <Button size="xs" variant="ghost" icon={isEd ? <ChevronRight className="h-3.5 w-3.5 rotate-90" /> : <Pencil className="h-3.5 w-3.5" />}
                          onClick={() => (isEd ? setEditingId(null) : openEditor(nd))}>
                          {isEd ? '收起' : '现场改纲'}
                        </Button>
                      </div>
                      {isEd && (
                        <div className="mt-3 space-y-2.5 border-t pt-3">
                          <Field label="章标题"><Input value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} /></Field>
                          <Field label="章概要"><Textarea rows={2} value={draft.summary} onChange={(e) => setDraft({ ...draft, summary: e.target.value })} /></Field>
                          <div className="grid gap-2 sm:grid-cols-2">
                            <Field label="起 · 入局冲突"><Textarea rows={2} value={draft.stage_qi} onChange={(e) => setDraft({ ...draft, stage_qi: e.target.value })} placeholder="开篇前三句冲突与画面…" /></Field>
                            <Field label="承 · 加压博弈"><Textarea rows={2} value={draft.stage_cheng} onChange={(e) => setDraft({ ...draft, stage_cheng: e.target.value })} placeholder="对手加码与信息差拉满…" /></Field>
                            <Field label="转 · 反转爆点"><Textarea rows={2} value={draft.stage_zhuan} onChange={(e) => setDraft({ ...draft, stage_zhuan: e.target.value })} placeholder="金手指/底牌亮出与打脸…" /></Field>
                            <Field label="合 · 收益与钩子"><Textarea rows={2} value={draft.stage_he} onChange={(e) => setDraft({ ...draft, stage_he: e.target.value })} placeholder="落袋收益与章末半拍卡点…" /></Field>
                          </div>
                          <div className="flex justify-end gap-2">
                            <Button size="xs" variant="ghost" onClick={() => setEditingId(null)}>取消</Button>
                            <Button size="xs" variant="primary" icon={<Check className="h-3.5 w-3.5" />} loading={saveNode.isPending} onClick={() => saveNode.mutate(nd)}>保存本章细纲</Button>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </Sheet>
    </>
  )
}
