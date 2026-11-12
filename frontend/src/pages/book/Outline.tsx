import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronRight, ChevronsDownUp, ChevronsUpDown, FileText, ListTree, Pencil, Plus, Sparkles, Trash2, UnfoldVertical, X } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { Tip } from '@/components/ui/tooltip'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { OutlineLevel, OutlineNode } from '@/lib/types'
import { cn } from '@/lib/utils'

type TNode = OutlineNode & { children: TNode[] }
const LEVEL: Record<OutlineLevel, { label: string; cls: string }> = {
  book: { label: '总纲', cls: 'bg-foreground text-background' },
  volume: { label: '卷', cls: 'bg-primary text-primary-foreground' },
  arc: { label: '弧', cls: 'bg-amber-500/15 text-amber-600 dark:text-amber-300' },
  chapter: { label: '章', cls: 'bg-muted text-muted-foreground' },
}
const STATUS = { planned: { l: '待展开', t: 'neutral' }, expanded: { l: '已展开', t: 'primary' }, written: { l: '已成文', t: 'success' } } as const

function buildTree(list: OutlineNode[]): TNode[] {
  const map = new Map<number, TNode>()
  list.forEach((n) => map.set(n.id, { ...n, children: [] }))
  const roots: TNode[] = []
  map.forEach((n) => { const p = n.parent_id != null ? map.get(n.parent_id) : undefined; if (p) p.children.push(n); else roots.push(n) })
  const sort = (a: TNode[]) => { a.sort((x, y) => x.order - y.order || x.id - y.id); a.forEach((c) => sort(c.children)) }
  sort(roots)
  return roots
}

export default function Outline() {
  const id = useBookId()
  const q = useQuery({ queryKey: qk.outline(id), queryFn: () => api.outline(id) })
  const tree = useMemo(() => buildTree(q.data ?? []), [q.data])
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [editing, setEditing] = useState<OutlineNode | null>(null)
  const { start } = useJobs()
  const job = useActiveJob(`outline:${id}`)
  const counts = useMemo(() => {
    const c = { volume: 0, arc: 0, chapter: 0, written: 0 }
    ;(q.data ?? []).forEach((n) => { if (n.level !== 'book') c[n.level]++; if (n.level === 'chapter' && n.status === 'written') c.written++ })
    return c
  }, [q.data])

  const toggle = (nid: number) => setCollapsed((s) => { const n = new Set(s); n.has(nid) ? n.delete(nid) : n.add(nid); return n })
  const collapseAll = () => setCollapsed(new Set((q.data ?? []).filter((n) => n.level === 'arc' || n.level === 'volume').map((n) => n.id)))
  const gen = () => start(api.generateOutline(id), { key: `outline:${id}`, label: '生成大纲', successMsg: '大纲已生成' })

  return (
    <div className="page">
      <BookCrumb bookId={id} page="大纲" />
      <PageHeader className="mt-3" title="大纲"
        actions={<>
          {!!q.data?.length && <>
            <Button size="sm" variant="ghost" icon={<ChevronsUpDown className="h-4 w-4" />} onClick={() => setCollapsed(new Set())}>全部展开</Button>
            <Button size="sm" variant="ghost" icon={<ChevronsDownUp className="h-4 w-4" />} onClick={collapseAll}>收起</Button>
          </>}
          <Button variant="primary" loading={!!job} icon={<Sparkles className="h-4 w-4" />} onClick={gen}>{q.data?.length ? '重新生成大纲' : '生成大纲'}</Button>
        </>} />
      {job && <JobInline job={job} className="mb-5" />}

      {q.isLoading ? <div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
        : q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : !tree.length ? <EmptyState kind="outline" title="还没有大纲" action={<Button variant="primary" loading={!!job} icon={<ListTree className="h-4 w-4" />} onClick={gen}>生成大纲</Button>} />
        : (
          <>
            <div className="mb-4 flex flex-wrap gap-2 text-[12.5px] text-muted-foreground">
              <span className="rounded-full bg-surface px-3 py-1 hairline">{counts.volume} 卷</span>
              <span className="rounded-full bg-surface px-3 py-1 hairline">{counts.arc} 段剧情弧</span>
              <span className="rounded-full bg-surface px-3 py-1 hairline">{counts.chapter} 章细纲 · 已成文 {counts.written}</span>
            </div>
            <Card className="p-2 md:p-3">
              {tree.map((n) => <NodeRow key={n.id} node={n} depth={0} collapsed={collapsed} toggle={toggle} onEdit={setEditing} bookId={id} />)}
            </Card>
          </>
        )}
      <NodeEditor node={editing} onClose={() => setEditing(null)} bookId={id} />
    </div>
  )
}

