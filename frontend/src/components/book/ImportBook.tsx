import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CloudUpload } from '@/components/icons'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Segmented } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import { useJobs } from '@/lib/jobs'
import type { Gender, ImportPreview } from '@/lib/types'
import { cn, fmtNum } from '@/lib/utils'

/** v0.12 导入已有作品：文件 / 粘贴 → 预览卷章与疑点 → 建书（正文直接入库）→ 可选接管（反推设定、账本、大纲） */
export function ImportBookDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [src, setSrc] = useState<'file' | 'paste'>('file')
  const [text, setText] = useState('')
  const [pv, setPv] = useState<ImportPreview | null>(null)
  const [title, setTitle] = useState('')
  const [genre, setGenre] = useState('')
  const [gender, setGender] = useState<Gender>('male')
  const [skip, setSkip] = useState<Set<number>>(new Set())
  const [adopt, setAdopt] = useState(true)
  const fileRef = useRef<HTMLInputElement>(null)
  const nav = useNavigate()
  const qc = useQueryClient()
  const { start } = useJobs()
  const reset = () => { setPv(null); setText(''); setTitle(''); setGenre(''); setSkip(new Set()) }
  const parse = useMutation({
    mutationFn: (s: File | string) => api.importPreview(s),
    meta: { errorTitle: '解析失败' },
    onSuccess: (p) => { setPv(p); setTitle(p.title); setSkip(new Set(p.chapters.filter((c) => c.words === 0).map((c) => c.index))) },
  })
  const commit = useMutation({
    mutationFn: () => api.importCommit({ import_id: pv!.import_id, title: title.trim(), genre: genre.trim(), gender, skip: [...skip] }),
    meta: { errorTitle: '导入失败' },
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['books'] })
      toast.success(`已导入 ${r.chapters} 章，${fmtNum(r.words)} 字`)
      if (adopt) start(api.adoptBook(r.book_id), { key: `adopt:${r.book_id}`, label: '接管旧书', successMsg: '接管完成：设定、伏笔、大纲已补上' })
      reset(); onOpenChange(false); nav(`/books/${r.book_id}`)
    },
  })
  const chosen = pv ? pv.chapters.filter((c) => !skip.has(c.index)) : []
  const toggle = (i: number) => setSkip((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n })
  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) reset(); onOpenChange(o) }} title="导入作品" width={720}
      footer={pv ? <div className="flex w-full flex-wrap items-center gap-2">
        <label className="flex min-h-[40px] cursor-pointer items-center gap-2 text-[13px]"><Switch checked={adopt} onCheckedChange={setAdopt} />导入后接管（反推设定、伏笔、大纲）</label>
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" onClick={() => setPv(null)}>重新选择</Button>
          <Button variant="primary" disabled={!chosen.length || !title.trim()} loading={commit.isPending} onClick={() => commit.mutate()}>导入 {chosen.length} 章</Button>
        </div>
      </div> : undefined}>
      {!pv ? (
        <div className="space-y-4">
          <Segmented block value={src} onChange={setSrc} options={[{ value: 'file', label: '上传文件' }, { value: 'paste', label: '粘贴正文' }]} />
          {src === 'file' ? (
            <button type="button" onClick={() => fileRef.current?.click()} disabled={parse.isPending}
              className="flex h-44 w-full flex-col items-center justify-center gap-2 rounded-xl border border-dashed text-[13.5px] text-muted-foreground transition hover:border-primary/50 hover:bg-primary-soft/40 hover:text-primary">
              <CloudUpload className="h-7 w-7" />{parse.isPending ? '解析中…' : '选择 TXT / MD / DOCX'}
              <input ref={fileRef} type="file" accept=".txt,.md,.docx,text/plain,text/markdown" className="hidden"
                onChange={(e) => { const f = e.target.files?.[0]; if (f) parse.mutate(f); e.target.value = '' }} />
            </button>
          ) : (
            <>
              <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-[280px] text-[13px]" placeholder="第1章 ……" />
              <div className="flex justify-end"><Button variant="primary" disabled={!text.trim()} loading={parse.isPending} onClick={() => parse.mutate(text)}>识别章节</Button></div>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-[1fr_140px_140px]">
            <Field label="书名"><Input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
            <Field label="题材"><Input value={genre} onChange={(e) => setGenre(e.target.value)} placeholder="如：玄幻" /></Field>
            <Field label="频道"><Segmented block value={gender} onChange={setGender} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} /></Field>
          </div>
          <div className="flex flex-wrap gap-2 text-[12.5px] text-muted-foreground">
            <span className="rounded-full bg-surface px-3 py-1 hairline">{pv.chapters.length} 章</span>
            <span className="rounded-full bg-surface px-3 py-1 hairline">{fmtNum(pv.total_words)} 字</span>
            {pv.volumes.length > 0 && <span className="rounded-full bg-surface px-3 py-1 hairline">{pv.volumes.length} 卷</span>}
          </div>
          {pv.warnings.map((w) => <div key={w} className="flex items-center gap-2 rounded-lg bg-warning-soft px-3.5 py-2 text-[13px] text-warning"><AlertTriangle className="h-4 w-4 shrink-0" />{w}</div>)}
          <div className="max-h-[50vh] divide-y divide-border/70 overflow-auto rounded-xl bg-surface hairline">
            {pv.chapters.map((c) => {
              const off = skip.has(c.index)
              return (
                <label key={c.index} className={cn('flex min-h-[48px] cursor-pointer items-start gap-3 px-3.5 py-2.5', off && 'opacity-50')}>
                  <input type="checkbox" checked={!off} onChange={() => toggle(c.index)} className="mt-1 h-4 w-4 shrink-0 accent-[hsl(var(--primary))]" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="truncate text-[13.5px] font-medium">{c.raw_title}</span>
                      {c.volume && <span className="rounded bg-muted px-1.5 text-[11px] text-muted-foreground">{c.volume}</span>}
                      {c.flags.map((f) => <span key={f} className="rounded bg-warning-soft px-1.5 text-[11px] text-warning">{f}</span>)}
                    </div>
                    <p className="mt-0.5 truncate text-[12px] text-muted-foreground">{c.preview || '（空）'}</p>
                  </div>
                  <span className="num shrink-0 text-[12px] text-muted-foreground">{fmtNum(c.words)} 字</span>
                </label>
              )
            })}
          </div>
        </div>
      )}
    </Sheet>
  )
}
