import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertTriangle, ArrowRight, Check, CheckCircle2, FileText, ImagePlus, Layers, ListTree, LayoutDashboard, Loader2, Package as PackageIcon,
  PenLine, Pencil, RotateCcw, Trash2, Undo2, Waypoints, X, XCircle,
} from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent } from '@/components/ui/dialog'
import { Progress } from '@/components/ui/misc'
import { Textarea } from '@/components/ui/input'
import { CompareRow, TropeAlert } from '@/components/common/AiAsk'
import { ConflictReview } from '@/components/common/ConflictReview'
import { DiffView } from '@/components/chapter/DiffView'
import * as D from '@radix-ui/react-dialog'
import { api, qk } from '@/lib/api'
import { useJobs } from '@/lib/jobs'
import type { AgentJobState, AgentProposal, BibleOp, BibleProposal } from '@/lib/types'
import { cardTypeLabel, cn } from '@/lib/utils'

const KIND_ICON: Record<string, typeof Layers> = {
  book_info: LayoutDashboard, bible: Layers, card_delete: Layers, outline_nodes: ListTree, chapter_rewrite: FileText,
  foreshadow_add: Waypoints, foreshadow_update: Waypoints, foreshadow_delete: Waypoints, package: PackageIcon, covers: ImagePlus, write_chapter: PenLine,
}
const STATUS: Record<AgentProposal['status'], { label: string; tone: 'neutral' | 'primary' | 'success' | 'warning' | 'danger' }> = {
  pending: { label: '待采纳', tone: 'primary' }, applied: { label: '已采纳', tone: 'success' }, rejected: { label: '已拒绝', tone: 'neutral' },
  reverted: { label: '已撤回', tone: 'neutral' }, running: { label: '执行中', tone: 'warning' }, failed: { label: '失败', tone: 'danger' },
}
const INFO_LABEL: Record<string, string> = { title: '书名', tagline: '一句话简介', premise: '核心设定' }
const PKG_LABEL: Record<string, string> = { blurb: '简介', cover_prompt: '封面提示词', tags: '标签', titles: '书名候选' }
const TIER: Record<string, string> = { short: '短线', mid: '中线', long: '长线' }
const EDITABLE = new Set(['book_info', 'outline_nodes', 'chapter_rewrite', 'foreshadow_add', 'package'])

function linkFor(p: AgentProposal): { to: string; label: string } | null {
  const b = `/books/${p.book_id}`
  switch (p.kind) {
    case 'book_info': return { to: b, label: '去概览' }
    case 'bible': case 'card_delete': return { to: `${b}/bible`, label: '去设定库' }
    case 'outline_nodes': return { to: `${b}/outline`, label: '去大纲' }
    case 'chapter_rewrite': return { to: `${b}/chapters/${p.payload.chapter_id}`, label: '去看这一章' }
    case 'write_chapter': return p.result?.chapter_id ? { to: `${b}/chapters/${p.result.chapter_id}`, label: '去看新章节' } : { to: `${b}/chapters`, label: '去章节' }
    case 'foreshadow_add': case 'foreshadow_update': case 'foreshadow_delete': return { to: `${b}/foreshadows`, label: '去伏笔' }
    case 'package': case 'covers': return { to: `${b}/package`, label: '去包装发布' }
  }
  return null
}

