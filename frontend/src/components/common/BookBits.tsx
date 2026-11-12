import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from '@/components/icons'
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

// 布面精装配色：藏青、墨绿、赭石、朱砂、黛灰、栗色、靛蓝
const CLOTH = ['#2c3e57', '#33503f', '#8a5a2b', '#9b3a2c', '#4a4f57', '#5e3a2e', '#2f4a5e']

export function BookCover({ book, className, mini }: { book: Pick<Book, 'id' | 'title' | 'cover_url' | 'genre'>; className?: string; mini?: boolean }) {
  const [broken, setBroken] = useState(false)
  if (book.cover_url && !broken)
    return <img src={book.cover_url} alt={book.title} onError={() => setBroken(true)} className={cn('aspect-[3/4] w-full rounded-[3px] object-cover shadow-card ring-1 ring-black/10', className)} />
  const bg = CLOTH[book.id % CLOTH.length]
  const cloth = { backgroundColor: bg, backgroundImage: 'linear-gradient(90deg, rgb(0 0 0 / 0.22) 0, rgb(0 0 0 / 0.22) 6%, rgb(255 255 255 / 0.10) 6.5%, transparent 9%), linear-gradient(160deg, rgb(255 255 255 / 0.10), transparent 55%)' }
  if (mini)
    return (
      <div className={cn('relative flex aspect-[3/4] w-full items-center justify-center overflow-hidden rounded-[3px] text-[#f3ead8] shadow-card ring-1 ring-black/10', className)} style={cloth}>
        <span className="relative pl-[8%] font-serif text-[16px] font-bold">{book.title.slice(0, 1)}</span>
      </div>
    )
  return (
    <div className={cn('relative flex aspect-[3/4] w-full flex-col items-center justify-center overflow-hidden rounded-[3px] py-3 pl-[12%] pr-[6%] text-[#f3ead8] shadow-card ring-1 ring-black/10', className)} style={cloth}>
      <div className="absolute inset-y-[7%] left-[13%] right-[7%] border border-[#e9dcc0]/35" />
      <div className="relative line-clamp-3 text-center font-serif text-[13px] font-bold leading-snug tracking-wide">{book.title}</div>
      <div className="relative mt-2 h-px w-6 bg-[#e9dcc0]/50" />
      <div className="relative mt-1.5 text-[10px] tracking-widest opacity-75">{book.genre}</div>
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
          <Field label="书名">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="例如：我在末世开超市" />
          </Field>
          <Field label="一句话点子">
            <Textarea value={premise} onChange={(e) => setPremise(e.target.value)} placeholder="例如：全球冰封，主角的超市每天零点自动补货。" className="min-h-[72px]" />
          </Field>
        </div>
      </DialogContent>
    </Dialog>
  )
}
