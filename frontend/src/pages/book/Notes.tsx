import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Download, Folder, Pin, Plus, Search, Trash2, CloudUpload } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { TagInput } from '@/components/ui/tag-input'
import { EmptyState, PageHeader } from '@/components/common/States'
import { v013Api } from '@/lib/api'
import type { Note } from '@/lib/types'
import { cn, fmtTime } from '@/lib/utils'

/** v0.13 写作笔记：目录 + 笔记，置顶、标签、搜索；写章时用「@笔记:标题」引用；Markdown 导入导出 */
export default function NotesPage() {
  const bookId = Number(useParams().bookId)
  const qc = useQueryClient()
  const key = ['notes', bookId]
  const [q, setQ] = useState('')
  const list = useQuery({ queryKey: key, queryFn: () => v013Api.notes(bookId) })
  const [sel, setSel] = useState<number | null>(null)
  const [folder, setFolder] = useState<string | null>(null)
  const [del, setDel] = useState<Note | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const notes = list.data ?? []
  const folders = useMemo(() => [...new Set(notes.map((n) => n.folder))].sort((a, b) => (a === '' ? 1 : b === '' ? -1 : a.localeCompare(b))), [notes])
  const shown = notes.filter((n) => (folder === null || n.folder === folder) && (!q.trim() || [n.title, n.content, ...n.tags].some((x) => x.toLowerCase().includes(q.trim().toLowerCase()))))
  const cur = notes.find((n) => n.id === sel) ?? null
  useEffect(() => { if (!sel && shown.length) setSel(shown[0].id) }, [shown, sel])
  const create = useMutation({
    mutationFn: () => v013Api.createNote(bookId, { title: '新笔记', folder: folder ?? '', content: '' }),
    meta: { errorTitle: '新建失败' },
    onSuccess: (n) => { qc.invalidateQueries({ queryKey: key }); setSel(n.id) },
  })
  const rm = useMutation({
    mutationFn: (id: number) => v013Api.deleteNote(bookId, id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: key }); setSel(null); setDel(null); toast.success('已删除') },
  })
  const imp = useMutation({
    mutationFn: (text: string) => v013Api.importNotes(bookId, text, folder ?? ''),
    meta: { errorTitle: '导入失败' },
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: key }); toast.success(`导入 ${r.created} 条笔记`) },
  })
  const exportMd = async () => {
    const r = await fetch(v013Api.exportNotesUrl(bookId), { credentials: 'include' })
    const text = await r.text()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }))
    a.download = '写作笔记.md'
    a.click()
    URL.revokeObjectURL(a.href)
  }
  return (
    <div className="page max-w-[1180px]">
      <PageHeader title="写作笔记" actions={<>
        <Button icon={<CloudUpload className="h-4 w-4" />} loading={imp.isPending} onClick={() => fileRef.current?.click()}>导入</Button>
        <Button icon={<Download className="h-4 w-4" />} disabled={!notes.length} onClick={() => void exportMd()}>导出</Button>
        <Button variant="primary" icon={<Plus className="h-4 w-4" />} loading={create.isPending} onClick={() => create.mutate()}>新笔记</Button>
        <input ref={fileRef} type="file" accept=".md,.txt,text/markdown,text/plain" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void f.text().then((t) => imp.mutate(t)); e.target.value = '' }} />
      </>} />
      {list.isLoading ? <Skeleton className="h-[480px] rounded-2xl" /> : !notes.length ? (
        <EmptyState kind="idea" title="还没有笔记" action={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => create.mutate()}>新笔记</Button>} />
      ) : (
        <div className="grid gap-4 md:grid-cols-[280px_minmax(0,1fr)]">
          <Card className="flex max-h-[calc(100vh-180px)] min-h-[420px] flex-col overflow-hidden">
            <div className="border-b p-3">
              <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="搜索" className="h-10 pl-9" /></div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <FolderChip on={folder === null} onClick={() => setFolder(null)}>全部</FolderChip>
                {folders.map((f) => <FolderChip key={f} on={folder === f} onClick={() => setFolder(f)}>{f || '未归类'}</FolderChip>)}
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {shown.map((n) => (
                <button key={n.id} type="button" onClick={() => setSel(n.id)}
                  className={cn('block w-full border-b px-3.5 py-2.5 text-left transition hover:bg-subtle', sel === n.id && 'bg-primary-soft/50')}>
                  <div className="flex items-center gap-1.5">
                    {n.pinned && <Pin className="h-3.5 w-3.5 shrink-0 text-primary" />}
                    <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{n.title}</span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[12px] text-muted-foreground">{n.content || '（空）'}</p>
                  <div className="mt-1 text-[11px] text-muted-foreground">{n.folder || '未归类'} · {fmtTime(n.updated_at ?? '')}</div>
                </button>
              ))}
            </div>
          </Card>
          {cur ? <Editor key={cur.id} note={cur} bookId={bookId} onDelete={() => setDel(cur)} folders={folders} /> : <Card className="flex min-h-[420px] items-center justify-center text-[13px] text-muted-foreground">选一条笔记</Card>}
        </div>
      )}
      <Dialog open={!!del} onOpenChange={(o) => !o && setDel(null)}>
        <DialogContent title={`删除「${del?.title ?? ''}」？`} footer={<><Button variant="ghost" onClick={() => setDel(null)}>取消</Button><Button variant="danger" loading={rm.isPending} onClick={() => del && rm.mutate(del.id)}>删除</Button></>} />
      </Dialog>
    </div>
  )
}

