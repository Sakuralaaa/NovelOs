import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'framer-motion'
import { toast } from 'sonner'
import {
  AlertTriangle, Bot, BookOpen, Check, ChevronDown, ChevronRight, Loader2, MoreHorizontal, Pencil, Plus, RotateCcw, Send,
  Sparkles, StopSquare, Trash2, Wand2, Wrench, XCircle,
} from '@/components/icons'
import * as DM from '@radix-ui/react-dropdown-menu'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tip } from '@/components/ui/tooltip'
import { ModelSelect, useModelRoute } from '@/components/common/AiAsk'
import { ProposalCard } from './ProposalCard'
import { useAgentSession, useAgentSessions, useAgentTools } from './useAgent'
import { useBook } from '@/hooks/queries'
import { api, qk } from '@/lib/api'
import type { AgentMessage, AgentProposal, AgentSessionDetail } from '@/lib/types'
import { cn } from '@/lib/utils'

const FALLBACK_EXAMPLES = ['别强调拳法，把碎星神通改个名，同步设定和大纲', '规划 3 条伏笔，前十章至少一条长线', '简介再抓人一点，突出反差', '写下一章']

interface Turn { user: AgentMessage | null; items: AgentMessage[] }

function toTurns(messages: AgentMessage[]): Turn[] {
  const out: Turn[] = []
  for (const m of messages) {
    if (m.role === 'user' || !out.length) out.push({ user: m.role === 'user' ? m : null, items: m.role === 'user' ? [] : [m] })
    else out[out.length - 1].items.push(m)
  }
  return out
}

