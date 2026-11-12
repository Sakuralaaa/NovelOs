import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import * as P from '@radix-ui/react-popover'
import { ChevronDown, Layers3, PenLine } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Segmented } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import { cn } from '@/lib/utils'

type V = 1 | 2 | 3
const LS = 'novelos-variants'

/** 写下一章（可选 1/2/3 个版本） */
export function WriteNextButton({ bookId, size = 'md', className, navigateOnDone = true }: { bookId: number; size?: 'sm' | 'md' | 'lg'; className?: string; navigateOnDone?: boolean }) {
  const [variants, setVariants] = useState<V>(() => (Number(localStorage.getItem(LS)) as V) || 1)
  const { start } = useJobs()
  const job = useActiveJob(`write-next:${bookId}`)
  const batch = useActiveJob(`write-batch:${bookId}`)
  const nav = useNavigate()
  const set = (v: V) => { setVariants(v); localStorage.setItem(LS, String(v)) }
  const go = () =>
    start(api.writeNext(bookId, variants), {
      key: `write-next:${bookId}`,
      label: variants > 1 ? `写下一章（${variants} 个版本）` : '写下一章',
      successMsg: variants > 1 ? `新章节已生成 ${variants} 个版本，挑一个吧` : '新章节已写好并通过审稿',
      onSuccess: (j) => { if (navigateOnDone && j.result?.chapter_id) nav(`/books/${bookId}/chapters/${j.result.chapter_id}`) },
    })
  return (
    <div className={cn('inline-flex', className)}>
      <Button variant="primary" size={size} loading={!!job} disabled={!!batch} icon={<PenLine className="h-4 w-4" />} onClick={go} className="rounded-r-none">
        {job ? `写作中 ${Math.round(job.progress)}%` : variants > 1 ? `写下一章 ×${variants}版` : '写下一章'}
      </Button>
      <P.Root>
        <P.Trigger asChild>
          <Button variant="primary" size={size} disabled={!!job || !!batch} className="rounded-l-none border-l border-white/20 px-2" aria-label="版本数设置">
            <ChevronDown className="h-4 w-4" />
          </Button>
        </P.Trigger>
        <P.Portal>
          <P.Content align="end" sideOffset={6} className="z-50 w-[280px] rounded-xl bg-popover p-4 shadow-pop hairline animate-zoom-in">
            <div className="text-[13px] font-semibold">一次写几个版本？</div>
            <Segmented className="mt-3 w-full" value={String(variants) as '1' | '2' | '3'} onChange={(v) => set(Number(v) as V)} options={[{ value: '1', label: '1 版' }, { value: '2', label: '2 版' }, { value: '3', label: '3 版' }]} />
          </P.Content>
        </P.Portal>
      </P.Root>
    </div>
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