function FolderChip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={cn('inline-flex h-8 items-center gap-1 rounded-full border px-2.5 text-[12.5px] transition', on ? 'border-primary bg-primary-soft text-primary' : 'hover:bg-muted')}>
      <Folder className="h-3.5 w-3.5" />{children}
    </button>
  )
}

function Editor({ note, bookId, onDelete, folders }: { note: Note; bookId: number; onDelete: () => void; folders: string[] }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ title: note.title, folder: note.folder, content: note.content, tags: note.tags, pinned: note.pinned })
  const dirty = f.title !== note.title || f.folder !== note.folder || f.content !== note.content || f.pinned !== note.pinned || f.tags.join('|') !== note.tags.join('|')
  const save = useMutation({
    mutationFn: (b: Partial<Note>) => v013Api.updateNote(bookId, note.id, b),
    meta: { errorTitle: '保存失败' },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notes', bookId] }),
  })
  useEffect(() => {
    if (!dirty) return
    const t = setTimeout(() => save.mutate(f), 900)
    return () => clearTimeout(t)
  }, [f]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Card className="flex min-h-[420px] flex-col p-4 sm:p-5">
      <div className="flex items-center gap-2">
        <Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} className="h-11 border-0 px-0 text-[18px] font-semibold shadow-none focus-visible:ring-0" />
        <Button size="icon-sm" variant="ghost" aria-label="置顶" onClick={() => setF({ ...f, pinned: !f.pinned })}><Pin className={cn('h-4 w-4', f.pinned && 'text-primary')} /></Button>
        <Button size="icon-sm" variant="ghost" aria-label="删除" onClick={onDelete} className="text-muted-foreground hover:text-danger"><Trash2 className="h-4 w-4" /></Button>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-[180px_minmax(0,1fr)]">
        <Input value={f.folder} onChange={(e) => setF({ ...f, folder: e.target.value })} placeholder="目录" list={`folders-${note.id}`} className="h-10" />
        <datalist id={`folders-${note.id}`}>{folders.filter(Boolean).map((x) => <option key={x} value={x} />)}</datalist>
        <TagInput value={f.tags} onChange={(v) => setF({ ...f, tags: v })} placeholder="标签，回车添加" />
      </div>
      <Textarea value={f.content} onChange={(e) => setF({ ...f, content: e.target.value })} className="mt-3 min-h-[360px] flex-1 font-serif text-[15px] leading-relaxed" />
      <div className="mt-2 flex items-center justify-between text-[12px] text-muted-foreground">
        <span className="font-mono">@笔记:{f.title}</span>
        <span>{save.isPending ? '保存中…' : dirty ? '未保存' : '已保存'}</span>
      </div>
    </Card>
  )
}
