import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Segmented } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import { useJobs } from '@/lib/jobs'
import type { Book, BookStatus, Gender } from '@/lib/types'
import { GENRES_FEMALE, GENRES_MALE, STAGES, cn, stageIndex } from '@/lib/utils'

const GRADS = [
  ['#5b6cf0', '#8b5cf6'], ['#0ea5e9', '#6366f1'], ['#f97316', '#e11d48'], ['#10b981', '#0ea5e9'],
  ['#a855f7', '#ec4899'], ['#334155', '#64748b'], ['#d97706', '#b45309'],
]

export function BookCover({ book, className }: { book: Pick<Book, 'id' | 'title' | 'cover_url' | 'genre'>; className?: string }) {
  const [broken, setBroken] = useState(false)
  if (book.cover_url && !broken)
    return <img src={book.cover_url} alt={book.title} onError={() => setBroken(true)} className={cn('aspect-[3/4] w-full rounded-md object-cover shadow-card', className)} />
  const [a, b] = GRADS[book.id % GRADS.length]
  return (
    <div className={cn('relative flex aspect-[3/4] w-full flex-col justify-end overflow-hidden rounded-md p-2.5 text-white shadow-card', className)} style={{ background: `linear-gradient(145deg, ${a}, ${b})` }}>
      <div className="absolute -right-6 -top-6 h-20 w-20 rounded-full bg-white/15" />
      <div className="absolute right-3 top-10 h-8 w-8 rounded-full border border-white/30" />
      <div className="relative line-clamp-3 font-serif text-[13px] font-bold leading-snug [text-shadow:0_1px_4px_rgb(0_0_0/0.25)]">{book.title}</div>
      <div className="relative mt-1 text-[10px] opacity-80">{book.genre}</div>
    </div>
  )
}

export function StageBadge({ status }: { status: BookStatus }) {
  const s = STAGES[stageIndex(status)]
  const tone = status === 'done' ? 'success' : status === 'writing' ? 'primary' : status === 'packaging' ? 'warning' : 'neutral'
  return <Badge tone={tone} dot>{s.label}{status === 'done' ? '' : '阶段'}</Badge>
}

export function StageDots({ status }: { status: BookStatus }) {
  const i = stageIndex(status)
  return (
    <div className="flex items-center gap-1">
      {STAGES.map((s, k) => (
        <div key={s.key} title={s.label} className={cn('h-1.5 flex-1 rounded-full transition-colors', k < i ? 'bg-primary/60' : k === i ? 'bg-primary' : 'bg-muted')} />
      ))}
    </div>
  )
}

/** 一键开写：建书 + 自动开始生成设定 */
export function QuickCreateDialog({ open, onOpenChange, defaults }: { open: boolean; onOpenChange: (o: boolean) => void; defaults?: { genre?: string; gender?: Gender; premise?: string } }) {
  const [gender, setGender] = useState<Gender>(defaults?.gender ?? 'male')
  const [genre, setGenre] = useState(defaults?.genre ?? '')
  const [title, setTitle] = useState('')
  const [premise, setPremise] = useState(defaults?.premise ?? '')
  const nav = useNavigate()
  const qc = useQueryClient()
  const { start } = useJobs()
  const genres = gender === 'male' ? GENRES_MALE : GENRES_FEMALE
  const m = useMutation({
    mutationFn: () => api.createBook({ title: title.trim() || undefined, genre: genre || genres[0], gender, premise: premise.trim() || undefined }),
    meta: { errorTitle: '建书失败' },
    onSuccess: (book) => {
      qc.invalidateQueries({ queryKey: ['books'] })
      onOpenChange(false)
      toast.success(`《${book.title}》已创建`, { description: '正在为你生成设定库…' })
      nav(`/books/${book.id}`)
      start(api.generateBible(book.id), { key: `bible:${book.id}`, label: '生成设定' })
    },
  })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="一键开写"
        desc="选个题材，写一句你的点子（可不写）。建书后会自动生成设定库。"
        footer={
          <>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>取消</Button>
            <Button variant="primary" loading={m.isPending} icon={<Sparkles className="h-4 w-4" />} onClick={() => m.mutate()}>创建并开始</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="频道">
            <Segmented value={gender} onChange={(g) => { setGender(g); setGenre('') }} options={[{ value: 'male', label: '男频' }, { value: 'female', label: '女频' }]} />
          </Field>
          <Field label="题材">
            <div className="flex flex-wrap gap-1.5">
              {genres.map((g) => (
                <button key={g} type="button" onClick={() => setGenre(g)} className={cn('h-7 rounded-full border px-3 text-[12.5px] transition', (genre || genres[0]) === g ? 'border-primary bg-primary-soft text-primary' : 'hover:border-foreground/25')}>
                  {g}
                </button>
              ))}
            </div>
          </Field>
          <Field label="书名" hint="可留空，之后在包装页再定">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：我在末世开超市" />
          </Field>
          <Field label="一句话点子" hint="可选">
            <Textarea value={premise} onChange={(e) => setPremise(e.target.value)} placeholder="例如：全球冰封，主角的超市每天零点自动补货。" className="min-h-[72px]" />
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  )
}