/** 每本书的专属 Agent 对话。variant=page 用于「Agent」页，drawer 用于各书页右下角呼出的抽屉。 */
export function AgentChat({ bookId, variant = 'page', autoFocus }: { bookId: number; variant?: 'page' | 'drawer'; autoFocus?: boolean }) {
  const qc = useQueryClient()
  const lsKey = `novelos-agent-session-${bookId}`
  const sessions = useAgentSessions(bookId)
  const [sid, setSidState] = useState<number | null>(() => Number(localStorage.getItem(lsKey)) || null)
  const setSid = (v: number | null) => { setSidState(v); if (v) localStorage.setItem(lsKey, String(v)); else localStorage.removeItem(lsKey) }
  useEffect(() => {
    const list = sessions.data
    if (!list) return
    if (!list.length) { if (sid) setSid(null); return }
    if (!sid || !list.some((s) => s.id === sid)) setSid(list[0].id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions.data])
  const detail = useAgentSession(sid)
  const d = detail.data
  const book = useBook(bookId)
  const tools = useAgentTools()
  const storage = useModelRoute('novelos-agent-route')
  const [text, setText] = useState('')
  const [pendingUser, setPendingUser] = useState<string | null>(null)
  const scroller = useRef<HTMLDivElement>(null)
  const running = !!d?.job || !!pendingUser

  const invalidateSessions = () => qc.invalidateQueries({ queryKey: qk.agentSessions(bookId) })
  const newSession = useMutation({
    mutationFn: () => api.createAgentSession(bookId),
    onSuccess: (s) => { setSid(s.id); invalidateSessions() },
    meta: { errorTitle: '新建对话失败' },
  })
  const send = useMutation({
    mutationFn: async (content: string) => {
      let id = sid
      if (!id) { const s = await api.createAgentSession(bookId); id = s.id; setSid(id) }
      return { id, r: await api.sendAgent(id, { content, route: storage.model }) }
    },
    onMutate: (content) => { setPendingUser(content); setText('') },
    onSuccess: ({ id }) => { qc.invalidateQueries({ queryKey: qk.agentSession(id) }); invalidateSessions() },
    onError: (_e, content) => setText(content),
    onSettled: () => setTimeout(() => setPendingUser(null), 300),
    meta: { errorTitle: '发送失败' },
  })
  const stop = useMutation({ mutationFn: () => api.stopAgent(sid!), onSuccess: () => toast('已请求停止，当前这一步做完就停') })
  const clear = useMutation({
    mutationFn: () => api.clearAgentSession(sid!),
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.agentSession(sid!) }); invalidateSessions(); toast.success('已清空这条对话', { description: '已经写入的改动不受影响' }) },
    meta: { errorTitle: '清空失败' },
  })
  const remove = useMutation({
    mutationFn: () => api.deleteAgentSession(sid!),
    onSuccess: () => { setSid(null); invalidateSessions() },
    meta: { errorTitle: '删除失败' },
  })
  const rename = useMutation({
    mutationFn: (title: string) => api.renameAgentSession(sid!, title),
    onSuccess: invalidateSessions,
  })
  const autoApply = useMutation({
    mutationFn: (v: boolean) => api.saveAgentSettings(bookId, v),
    onSuccess: (r) => { qc.setQueryData(qk.book(bookId), r.book); toast.success(r.auto_apply ? '已打开自动采纳' : '已关闭自动采纳', { description: r.auto_apply ? '无冲突的改动直接写入，仍可撤回；删除类操作仍需确认' : '所有改动都先给你看提案' }) },
    meta: { errorTitle: '设置失败' },
  })

  const turns = useMemo(() => toTurns(d?.messages ?? []), [d?.messages])
  const propsById = useMemo(() => new Map((d?.proposals ?? []).map((p) => [p.id, p])), [d?.proposals])
  const pendingCount = (d?.proposals ?? []).filter((p) => p.status === 'pending').length

  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [d?.messages.length, pendingUser, d?.job?.message])

  const submit = (v = text) => { const t = v.trim(); if (t && !running && !send.isPending) send.mutate(t) }
  const examples = tools.data?.examples ?? FALLBACK_EXAMPLES
  const sessionOpts = (sessions.data ?? []).map((s) => ({ value: String(s.id), label: <span className="truncate">{s.title}</span> }))
  const empty = !turns.length && !pendingUser

  return (
    <div className={cn('flex h-full min-h-0 flex-col', variant === 'page' && 'rounded-2xl bg-surface shadow-card hairline')}>
      {/* 顶栏：会话、新对话、自动采纳 */}
      <div className={cn('flex flex-wrap items-center gap-2 border-b px-3 py-2.5', variant === 'page' && 'px-4')}>
        <div className="min-w-0 flex-1 basis-[160px]">
          {sessionOpts.length > 0
            ? <Select value={sid ? String(sid) : null} onChange={(v) => v && setSid(Number(v))} options={sessionOpts} placeholder="选择对话" className="h-8 text-[13px]" />
            : <span className="px-1 text-[13px] text-muted-foreground">还没有对话</span>}
        </div>
        <Tip content="新对话"><Button size="icon-sm" variant="ghost" loading={newSession.isPending} onClick={() => newSession.mutate()} aria-label="新对话"><Plus className="h-4 w-4" /></Button></Tip>
        {sid && (
          <DM.Root>
            <DM.Trigger asChild><Button size="icon-sm" variant="ghost" aria-label="更多"><MoreHorizontal className="h-4 w-4" /></Button></DM.Trigger>
            <DM.Portal>
              <DM.Content align="end" sideOffset={6} className="z-[60] min-w-[160px] rounded-lg bg-popover p-1 text-[13px] shadow-pop hairline">
                <DM.Item className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 outline-none data-[highlighted]:bg-muted"
                  onSelect={() => { const t = window.prompt('对话名称', d?.session.title ?? ''); if (t?.trim()) rename.mutate(t.trim()) }}><Pencil className="h-3.5 w-3.5" />重命名</DM.Item>
                <DM.Item disabled={running} className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-muted"
                  onSelect={() => { if (window.confirm('清空这条对话的消息和提案？已经写入的改动不受影响。')) clear.mutate() }}><RotateCcw className="h-3.5 w-3.5" />清空对话</DM.Item>
                <DM.Item disabled={running} className="flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-danger outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-danger-soft"
                  onSelect={() => { if (window.confirm('删除这条对话？')) remove.mutate() }}><Trash2 className="h-3.5 w-3.5" />删除对话</DM.Item>
              </DM.Content>
            </DM.Portal>
          </DM.Root>
        )}
        <Tip content="打开后：无冲突、非删除的改动直接写入（写入前留快照/旧版本，可撤回）。删除类操作永远要你确认。">
          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg px-1.5 py-1 text-[12.5px] text-muted-foreground hover:bg-muted">
            <Switch checked={!!book.data?.agent_auto_apply} onCheckedChange={(v) => autoApply.mutate(v)} className="scale-[0.85]" />
            自动采纳
          </label>
        </Tip>
      </div>

      {/* 消息区 */}
      <div ref={scroller} className={cn('min-h-0 flex-1 overflow-y-auto', variant === 'page' ? 'px-5 py-6 md:px-8' : 'px-3.5 py-4')}>
        {empty ? (
          <Welcome title={book.data?.title} examples={examples} onPick={(e) => setText(e)} maxSteps={tools.data?.max_steps} toolCount={tools.data?.tools.length} />
        ) : (
          <div className={cn('mx-auto space-y-6', variant === 'page' ? 'max-w-[820px]' : '')}>
            {turns.map((t, i) => (
              <TurnView key={t.user?.id ?? `t${i}`} turn={t} propsById={propsById} detail={d}
                live={i === turns.length - 1 && !!d?.job} compact={variant === 'drawer'} />
            ))}
            {pendingUser && !turns.some((t) => t.user?.content === pendingUser && t === turns[turns.length - 1]) && (
              <div className="space-y-3"><UserBubble text={pendingUser} /><Thinking message="正在发送…" /></div>
            )}
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className={cn('border-t bg-surface/80 px-3 pb-3 pt-2.5', variant === 'page' && 'rounded-b-2xl px-4')}>
        {pendingCount > 0 && !running && (
          <div className="mb-2 flex items-center gap-1.5 text-[12px] text-primary"><Sparkles className="h-3.5 w-3.5" />有 {pendingCount} 个提案等你采纳或拒绝</div>
        )}
        {!empty && !running && (
          <div className="mb-2 flex gap-1.5 overflow-x-auto pb-0.5">
            {examples.slice(0, 4).map((e) => (
              <button key={e} onClick={() => setText(e)} className="shrink-0 rounded-full bg-subtle px-2.5 py-1 text-[12px] text-foreground/70 transition hover:bg-primary-soft hover:text-primary hairline">{e}</button>
            ))}
          </div>
        )}
        <div className="rounded-xl border bg-background shadow-xs transition-colors focus-within:border-primary/45">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={variant === 'page' ? 3 : 2} autoFocus={autoFocus}
            placeholder="告诉 Agent 要改什么，比如：别强调拳法，把碎星神通改个名，同步设定和大纲（Enter 发送，Shift+Enter 换行）"
            className="block min-h-[60px] w-full resize-none bg-transparent px-3.5 pt-3 text-[13.5px] leading-relaxed outline-none placeholder:text-muted-foreground/70"
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit() } }} />
          <div className="flex items-center justify-between gap-2 px-2 pb-2">
            <ModelSelect storage={storage} emptyLabel="默认（Agent 路由）" className="w-[180px]" />
            {running ? (
              <Button size="sm" variant="secondary" icon={<StopSquare className="h-3.5 w-3.5" />} loading={stop.isPending} disabled={!d?.job} onClick={() => stop.mutate()}>停止</Button>
            ) : (
              <Button size="sm" variant="primary" icon={<Send className="h-3.5 w-3.5" />} loading={send.isPending} disabled={!text.trim()} onClick={() => submit()}>发送</Button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function Welcome({ title, examples, onPick, maxSteps, toolCount }: { title?: string; examples: string[]; onPick: (e: string) => void; maxSteps?: number; toolCount?: number }) {
  return (
    <div className="mx-auto flex max-w-[560px] flex-col items-center py-6 text-center">
      <div className="relative mb-4">
        <div className="absolute inset-0 -z-10 rounded-full bg-primary/10 blur-xl" />
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-soft text-primary hairline"><Bot className="h-7 w-7" weight="duotone" /></span>
      </div>
      <h3 className="font-serif text-[17px] font-semibold">《{title ?? '…'}》的专属 Agent</h3>
      <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">
        它能读这本书的一切，也能指挥设定库、大纲、章节、伏笔、包装和封面去改。改动先变成提案给你过目，你点采纳才写入，写入后也能撤回。
      </p>
      <div className="mt-5 grid w-full gap-2 text-left">
        {examples.map((e) => (
          <button key={e} onClick={() => onPick(e)} className="group flex items-center gap-2.5 rounded-xl bg-surface px-3.5 py-2.5 text-left text-[13px] shadow-xs transition hover:shadow-card hairline hover:border-primary/30">
            <Wand2 className="h-4 w-4 shrink-0 text-primary/70 group-hover:text-primary" />
            <span className="flex-1">{e}</span>
            <ChevronRight className="h-3.5 w-3.5 text-muted-foreground opacity-0 transition group-hover:opacity-100" />
          </button>
        ))}
      </div>
      {toolCount ? <p className="mt-4 text-[11.5px] text-muted-foreground">可调用 {toolCount} 个工具 · 每轮最多 {maxSteps} 步 · 删除类操作永远需要你确认</p> : null}
    </div>
  )
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-primary px-3.5 py-2 text-[13.5px] leading-relaxed text-primary-foreground shadow-xs">{text}</div>
    </div>
  )
}

function Thinking({ message }: { message?: string }) {
  return (
    <div className="flex items-center gap-2 pl-9 text-[12.5px] text-muted-foreground">
      <span className="flex gap-0.5">{[0, 1, 2].map((i) => <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-primary/60" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1.2, repeat: Infinity, delay: i * 0.18 }} />)}</span>
      <span className="truncate">{message || '思考中…'}</span>
    </div>
  )
}

/** 把助手消息里的 #12 渲染成小标签 */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(#\d+)/g)
  return <>{parts.map((s, i) => /^#\d+$/.test(s) ? <span key={i} className="mx-0.5 rounded bg-primary-soft px-1 font-mono text-[12px] text-primary">{s}</span> : <Fragment key={i}>{s}</Fragment>)}</>
}

function TurnView({ turn, propsById, detail, live, compact }: {
  turn: Turn; propsById: Map<number, AgentProposal>; detail?: AgentSessionDetail; live: boolean; compact: boolean
}) {
  const results = new Map(turn.items.filter((m) => m.role === 'tool').map((m) => [m.tool_call_id, m]))
  const steps = turn.items.filter((m) => m.role === 'assistant' && m.tool_calls.length)
  const last = turn.items.at(-1)
  const final = turn.items.filter((m) => m.role === 'assistant' && !m.tool_calls.length && m.content).at(-1)
  const notices = turn.items.filter((m) => m.role === 'notice')
  const pids = turn.items.flatMap((m) => m.proposal_ids)
  const nCalls = steps.reduce((n, s) => n + s.tool_calls.length, 0)
  const [open, setOpen] = useState(live)
  useEffect(() => { if (live) setOpen(true) }, [live])

  return (
    <div className="space-y-3">
      {turn.user && <UserBubble text={turn.user.content} />}
      {(turn.items.length > 0 || live) && (
        <div className="flex gap-2.5">
          <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-soft text-primary hairline"><Bot className="h-4 w-4" weight="duotone" /></span>
          <div className="min-w-0 flex-1 space-y-2.5">
            {nCalls > 0 && (
              <div className="rounded-xl bg-subtle/70 hairline">
                <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] text-muted-foreground hover:text-foreground">
                  {live ? <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> : <Wrench className="h-3.5 w-3.5" />}
                  <span className="flex-1">{live ? '正在处理' : '处理过程'} · {steps.length} 步 · 调用 {nCalls} 次工具</span>
                  <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', !open && '-rotate-90')} />
                </button>
                <AnimatePresence initial={false}>
                  {open && (
                    <motion.ol initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.18 }}
                      className="overflow-hidden border-t border-dashed px-3 pb-2 pt-1.5">
                      {steps.map((s, si) => (
                        <li key={s.id} className="py-1">
                          {s.content && <p className="mb-1 text-[12.5px] leading-relaxed text-foreground/70"><RichText text={s.content} /></p>}
                          <div className="space-y-1">
                            {s.tool_calls.map((c) => <StepRow key={c.id} call={c} result={results.get(c.id)} live={live} index={si + 1} />)}
                          </div>
                        </li>
                      ))}
                    </motion.ol>
                  )}
                </AnimatePresence>
              </div>
            )}
            {pids.map((id) => propsById.get(id)).filter(Boolean).map((p) => (
              <ProposalCard key={p!.id} p={p!} job={detail?.proposal_jobs?.[String(p!.id)]} compact={false} />
            ))}
            {final && (
              <div className={cn('whitespace-pre-wrap break-words rounded-2xl rounded-tl-md bg-surface px-3.5 py-2.5 leading-relaxed shadow-xs hairline', compact ? 'text-[13px]' : 'text-[13.5px]')}>
                <RichText text={final.content} />
              </div>
            )}
            {notices.map((n) => (
              <p key={n.id} className={cn('flex items-start gap-1.5 rounded-lg px-3 py-2 text-[12.5px]', n.status === 'error' ? 'bg-warning-soft text-warning' : 'bg-subtle text-muted-foreground')}>
                {n.status === 'error' ? <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" />}{n.content}
              </p>
            ))}
            {live && last?.role !== 'notice' && <Thinking message={detail?.job?.message} />}
          </div>
        </div>
      )}
    </div>
  )
}

function argText(args: Record<string, any>) {
  const vals = Object.entries(args).filter(([, v]) => v !== '' && v != null && !(Array.isArray(v) && !v.length))
  if (!vals.length) return ''
  return vals.map(([k, v]) => (typeof v === 'string' ? v : `${k}=${JSON.stringify(v)}`)).join(' · ')
}

function StepRow({ call, result, live, index }: { call: AgentMessage['tool_calls'][number]; result?: AgentMessage; live: boolean; index: number }) {
  const [open, setOpen] = useState(false)
  const pending = !result
  const err = result?.status === 'error'
  const Icon = call.kind === 'write' ? Wand2 : BookOpen
  const args = argText(call.arguments)
  return (
    <div className="rounded-lg">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full items-start gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-background/70">
        <span className="mt-[3px] w-4 shrink-0 text-center font-mono text-[10.5px] text-muted-foreground/70">{index}</span>
        <Icon className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', call.kind === 'write' ? 'text-primary' : 'text-muted-foreground')} />
        <span className="min-w-0 flex-1 text-[12.5px]">
          <span className="font-medium text-foreground/85">{call.label}</span>
          {args && <span className="ml-1.5 text-muted-foreground">{args.length > 48 ? args.slice(0, 48) + '…' : args}</span>}
          {result?.summary && <span className={cn('block truncate', err ? 'text-danger' : 'text-foreground/60')}>→ {result.summary}</span>}
        </span>
        {pending ? (live ? <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primary" /> : <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />)
          : err ? <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-danger" /> : <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-success" />}
      </button>
      {open && (
        <div className="ml-6 mt-1 space-y-1.5 text-[11.5px]">
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md bg-background px-2.5 py-1.5 font-mono text-foreground/70 hairline">{JSON.stringify(call.arguments, null, 1)}</pre>
          {result && <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-md bg-background px-2.5 py-1.5 font-mono text-foreground/60 hairline">{prettyJson(result.content)}</pre>}
        </div>
      )}
    </div>
  )
}

function prettyJson(s: string) {
  try { return JSON.stringify(JSON.parse(s), null, 1) } catch { return s }
}
