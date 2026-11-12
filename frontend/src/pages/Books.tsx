import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MoreHorizontal, Plus, Trash2 } from '@/components/icons'
import * as DM from '@radix-ui/react-dropdown-menu'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { BookCover, QuickCreateDialog, StageBadge, StageDots } from '@/components/common/BookBits'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { GridSkeleton } from './_skeleton'
import { useBooks } from '@/hooks/queries'
import { api } from '@/lib/api'
import type { Book } from '@/lib/types'
import { fmtNum, fmtTime } from '@/lib/utils'

export default function Books() {
  const { data, isLoading, error, refetch } = useBooks()
  const [open, setOpen] = useState(false)
  const [del, setDel] = useState<Book | null>(null)
  const qc = useQueryClient()
  const rm = useMutation({
    mutationFn: (id: number) => api.deleteBook(id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['books'] }); toast.success('已删除'); setDel(null) },
  })
  return (
    <div className="page">
      <PageHeader title="我的书" actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>新建作品</Button>} />
      {isLoading ? <GridSkeleton n={4} h="h-[300px]" cols="grid-cols-2 md:grid-cols-3 lg:grid-cols-4" /> : error ? <ErrorState error={error} onRetry={refetch} /> : !data?.length ? (
        <EmptyState kind="book" title="书架还是空的" action={<><Link to="/radar"><Button>看热点</Button></Link><Button variant="primary" onClick={() => setOpen(true)}>一键开写</Button></>} />
      ) : (
        <div className="grid grid-cols-2 gap-5 md:grid-cols-3 lg:grid-cols-4">
          {data.map((b) => (
            <div key={b.id} className="group relative">
              <Link to={`/books/${b.id}`} className="block rounded-xl bg-surface p-3 hairline shadow-card transition hover:-translate-y-0.5 hover:shadow-lift">
                <BookCover book={b} />
                <div className="mt-3 truncate font-semibold group-hover:text-primary">{b.title}</div>
                <div className="mt-0.5 flex items-center justify-between text-xs text-muted-foreground">
                  <span className="truncate">{b.genre}</span><span>{fmtTime(b.updated_at)}</span>
                </div>
                <div className="mt-2.5 flex items-center justify-between"><StageBadge status={b.status} /><span className="num text-xs text-muted-foreground">{fmtNum(b.stats.words)} 字</span></div>
                <div className="mt-2.5"><StageDots status={b.status} /></div>
              </Link>
              <DM.Root>
                <DM.Trigger asChild>
                  <button className="absolute right-5 top-5 rounded-md bg-black/35 p-1 text-white opacity-0 backdrop-blur transition hover:bg-black/50 group-hover:opacity-100 data-[state=open]:opacity-100" aria-label="更多"><MoreHorizontal className="h-4 w-4" /></button>
                </DM.Trigger>
                <DM.Portal>
                  <DM.Content align="end" sideOffset={4} className="z-50 min-w-[140px] rounded-lg bg-popover p-1 shadow-pop hairline animate-zoom-in">
                    <DM.Item onSelect={() => setDel(b)} className="flex cursor-default items-center gap-2 rounded-md px-2 py-1.5 text-[13px] text-danger outline-none data-[highlighted]:bg-danger-soft"><Trash2 className="h-3.5 w-3.5" />删除作品</DM.Item>
                  </DM.Content>
                </DM.Portal>
              </DM.Root>
            </div>
          ))}
        </div>
      )}
      <QuickCreateDialog open={open} onOpenChange={setOpen} />
      <Dialog open={!!del} onOpenChange={(o) => !o && setDel(null)}>
        <DialogContent title={`删除《${del?.title ?? ''}》？`} desc="设定、大纲、章节都会一并删除，无法恢复。"
          footer={<><Button variant="ghost" onClick={() => setDel(null)}>取消</Button><Button variant="danger" loading={rm.isPending} onClick={() => del && rm.mutate(del.id)}>确认删除</Button></>} />
      </Dialog>
    </div>
  )
}