function NodeRow({ node: n, depth, collapsed, toggle, onEdit, bookId }: { node: TNode; depth: number; collapsed: Set<number>; toggle: (id: number) => void; onEdit: (n: OutlineNode) => void; bookId: number }) {
  const open = !collapsed.has(n.id)
  const hasKids = n.children.length > 0
  const { start } = useJobs()
  const job = useActiveJob(`expand:${n.id}`)
  const isChapter = n.level === 'chapter'
  const st = STATUS[n.status] ?? STATUS.planned
  return (
    <div>
      <div className={cn('group relative flex items-start gap-2 rounded-lg py-2.5 pr-2 transition hover:bg-subtle', n.level === 'book' && 'bg-subtle/60', n.level === 'volume' && 'mt-1')} style={{ paddingLeft: 8 + depth * 22 }}>
        {depth > 0 && <span className="absolute top-0 h-full w-px bg-border" style={{ left: 8 + (depth - 1) * 22 + 9 }} />}
        <button onClick={() => hasKids && toggle(n.id)} className={cn('mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded text-muted-foreground', hasKids ? 'hover:bg-muted' : 'opacity-0')} aria-label={open ? '收起' : '展开'}>
          <ChevronRight className={cn('h-4 w-4 transition-transform', open && hasKids && 'rotate-90')} />
        </button>
        <span className={cn('mt-0.5 inline-flex h-5 shrink-0 items-center rounded px-1.5 text-[11px] font-semibold', LEVEL[n.level].cls)}>{LEVEL[n.level].label}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span title={n.title} className={cn('min-w-0 truncate font-medium', n.level === 'book' || n.level === 'volume' ? 'text-[14.5px]' : 'text-[13.5px]')}>{n.title}</span>
            <Badge tone={st.t} className="h-5 text-[11px]">{st.l}</Badge>
          </div>
          {n.summary && <p className={cn('mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground', isChapter ? 'line-clamp-1' : 'line-clamp-2')}>{n.summary}</p>}
          {isChapter && n.beats && Object.keys(n.beats).length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">{Object.entries(n.beats).slice(0, 4).map(([k, v]) => <span key={k} className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{k}：{typeof v === 'string' ? v : JSON.stringify(v)}</span>)}</div>
          )}
          {job && <JobInline job={job} className="mt-2 max-w-md" />}
        </div>
        <div className="flex shrink-0 items-center gap-1 opacity-60 transition group-hover:opacity-100">
          {isChapter && n.chapter_id && <Link to={`/books/${bookId}/chapters/${n.chapter_id}`}><Button size="xs" variant="ghost" icon={<FileText className="h-3.5 w-3.5" />}>正文</Button></Link>}
          {!isChapter && (
            <Tip content="根据上层大纲，AI 生成下一层（卷→弧→章细纲）">
              <Button size="xs" variant={n.status === 'planned' ? 'soft' : 'ghost'} loading={!!job} icon={<UnfoldVertical className="h-3.5 w-3.5" />} onClick={() => start(api.expandOutline(n.id), { key: `expand:${n.id}`, label: `滚动展开：${n.title}` })}>滚动展开</Button>
            </Tip>
          )}
          <Button size="icon-sm" variant="ghost" onClick={() => onEdit(n)} aria-label="编辑"><Pencil className="h-3.5 w-3.5" /></Button>
        </div>
      </div>
      <AnimatePresence initial={false}>
        {open && hasKids && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.18 }} className="overflow-hidden">
            {n.children.map((c) => <NodeRow key={c.id} node={c} depth={depth + 1} collapsed={collapsed} toggle={toggle} onEdit={onEdit} bookId={bookId} />)}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function NodeEditor({ node, onClose, bookId }: { node: OutlineNode | null; onClose: () => void; bookId: number }) {
  const [f, setF] = useState<{ title: string; summary: string; beats: { k: string; v: string }[] }>({ title: '', summary: '', beats: [] })
  const [cur, setCur] = useState<OutlineNode | null>(null)
  if (node && node !== cur) {
    setCur(node)
    setF({ title: node.title, summary: node.summary, beats: Object.entries(node.beats ?? {}).map(([k, v]) => ({ k, v: typeof v === 'string' ? v : JSON.stringify(v) })) })
  }
  const qc = useQueryClient()
  const m = useMutation({
    mutationFn: () => api.updateOutline(node!.id, { title: f.title, summary: f.summary, beats: f.beats.length ? Object.fromEntries(f.beats.filter((b) => b.k.trim()).map((b) => [b.k.trim(), b.v])) : node!.beats }),
    meta: { errorTitle: '保存失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.outline(bookId) }); toast.success('大纲已保存'); onClose() },
  })
  const [confirmDel, setConfirmDel] = useState(false)
  const rm = useMutation({
    mutationFn: () => api.deleteOutline(node!.id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.outline(bookId) }); qc.invalidateQueries({ queryKey: qk.chapters(bookId) }); toast.success('已删除'); setConfirmDel(false); onClose() },
  })
  return (
    <Sheet open={!!node} onOpenChange={(o) => !o && onClose()} title={`编辑${node ? LEVEL[node.level].label : ''}`}
      footer={<div className="flex w-full items-center gap-2">
        {node && node.level !== 'book' && <Button variant="ghost" className="text-danger hover:bg-danger-soft" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setConfirmDel(true)}>删除</Button>}
        <div className="ml-auto flex gap-2"><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate()}>保存</Button></div>
      </div>}>
      <Dialog open={confirmDel} onOpenChange={setConfirmDel}>
        <DialogContent title={`删除「${node?.title ?? ''}」？`} desc={node?.level === 'chapter' ? '未提交的草稿会一起删除。' : '下面的所有子节点和未提交的草稿会一起删除。'}
          footer={<><Button variant="ghost" onClick={() => setConfirmDel(false)}>取消</Button><Button variant="danger" loading={rm.isPending} onClick={() => rm.mutate()}>删除</Button></>} />
      </Dialog>
      <div className="space-y-4">
        <Field label="标题"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="内容概要"><Textarea value={f.summary} onChange={(e) => setF({ ...f, summary: e.target.value })} className="min-h-[160px] leading-relaxed" /></Field>
        {node?.level === 'chapter' && (
          <div>
            <div className="mb-1.5 flex items-center justify-between"><span className="text-[13px] font-medium">节拍</span><Button size="xs" variant="ghost" icon={<Plus className="h-3 w-3" />} onClick={() => setF({ ...f, beats: [...f.beats, { k: '', v: '' }] })}>添加</Button></div>
            <div className="space-y-1.5">
              {f.beats.map((b, i) => (
                <div key={i} className="flex gap-1.5">
                  <Input className="w-[110px] shrink-0" value={b.k} placeholder="如：章尾钩子" onChange={(e) => setF({ ...f, beats: f.beats.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)) })} />
                  <Input value={b.v} onChange={(e) => setF({ ...f, beats: f.beats.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)) })} />
                  <Button size="icon" variant="ghost" onClick={() => setF({ ...f, beats: f.beats.filter((_, j) => j !== i) })}><X className="h-4 w-4" /></Button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </Sheet>
  )
}
