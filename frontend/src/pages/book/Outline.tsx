import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { Check, ChevronRight, ChevronsDownUp, ChevronsUpDown, FileText, Layers3, ListTree, Lock, Pencil, Plus, RotateCcw, Sparkles, Trash2, UnfoldVertical, Unlock, X } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { MentionTextarea } from '@/components/bible/MentionTextarea'
import { Skeleton } from '@/components/ui/misc'
import { Tip } from '@/components/ui/tooltip'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { AskBox, CompareRow, useModelRoute } from '@/components/common/AiAsk'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { OutlineLevel, OutlineNode } from '@/lib/types'
import { BEAT_LABELS, beatLabel, cn } from '@/lib/utils'

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
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchCount, setBatchCount] = useState(10)
  const [batchHeavy, setBatchHeavy] = useState(true)
  const [batchInst, setBatchInst] = useState('')
  const [goldenOpen, setGoldenOpen] = useState(false)
  const [goldenInst, setGoldenInst] = useState('')
  const { start } = useJobs()
  const job = useActiveJob(`outline:${id}`)
  const batchJob = useActiveJob(`outline-batch:${id}`)
  const goldenJob = useActiveJob(`golden-three:${id}`)
  const counts = useMemo(() => {
    const c = { volume: 0, arc: 0, chapter: 0, written: 0 }
    ;(q.data ?? []).forEach((n) => { if (n.level !== 'book') c[n.level]++; if (n.level === 'chapter' && n.status === 'written') c.written++ })
    return c
  }, [q.data])

  const toggle = (nid: number) => setCollapsed((s) => { const n = new Set(s); n.has(nid) ? n.delete(nid) : n.add(nid); return n })
  const collapseAll = () => setCollapsed(new Set((q.data ?? []).filter((n) => n.level === 'arc' || n.level === 'volume').map((n) => n.id)))
  const gen = () => start(api.generateOutline(id), { key: `outline:${id}`, label: '生成大纲', successMsg: counts.written > 0 ? '总纲已生成并自动锚定已写开篇' : '大纲已生成' })
  const runBatch = () => {
    setBatchOpen(false)
    start(api.batchOutlineChapters(id, { count: batchCount, heavy: batchHeavy, instruction: batchInst.trim() }), {
      key: `outline-batch:${id}`,
      label: `批量生成 ${batchCount} 章细纲`,
      successMsg: `已生成 ${batchCount} 章${batchHeavy ? '千字起承转合' : ''}章纲`,
    })
  }
  const runGolden = () => {
    setGoldenOpen(false)
    start(api.writeGoldenThree(id, goldenInst.trim()), {
      key: `golden-three:${id}`,
      label: '黄金三章先行',
      successMsg: '黄金三章已写完！现在可点「生成大纲」锚定前三章展开全书',
    })
  }

  return (
    <div className="page">
      <BookCrumb bookId={id} page="大纲" />
      <PageHeader className="mt-3" title="大纲"
        actions={<>
          {!!q.data?.length && <>
            <Button size="sm" variant="ghost" icon={<ChevronsUpDown className="h-4 w-4" />} onClick={() => setCollapsed(new Set())}>全部展开</Button>
            <Button size="sm" variant="ghost" icon={<ChevronsDownUp className="h-4 w-4" />} onClick={collapseAll}>收起</Button>
          </>}
          {counts.written < 3 && (
            <Button size="sm" variant="soft" loading={!!goldenJob} icon={<Sparkles className="h-4 w-4" />} onClick={() => setGoldenOpen(true)}>
              黄金三章先行
            </Button>
          )}
          <Button size="sm" variant="soft" loading={!!batchJob} icon={<Layers3 className="h-4 w-4" />} onClick={() => setBatchOpen(true)}>
            批量章纲
          </Button>
          <Button variant="primary" loading={!!job} icon={<Sparkles className="h-4 w-4" />} onClick={gen}>{q.data?.length ? '重新生成大纲' : '生成大纲'}</Button>
        </>} />
      {job && <JobInline job={job} className="mb-4" />}
      {batchJob && <JobInline job={batchJob} className="mb-4" />}
      {goldenJob && <JobInline job={goldenJob} className="mb-4" />}

      {q.isLoading ? <div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>
        : q.error ? <ErrorState error={q.error} onRetry={() => q.refetch()} />
        : !tree.length ? (
          <EmptyState kind="outline" title="还没有大纲"
            desc="推荐「黄金三章先行」先写出强情绪前三章，满意后再点「生成大纲」自动锚定前三章展开全书；也可以直接生成整书总纲。"
            action={<div className="flex flex-wrap justify-center gap-2">
              <Button variant="soft" loading={!!goldenJob} icon={<Sparkles className="h-4 w-4" />} onClick={() => setGoldenOpen(true)}>黄金三章先行</Button>
              <Button variant="primary" loading={!!job} icon={<ListTree className="h-4 w-4" />} onClick={gen}>生成大纲</Button>
            </div>} />
        )
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

      <Dialog open={batchOpen} onOpenChange={setBatchOpen}>
        <DialogContent title="批量生成起承转合章纲"
          desc="重纲轻写：一次规划 5–15 章详纲，每章配齐起/承/转/合四拍与核心收益，按 1:2 比例扩写成紧凑短章。"
          footer={<><Button variant="ghost" onClick={() => setBatchOpen(false)}>取消</Button><Button variant="primary" onClick={runBatch}>生成 {batchCount} 章纲</Button></>}>
          <div className="space-y-4">
            <div className="flex items-center gap-4">
              <input type="range" min={3} max={15} value={batchCount} onChange={(e) => setBatchCount(Number(e.target.value))} className="flex-1 accent-[hsl(var(--primary))]" />
              <div className="num w-16 rounded-md bg-muted py-1 text-center text-base font-semibold">{batchCount}<span className="ml-0.5 text-xs font-normal text-muted-foreground">章</span></div>
            </div>
            <label className="flex cursor-pointer items-center justify-between rounded-lg bg-subtle/60 px-3 py-2.5 text-[13px]">
              <span>启用「千字起承转合详纲」模式</span>
              <Switch checked={batchHeavy} onCheckedChange={setBatchHeavy} />
            </label>
            <Field label="本批走势要求（可选）">
              <Textarea rows={3} value={batchInst} onChange={(e) => setBatchInst(e.target.value)} placeholder="例如：这10章围绕拍卖会与家族夺权推进，第8章完成一次大打脸并升级金手指…" />
            </Field>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={goldenOpen} onOpenChange={setGoldenOpen}>
        <DialogContent title="黄金三章先行（倒序开书）"
          desc="不急着先写几十万字总纲——先一次性打磨并生成强情绪第 1–3 章，确认开篇爆点够硬后，再点「生成大纲」自动锚定前三章展开全书。"
          footer={<><Button variant="ghost" onClick={() => setGoldenOpen(false)}>取消</Button><Button variant="primary" onClick={runGolden}>立即生成黄金三章</Button></>}>
          <Field label="开篇定向要求（可选）" hint="将同时作用于前三章详纲与正文写作">
            <Textarea rows={3} value={goldenInst} onChange={(e) => setGoldenInst(e.target.value)}
              placeholder="例如：第1章前三句直接进高情绪冲突对话；全程大白话无专业黑话；每章约2100字…" />
          </Field>
        </DialogContent>
      </Dialog>
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
            {n.locked && <Lock className="h-3.5 w-3.5 text-primary" aria-label="已锁定" />}
          </div>
          {n.summary && <p className={cn('mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground', isChapter ? 'line-clamp-1' : 'line-clamp-2')}>{n.summary}</p>}
          {isChapter && n.beats && Object.keys(n.beats).length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">{Object.entries(n.beats).slice(0, 4).map(([k, v]) => <span key={k} className="max-w-[260px] truncate rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">{beatLabel(k)}：{typeof v === 'string' ? v : JSON.stringify(v)}</span>)}</div>
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

type BeatRow = { k: string; v: string; json?: boolean }

function NodeEditor({ node, onClose, bookId }: { node: OutlineNode | null; onClose: () => void; bookId: number }) {
  const [lockOv, setLockOv] = useState<boolean | null>(null)
  const [f, setF] = useState<{ title: string; summary: string; beats: BeatRow[] }>({ title: '', summary: '', beats: [] })
  const [cur, setCur] = useState<OutlineNode | null>(null)
  const [ask, setAsk] = useState('')
  const [prop, setProp] = useState<{ title: string; summary: string; instruction: string; change: string; before: { title: string; summary: string } } | null>(null)
  const storage = useModelRoute('novelos.outline-route')
  const { start } = useJobs()
  const job = useActiveJob(node ? `outline-ai:${node.id}` : undefined)
  const load = (n: OutlineNode) => setF({ title: n.title, summary: n.summary, beats: Object.entries(n.beats ?? {}).map(([k, v]) => (typeof v === 'string' ? { k, v } : { k, v: JSON.stringify(v), json: true })) })
  if (node && node !== cur) {
    setCur(node)
    load(node)
    setProp(null)
    setLockOv(null)
  }
  const locked = lockOv ?? !!node?.locked
  const qc = useQueryClient()
  // 列表、对象类的节拍按 JSON 还原后再存（以前直接存成字符串，伏笔和出场人物会丢）
  const beatsOut = () => Object.fromEntries(f.beats.filter((b) => b.k.trim()).map((b) => {
    if (b.json) { try { return [b.k.trim(), JSON.parse(b.v)] } catch { /* 保留字符串 */ } }
    return [b.k.trim(), b.v]
  }))
  const m = useMutation({
    mutationFn: (o?: { title: string; summary: string; instruction?: string }) => api.updateOutline(node!.id, {
      title: o?.title ?? f.title, summary: o?.summary ?? f.summary, instruction: o?.instruction,
      ...(node!.level === 'chapter' ? { beats: f.beats.length ? beatsOut() : node!.beats } : {}),
    }),
    meta: { errorTitle: '保存失败' },
    onSuccess: (_n, o) => { qc.invalidateQueries({ queryKey: qk.outline(bookId) }); toast.success(o?.instruction ? '已采纳 AI 的修改，旧版本可撤回' : '大纲已保存'); setProp(null); setAsk(''); onClose() },
  })
  const undo = useMutation({
    mutationFn: () => api.undoOutline(node!.id),
    meta: { errorTitle: '撤回失败' },
    onSuccess: (n) => { qc.invalidateQueries({ queryKey: qk.outline(bookId) }); setCur(n); load(n); toast.success('已退回上一版') },
  })
  const suggest = () => {
    if (!node) return
    const instruction = ask.trim()
    start(api.suggestOutline(node.id, { instruction, route: storage.model }), {
      key: `outline-ai:${node.id}`, label: `AI 重写${LEVEL[node.level].label}`, silent: true,
      onSuccess: (j) => { const r = j.result as any; setProp({ ...r.proposal, instruction, change: r.change ?? '', before: { title: f.title, summary: f.summary } }) },
    })
  }
  const [confirmDel, setConfirmDel] = useState(false)
  const rm = useMutation({
    mutationFn: () => api.deleteOutline(node!.id),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.outline(bookId) }); qc.invalidateQueries({ queryKey: qk.chapters(bookId) }); toast.success('已删除'); setConfirmDel(false); onClose() },
  })
  const lock = useMutation({
    mutationFn: (v: boolean) => api.updateOutline(node!.id, { locked: v }),
    meta: { errorTitle: '操作失败' },
    onSuccess: (n) => { qc.invalidateQueries({ queryKey: qk.outline(bookId) }); setLockOv(!!n.locked); toast.success(n.locked ? '已锁定' : '已解锁') },
  })
  const versions = cur?.versions ?? 0
  return (
    <Sheet open={!!node} onOpenChange={(o) => !o && onClose()} title={`编辑${node ? LEVEL[node.level].label : ''}`} width={620}
      footer={<div className="flex w-full items-center gap-2">
        {node && node.level !== 'book' && <Button variant="ghost" className="text-danger hover:bg-danger-soft" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={() => setConfirmDel(true)}>删除</Button>}
        {node && <Button variant="ghost" loading={lock.isPending} icon={locked ? <Unlock className="h-3.5 w-3.5" /> : <Lock className="h-3.5 w-3.5" />} onClick={() => lock.mutate(!locked)}>{locked ? '解锁' : '锁定'}</Button>}
        {versions > 0 && <Tip content={cur?.last_instruction ? `撤回：${cur.last_instruction}` : '撤回上一次修改'}><Button variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={undo.isPending} onClick={() => undo.mutate()}>撤回（{versions}）</Button></Tip>}
        <div className="ml-auto flex gap-2"><Button variant="ghost" onClick={onClose}>取消</Button><Button variant="primary" loading={m.isPending} onClick={() => m.mutate(undefined)}>保存</Button></div>
      </div>}>
      <Dialog open={confirmDel} onOpenChange={setConfirmDel}>
        <DialogContent title={`删除「${node?.title ?? ''}」？`} desc={node?.level === 'chapter' ? '未提交的草稿会一起删除。' : '下面的所有子节点和未提交的草稿会一起删除。'}
          footer={<><Button variant="ghost" onClick={() => setConfirmDel(false)}>取消</Button><Button variant="danger" loading={rm.isPending} onClick={() => rm.mutate()}>删除</Button></>} />
      </Dialog>
      <div className="space-y-4">
        {prop ? (
          <div className="space-y-3 rounded-xl bg-primary-soft/30 p-3 hairline">
            <div className="text-[13px] font-semibold">AI 改好了，看看再决定{prop.change && <span className="font-normal text-muted-foreground"> · {prop.change}</span>}</div>
            <CompareRow label="标题" before={prop.before.title} after={prop.title} onChange={(v) => setProp({ ...prop, title: v })} />
            <CompareRow label="内容概要" before={prop.before.summary} after={prop.summary} onChange={(v) => setProp({ ...prop, summary: v })} multiline />
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setProp(null)}>放弃</Button>
              <Button size="sm" variant="primary" icon={<Check className="h-3.5 w-3.5" />} loading={m.isPending} onClick={() => m.mutate({ title: prop.title, summary: prop.summary, instruction: prop.instruction || 'AI 重写' })}>采纳并保存</Button>
            </div>
          </div>
        ) : locked ? (
          <div className="flex items-center gap-2 rounded-lg bg-primary-soft/50 px-3.5 py-2.5 text-[13px] text-primary"><Lock className="h-4 w-4 shrink-0" />已锁定，AI 不会改动这个节点</div>
        ) : node && (
          <AskBox title={`让 AI 重写这个${LEVEL[node.level].label}的概要`} storage={storage} value={ask} onChange={setAsk} onSubmit={suggest} job={job} refBookId={bookId}
            placeholder={node.level === 'book' ? '例如：主线别再围着身世转，改成揭开码头旧案' : node.level === 'volume' ? '例如：这一卷的卷末爆点更大，让反派当众翻车' : '例如：节奏快一点，弧末加一场反杀'} />
        )}
        <Field label="标题"><Input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="内容概要" hint={versions > 0 ? `改过 ${versions} 次，可撤回` : undefined}><MentionTextarea bookId={bookId} value={f.summary} onChange={(v) => setF({ ...f, summary: v })} placeholder="输入 @ 可引用设定条目"
          className="flex min-h-[160px] w-full rounded-md border border-input bg-surface px-3 py-2 text-sm leading-relaxed shadow-xs transition-[border,box-shadow] placeholder:text-muted-foreground/70 focus:border-primary/60 focus:shadow-glow focus:outline-none" /></Field>
        {node?.level === 'chapter' && (
          <div>
            <div className="mb-1.5 flex items-center justify-between"><span className="text-[13px] font-medium">节拍</span><Button size="xs" variant="ghost" icon={<Plus className="h-3 w-3" />} onClick={() => setF({ ...f, beats: [...f.beats, { k: '', v: '' }] })}>添加</Button></div>
            <div className="space-y-1.5">
              {f.beats.map((b, i) => {
                const isHeavyStage = b.k === 'stage_qi' || b.k === 'stage_cheng' || b.k === 'stage_zhuan' || b.k === 'stage_he'
                return (
                  <div key={i} className="flex items-start gap-1.5">
                    {BEAT_LABELS[b.k] ? <span className="flex w-[110px] shrink-0 items-center pt-2 text-[13px] text-muted-foreground">{BEAT_LABELS[b.k]}</span> : <Input className="w-[110px] shrink-0" value={b.k} placeholder="如：章尾钩子" onChange={(e) => setF({ ...f, beats: f.beats.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)) })} />}
                    {isHeavyStage ? (
                      <Textarea rows={3} value={b.v} className="flex-1 text-sm" onChange={(e) => setF({ ...f, beats: f.beats.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)) })} />
                    ) : (
                      <Input value={b.v} className={cn(b.json && 'font-mono text-xs')} onChange={(e) => setF({ ...f, beats: f.beats.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)) })} />
                    )}
                    <Button size="icon" variant="ghost" onClick={() => setF({ ...f, beats: f.beats.filter((_, j) => j !== i) })}><X className="h-4 w-4" /></Button>
                  </div>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </Sheet>
  )
}