export function ProposalCard({ p, job, compact }: { p: AgentProposal; job?: AgentJobState | null; compact?: boolean }) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<Record<string, any>>({})
  const [review, setReview] = useState(false)
  const [diff, setDiff] = useState(false)
  const [confirmDel, setConfirmDel] = useState(false)
  const Icon = KIND_ICON[p.kind] ?? Layers
  const st = STATUS[p.status]
  const refresh = () => {
    qc.invalidateQueries({ queryKey: qk.agentSession(p.session_id) })
    qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== 'job' && x.queryKey[0] !== 'agent' })
  }
  const apply = useMutation({
    mutationFn: (b?: { edited?: Record<string, any>; ops?: BibleOp[] }) => api.applyProposal(p.id, b),
    meta: { errorTitle: '采纳失败' },
    onSuccess: (r) => {
      refresh()
      setEditing(false)
      setDiff(false)
      if (r.job) start(Promise.resolve(r.job), { label: p.kind === 'covers' ? '生成封面' : '写下一章', key: `agent-proposal:${p.id}`, onSuccess: refresh, onError: refresh })
      else toast.success(`已采纳：${p.title}`, { description: r.proposal.revertible ? '改之前的版本已保留，随时可以撤回' : undefined })
    },
  })
  const reject = useMutation({ mutationFn: () => api.rejectProposal(p.id), onSuccess: refresh, meta: { errorTitle: '操作失败' } })
  const revert = useMutation({
    mutationFn: () => api.revertProposal(p.id), meta: { errorTitle: '撤回失败' },
    onSuccess: () => { refresh(); toast.success('已撤回', { description: p.title }) },
  })
  const busy = apply.isPending || reject.isPending || revert.isPending
  const editedPayload = () => {
    if (p.kind === 'foreshadow_add') return { items: (p.payload.items as any[]).filter((_, i) => !(draft.skip ?? []).includes(i)) }
    if (p.kind === 'outline_nodes') return { items: Object.entries(draft).map(([node_id, v]) => ({ node_id: +node_id, ...(v as any) })) }
    return draft
  }
  const onApply = () => {
    if (p.kind === 'bible' && (p.needs_review || p.payload.removals?.length)) return setReview(true)
    if (p.destructive && !confirmDel) return setConfirmDel(true)
    apply.mutate(editing ? { edited: editedPayload() } : undefined)
  }
  const link = linkFor(p)

  return (
    <div className={cn('overflow-hidden rounded-xl bg-surface shadow-card hairline transition',
      p.status === 'pending' && 'ring-1 ring-primary/20', p.destructive && p.status === 'pending' && 'ring-danger/30',
      (p.status === 'rejected' || p.status === 'reverted') && 'opacity-70')}>
      <div className="flex items-start gap-2.5 border-b border-dashed px-3.5 py-2.5">
        <span className={cn('mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg', p.destructive ? 'bg-danger-soft text-danger' : 'bg-primary-soft text-primary')}>
          <Icon className="h-4 w-4" weight="duotone" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-[11.5px] text-muted-foreground">#{p.id}</span>
            <span className="min-w-0 break-words text-[13.5px] font-semibold">{p.title}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <Badge tone={st.tone} dot>{st.label}{p.auto_applied && p.status !== 'pending' ? '（自动）' : ''}</Badge>
            <Badge tone="outline">{p.kind_label}</Badge>
            {p.destructive && <Badge tone="danger">删除 · 需确认</Badge>}
            {p.needs_review && p.status === 'pending' && <Badge tone="warning">有冲突 · 需审阅</Badge>}
          </div>
        </div>
      </div>

      <div className="space-y-2.5 px-3.5 py-3 text-[13px]">
        {p.summary && <p className="leading-relaxed text-foreground/75">{p.summary}</p>}
        {!compact && <Preview p={p} editing={editing && p.status === 'pending'} draft={draft} setDraft={setDraft} />}
        {p.status === 'running' && (
          <div className="rounded-lg bg-primary-soft/60 px-3 py-2">
            <div className="mb-1.5 flex items-center justify-between text-[12.5px] text-primary">
              <span className="flex items-center gap-1.5"><Loader2 className="h-3.5 w-3.5 animate-spin" />{job?.message || '后台执行中…'}</span>
              <span className="num">{job?.progress ?? 0}%</span>
            </div>
            <Progress value={job?.progress ?? 5} />
          </div>
        )}
        {p.error && <p className="flex items-start gap-1.5 rounded-lg bg-danger-soft/60 px-3 py-2 text-[12.5px] text-danger"><XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />{p.error}</p>}
        {p.status === 'pending' && p.destructive && confirmDel && (
          <div className="flex items-center gap-2 rounded-lg bg-danger-soft/70 px-3 py-2 text-[12.5px] text-danger">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" /><span className="flex-1">确定要删除吗？删除前会存快照，之后仍可撤回。</span>
            <Button size="xs" variant="danger" loading={apply.isPending} onClick={() => apply.mutate(undefined)}>确认删除</Button>
            <Button size="xs" variant="ghost" onClick={() => setConfirmDel(false)}>算了</Button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5 border-t bg-subtle/50 px-3 py-2">
        {(p.status === 'pending' || p.status === 'failed') && !confirmDel && (
          <>
            <Button size="xs" variant={p.destructive ? 'danger' : 'primary'} loading={apply.isPending} disabled={busy} onClick={onApply}
              icon={p.kind === 'bible' && (p.needs_review || p.payload.removals?.length) ? <AlertTriangle className="h-3 w-3" /> : <Check className="h-3 w-3" />}>
              {p.kind === 'bible' && (p.needs_review || p.payload.removals?.length) ? '冲突审阅' : p.destructive ? '确认删除' : editing ? '按我改的采纳' : '采纳'}
            </Button>
            {EDITABLE.has(p.kind) && !editing && (
              p.kind === 'chapter_rewrite'
                ? <Button size="xs" variant="ghost" icon={<Pencil className="h-3 w-3" />} disabled={busy} onClick={() => setDiff(true)}>逐段对比后采纳</Button>
                : <Button size="xs" variant="ghost" icon={<Pencil className="h-3 w-3" />} disabled={busy} onClick={() => setEditing(true)}>编辑后采纳</Button>
            )}
            {editing && <Button size="xs" variant="ghost" onClick={() => { setEditing(false); setDraft({}) }}>取消编辑</Button>}
            <Button size="xs" variant="ghost" icon={<X className="h-3 w-3" />} loading={reject.isPending} disabled={busy} onClick={() => reject.mutate()}>拒绝</Button>
          </>
        )}
        {p.status === 'applied' && (
          <span className="flex items-center gap-1 text-[12px] text-success"><CheckCircle2 className="h-3.5 w-3.5" />已写入{p.auto_applied ? '（自动采纳）' : ''}</span>
        )}
        {p.status === 'applied' && p.revertible && (
          <Button size="xs" variant="ghost" icon={<Undo2 className="h-3 w-3" />} loading={revert.isPending} onClick={() => revert.mutate()}>撤回</Button>
        )}
        {p.status === 'reverted' && <span className="flex items-center gap-1 text-[12px] text-muted-foreground"><RotateCcw className="h-3.5 w-3.5" />已撤回，恢复到改之前</span>}
        {p.status === 'rejected' && <span className="text-[12px] text-muted-foreground">没有写入</span>}
        {link && (p.status === 'applied' || p.status === 'running') && (
          <Link to={link.to} className="ml-auto flex items-center gap-1 text-[12px] text-primary hover:underline">{link.label}<ArrowRight className="h-3 w-3" /></Link>
        )}
      </div>

      {p.kind === 'bible' && (
        <Dialog open={review} onOpenChange={setReview}>
          <DialogContent wide title={`冲突审阅 · 提案 #${p.id}`} desc="逐条决定保留旧的 / 用新的替换 / 两者都留 / 删掉旧的；写入前自动存快照，可撤回。" className="max-w-3xl">
            {review && <ConflictReview bookId={p.book_id} proposal={p.payload as BibleProposal} onCancel={() => setReview(false)}
              onDone={() => { setReview(false); refresh(); toast.success('设定库已更新', { description: '改之前的版本已存快照，可在这里撤回' }) }}
              onApplyOps={(ops) => api.applyProposal(p.id, { ops })} />}
          </DialogContent>
        </Dialog>
      )}
      {p.kind === 'chapter_rewrite' && (
        <D.Root open={diff} onOpenChange={setDiff}>
          <D.Portal>
            <D.Overlay className="fixed inset-0 z-50 bg-black/30 data-[state=open]:animate-fade-in" />
            <D.Content className="fixed inset-3 z-50 overflow-y-auto rounded-xl bg-background shadow-pop hairline focus:outline-none md:inset-8">
              <D.Title className="sr-only">逐段对比</D.Title><D.Description className="sr-only">逐段接受或撤销改动</D.Description>
              {diff && <DiffView title={`第 ${p.payload.number} 章 · Agent 改写稿（提案 #${p.id}）`} before={p.payload.before} after={p.payload.after}
                applying={apply.isPending} onClose={() => setDiff(false)} onApply={(content) => apply.mutate({ edited: { content } })} />}
            </D.Content>
          </D.Portal>
        </D.Root>
      )}
    </div>
  )
}

function Preview({ p, editing, draft, setDraft }: { p: AgentProposal; editing: boolean; draft: Record<string, any>; setDraft: (d: Record<string, any>) => void }) {
  const pl = p.payload
  switch (p.kind) {
    case 'book_info': {
      const keys = (['title', 'tagline', 'premise'] as const).filter((k) => pl.proposal?.[k] !== pl.current?.[k])
      const imp = pl.impact
      return (
        <div className="space-y-2.5">
          {keys.map((k) => <CompareRow key={k} label={INFO_LABEL[k]} before={pl.current?.[k] ?? ''} after={draft[k] ?? pl.proposal?.[k] ?? ''} multiline={k === 'premise'}
            onChange={editing ? (v) => setDraft({ ...draft, [k]: v }) : undefined} />)}
          {!keys.length && <p className="text-muted-foreground">没有实际改动。</p>}
          {imp?.total > 0 && (
            <p className="rounded-lg bg-warning-soft/60 px-3 py-2 text-[12.5px] text-warning">
              「{(pl.terms ?? []).join('、')}」还出现在 {imp.cards?.length ?? 0} 张设定卡、{imp.outline?.length ?? 0} 个大纲节点
              {imp.chapters?.length ? `、第 ${imp.chapters.map((c: any) => c.number).join('、')} 章正文` : ''}里
            </p>
          )}
          <TropeAlert hits={pl.trope_hits} compact />
        </div>
      )
    }
    case 'bible': {
      const items: any[] = pl.items ?? []
      return (
        <ul className="space-y-1.5">
          {items.slice(0, 12).map((x) => (
            <li key={x.key} className="rounded-lg bg-subtle px-3 py-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone={x.action === 'update' ? 'warning' : 'success'}>{x.action === 'update' ? '改写' : '新增'}</Badge>
                <span className="font-medium">{x.card.name}</span>
                <span className="text-[11.5px] text-muted-foreground">{cardTypeLabel(x.card.type)}</span>
                {x.conflicts?.length > 0 && <Badge tone="danger">冲突 {x.conflicts.length}</Badge>}
              </div>
              {x.old && x.action === 'update' && x.old.summary !== x.card.summary
                ? <div className="mt-1 space-y-0.5 text-[12.5px]"><p className="text-foreground/45 line-through decoration-danger/40">{x.old.summary}</p><p>{x.card.summary}</p></div>
                : <p className="mt-1 text-[12.5px] text-foreground/70">{x.card.summary}</p>}
              {x.conflicts?.map((c: any) => <p key={c.card_id} className="mt-1 text-[12px] text-danger">与「{c.name}」：{c.reason}</p>)}
            </li>
          ))}
          {items.length > 12 && <li className="text-[12px] text-muted-foreground">…还有 {items.length - 12} 张</li>}
          {pl.removals?.length > 0 && <li className="rounded-lg bg-danger-soft/50 px-3 py-2 text-[12.5px] text-danger">建议删除旧卡：{pl.removals.map((r: any) => r.name).join('、')}（需在冲突审阅里确认）</li>}
        </ul>
      )
    }
    case 'card_delete':
      return <div className="rounded-lg bg-danger-soft/50 px-3 py-2"><div className="font-medium">{pl.card?.name}<span className="ml-1.5 text-[11.5px] font-normal text-muted-foreground">{cardTypeLabel(pl.card?.type)}</span></div><p className="mt-0.5 text-[12.5px] text-foreground/70">{pl.card?.summary}</p></div>
    case 'outline_nodes':
      return (
        <div className="space-y-3">
          {(pl.items as any[]).slice(0, 8).map((x) => {
            const d = draft[x.node_id] ?? {}
            return (
              <div key={x.node_id} className="space-y-1.5">
                {x.old.title !== x.new.title && <CompareRow label="标题" before={x.old.title} after={d.title ?? x.new.title} onChange={editing ? (v) => setDraft({ ...draft, [x.node_id]: { ...d, title: v } }) : undefined} />}
                <CompareRow label={`「${x.old.title}」概要`} before={x.old.summary} after={d.summary ?? x.new.summary} multiline
                  onChange={editing ? (v) => setDraft({ ...draft, [x.node_id]: { ...d, summary: v } }) : undefined} />
                {x.beats_changed && <p className="text-[12px] text-muted-foreground">章细纲节拍里的旧说法也会一并替换</p>}
              </div>
            )
          })}
        </div>
      )
    case 'chapter_rewrite':
      return <ChapterPreview pl={pl} />
    case 'foreshadow_add': {
      const skip: number[] = draft.skip ?? []
      return (
        <ul className="space-y-1.5">
          {(pl.items as any[]).map((x, i) => (
            <li key={i} className={cn('flex items-start gap-2 rounded-lg bg-subtle px-3 py-2', skip.includes(i) && 'opacity-45')}>
              {editing && <input type="checkbox" className="mt-1 accent-[hsl(var(--primary))]" checked={!skip.includes(i)}
                onChange={() => setDraft({ ...draft, skip: skip.includes(i) ? skip.filter((k) => k !== i) : [...skip, i] })} />}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">{x.tier && <Badge tone="primary">{TIER[x.tier] ?? x.tier}</Badge>}<span className="font-medium">{x.desc}</span></div>
                <p className="mt-0.5 text-[12px] text-muted-foreground">{x.plant_ch ? `第 ${x.plant_ch} 章埋` : '未定埋设章'}{x.resolve_ch ? ` · 第 ${x.resolve_ch} 章收` : ''}{x.note ? ` · ${x.note}` : ''}</p>
              </div>
            </li>
          ))}
          {pl.attach && <li className="text-[12px] text-muted-foreground">采纳后同时写进对应章细纲（已写的章不动）</li>}
        </ul>
      )
    }
    case 'foreshadow_update':
      return <ul className="space-y-1">{Object.entries(pl.changes ?? {}).map(([k, v]) => <li key={k} className="text-[12.5px]"><span className="text-muted-foreground">{k}：</span><span className="text-foreground/45 line-through">{String(pl.before?.[k] ?? '空')}</span> → <span className="font-medium">{String(v)}</span></li>)}</ul>
    case 'foreshadow_delete':
      return <p className="rounded-lg bg-danger-soft/50 px-3 py-2 text-[12.5px]"><Trash2 className="mr-1 inline h-3.5 w-3.5 text-danger" />{pl.row?.desc}</p>
    case 'package':
      return (
        <div className="space-y-2.5">
          {Object.keys(pl.after ?? {}).map((k) => Array.isArray(pl.after[k])
            ? <ChipsCompare key={k} label={PKG_LABEL[k] ?? k} before={pl.before?.[k] ?? []} after={pl.after[k]} />
            : <CompareRow key={k} label={PKG_LABEL[k] ?? k} before={pl.before?.[k] ?? ''} after={draft[k] ?? pl.after[k]} multiline
                onChange={editing ? (v) => setDraft({ ...draft, [k]: v }) : undefined} />)}
          <TropeAlert hits={pl.trope_hits} compact />
        </div>
      )
    case 'covers':
      return (
        <div className="space-y-2">
          <p className="line-clamp-3 rounded-lg bg-subtle px-3 py-2 text-[12.5px] text-foreground/70">{pl.prompt || '用包装里的封面提示词'}</p>
          {(p.result?.covers?.length ?? 0) > 0 && <div className="flex gap-2 overflow-x-auto pb-1">{(p.result?.covers as string[]).map((u: string) => <img key={u} src={u} alt="封面" className="h-32 w-24 shrink-0 rounded-md object-cover hairline" />)}</div>}
        </div>
      )
    case 'write_chapter':
      return <p className="text-[12.5px] text-muted-foreground">第 {pl.number} 章{pl.variants > 1 ? ` · 写 ${pl.variants} 个版本供挑选` : ''}。写完是草稿，在章节页提交才入账。</p>
  }
  return null
}

function ChipsCompare({ label, before, after }: { label: string; before: string[]; after: string[] }) {
  return (
    <div className="space-y-1">
      <div className="text-[12.5px] font-medium text-foreground/85">{label}</div>
      {before.length > 0 && <div className="flex flex-wrap gap-1">{before.map((t) => <span key={t} className="rounded bg-danger-soft/50 px-1.5 py-0.5 text-[12px] text-foreground/50 line-through">{t}</span>)}</div>}
      <div className="flex flex-wrap gap-1">{after.map((t) => <span key={t} className="rounded bg-success-soft/70 px-1.5 py-0.5 text-[12px]">{t}</span>)}</div>
    </div>
  )
}

function ChapterPreview({ pl }: { pl: Record<string, any> }) {
  const [open, setOpen] = useState(false)
  const firstChange = useMemo(() => {
    const a = String(pl.before ?? '').split('\n').filter(Boolean)
    const b = String(pl.after ?? '').split('\n').filter(Boolean)
    const i = b.findIndex((x, k) => x !== a[k])
    return i >= 0 ? { before: a[i] ?? '', after: b[i] } : null
  }, [pl.before, pl.after])
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-3 text-[12px] text-muted-foreground">
        <span>字数 <span className="num text-foreground">{pl.words_before}</span> → <span className="num text-foreground">{pl.words_after}</span></span>
        {pl.ai_score_after != null && <span>改后 AI 味 <span className="num text-foreground">{pl.ai_score_after}</span></span>}
      </div>
      {firstChange && (
        <div className="grid gap-1.5 text-[12.5px]">
          <p className="line-clamp-2 rounded-md bg-danger-soft/40 px-2.5 py-1.5 font-serif text-foreground/55">{firstChange.before || '（新增段落）'}</p>
          <p className="line-clamp-3 rounded-md bg-success-soft/60 px-2.5 py-1.5 font-serif">{firstChange.after}</p>
        </div>
      )}
      <button className="text-[12px] text-primary hover:underline" onClick={() => setOpen((o) => !o)}>{open ? '收起改写稿' : '展开改写稿全文'}</button>
      {open && <Textarea readOnly value={pl.after} rows={10} className="bg-subtle font-serif text-[13px]" />}
    </div>
  )
}
