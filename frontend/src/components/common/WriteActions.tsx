import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import * as P from '@radix-ui/react-popover'
import { ChevronDown, Layers3, Loader2, PenLine } from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { CostButton } from '@/components/cost/CostButton'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Segmented } from '@/components/ui/tabs'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import { cn, countWords } from '@/lib/utils'

type V = 1 | 2 | 3
const LS = 'novelos-variants'

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

  const goStream = async () => {
    const ac = new AbortController()
    abortRef.current = ac
    setStreaming(true)
    setStreamOpen(true)
    setStreamText('')
    setStreamMeta({ status: '准备上下文…' })
    let finishedId: number | null = null
    try {
      await api.writeStream(bookId, '', (ev) => {
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

export function BatchWriteButton({ bookId, size = 'md' }: { bookId: number; size?: 'sm' | 'md' }) {
  const [open, setOpen] = useState(false)
  const [n, setN] = useState(3)
  const { start } = useJobs()
  const job = useActiveJob(`write-batch:${bookId}`)
  const single = useActiveJob(`write-next:${bookId}`)
  return (
    <>
      <Button size={size} loading={!!job} disabled={!!single} icon={<Layers3 className="h-4 w-4" />} onClick={() => setOpen(true)}>
        {job ? `批量写作 ${Math.round(job.progress)}%` : '批量写'}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="批量写章"
          footer={<><Button variant="ghost" onClick={() => setOpen(false)}>取消</Button><Button variant="primary" onClick={() => { setOpen(false); start(api.writeBatch(bookId, n), { key: `write-batch:${bookId}`, label: `批量写 ${n} 章`, successMsg: `${n} 章已写完` }) }}>开始写 {n} 章</Button></>}>
          <div className="flex items-center gap-4">
            <input type="range" min={1} max={10} value={n} onChange={(e) => setN(Number(e.target.value))} className="flex-1 accent-[hsl(var(--primary))]" />
            <div className="num w-16 rounded-md bg-muted py-1.5 text-center text-lg font-semibold">{n}<span className="ml-0.5 text-xs font-normal text-muted-foreground">章</span></div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
