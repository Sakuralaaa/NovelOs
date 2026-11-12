import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Check, Plus, Trash2 } from '@/components/icons'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { TropeAlert } from '@/components/common/AiAsk'
import { api, qk } from '@/lib/api'
import type { BibleChoice, BibleItem, BibleOp, BibleProposal, CardDraft } from '@/lib/types'
import { cardTypeLabel, cn } from '@/lib/utils'

const CHOICES: { key: BibleChoice; label: string; tip: string }[] = [
  { key: 'keep_old', label: '保留旧的', tip: '不要这条新内容，旧卡不动' },
  { key: 'replace', label: '用新的替换', tip: '新内容写进旧卡（保留旧卡关联的人物状态）' },
  { key: 'both', label: '两者都留', tip: '旧卡不动，新内容另存一张（同名会自动加后缀）' },
  { key: 'delete_old', label: '删掉旧的', tip: '旧卡和它关联的人物状态一起删，新内容单独新建' },
]
const MODE_LABEL = { rewrite: '完全重写', add: '纯增加', optimize: '优化' } as const

const isReview = (x: BibleItem) => x.conflicts.length > 0 || x.action === 'update'
const primaryId = (x: BibleItem) => x.target_id ?? x.conflicts[0]?.card_id ?? null

/** 设定库「冲突审阅」：新增卡可勾选；冲突/改写逐条选择处理方式，支持批量；采纳前自动存快照，可回滚 */
export function ConflictReview({ bookId, proposal, onDone, onCancel, applyMode }: {
  bookId: number; proposal: BibleProposal; onDone: () => void; onCancel?: () => void; applyMode?: string
}) {
  const qc = useQueryClient()
  const clean = proposal.items.filter((x) => !isReview(x))
  const review = proposal.items.filter(isReview)
  const [picked, setPicked] = useState<Set<string>>(() => new Set(clean.map((x) => x.key)))
  const [choice, setChoice] = useState<Record<string, BibleChoice>>(() => Object.fromEntries(review.map((x) => [x.key, x.default === 'add' ? 'replace' : x.default])))
  const [sel, setSel] = useState<Set<string>>(new Set())
  const [removeIds, setRemoveIds] = useState<Set<number>>(() => new Set(proposal.removals.map((r) => r.card_id)))
  const [busy, setBusy] = useState(false)

  const ops = useMemo<BibleOp[]>(() => {
    const out: BibleOp[] = []
    const touched = new Set<number>()
    clean.forEach((x) => { if (picked.has(x.key)) out.push({ op: 'create', card: x.card }) })
    review.forEach((x) => {
      const c = choice[x.key] ?? 'keep_old'
      const pid = primaryId(x)
      if (pid != null) touched.add(pid)
      if (c === 'keep_old' || c === 'skip') return
      if (c === 'replace' && pid != null) out.push({ op: 'update', card_id: pid, card: x.card })
      else if (c === 'delete_old' && pid != null) { out.push({ op: 'delete', card_id: pid }); out.push({ op: 'create', card: x.card }) }
      else out.push({ op: 'create', card: x.card })
    })
    proposal.removals.forEach((r) => { if (removeIds.has(r.card_id) && !touched.has(r.card_id)) out.push({ op: 'delete', card_id: r.card_id }) })
    return out
  }, [clean, review, picked, choice, removeIds, proposal.removals])

  const bulk = (c: BibleChoice) => {
    const keys = sel.size ? [...sel] : review.map((x) => x.key)
    setChoice((m) => ({ ...m, ...Object.fromEntries(keys.map((k) => [k, c])) }))
  }
  const apply = async () => {
    setBusy(true)
    try {
      const r = await api.applyBible(bookId, { mode: applyMode ?? proposal.mode, instruction: proposal.instruction, ops, facts: proposal.facts })
      qc.invalidateQueries({ queryKey: qk.cards(bookId) })
      qc.invalidateQueries({ queryKey: qk.facts(bookId) })
      toast.success(`设定库已更新：新增 ${r.created}、修改 ${r.updated}、删除 ${r.deleted}`, { description: '改之前的版本已存快照，可在「历史版本」里回滚' })
      onDone()
    } catch (e: any) {
      toast.error('采纳失败', { description: e?.message })
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-lg bg-subtle px-3.5 py-2.5 text-[13px] leading-relaxed">
        <span className="font-medium">{MODE_LABEL[proposal.mode]}</span>
        {proposal.change && <span className="text-muted-foreground"> · {proposal.change}</span>}
        <div className="mt-0.5 text-xs text-muted-foreground">新增 {clean.length} 张 · 需要你决定 {review.length} 条{proposal.removals.length ? ` · 旧卡里没对应的 ${proposal.removals.length} 张` : ''}。什么都不会自动写入，点下面的「采纳」才生效。</div>
      </div>

      {review.length > 0 && (
        <section>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-[14px] font-semibold"><AlertTriangle className="h-4 w-4 text-warning" />冲突审阅 <span className="text-xs font-normal text-muted-foreground">{sel.size ? `已选 ${sel.size} 条` : '批量操作作用于全部'}</span></h3>
            <div className="flex flex-wrap items-center gap-1">
              <Button size="xs" variant="ghost" onClick={() => setSel(sel.size === review.length ? new Set() : new Set(review.map((x) => x.key)))}>{sel.size === review.length ? '取消全选' : '全选'}</Button>
              {CHOICES.map((c) => <Button key={c.key} size="xs" variant="soft" title={c.tip} onClick={() => bulk(c.key)}>全部{c.label}</Button>)}
            </div>
          </div>
          <div className="space-y-2.5">
            {review.map((x) => {
              const pid = primaryId(x)
              const old = x.old ?? null
              const c = choice[x.key] ?? 'keep_old'
              return (
                <div key={x.key} className={cn('rounded-xl bg-surface p-3 shadow-card hairline', sel.has(x.key) && 'ring-2 ring-primary/30')}>
                  <div className="flex items-start gap-2.5">
                    <input type="checkbox" className="mt-1 h-4 w-4 accent-primary" checked={sel.has(x.key)} onChange={() => setSel((s) => { const n = new Set(s); n.has(x.key) ? n.delete(x.key) : n.add(x.key); return n })} aria-label="选中" />
                    <div className="min-w-0 flex-1 space-y-2">
                      <div className="flex flex-wrap gap-1.5">
                        {x.action === 'update' && !x.conflicts.length && <Badge tone="primary">改写已有卡</Badge>}
                        {x.conflicts.map((cf) => (
                          <span key={cf.card_id} className="inline-flex items-center gap-1 rounded-md bg-warning-soft px-2 py-0.5 text-[12px] text-warning">
                            {cf.reason}{cf.name && <b className="font-medium">「{cf.name}」</b>}<span className="opacity-60">{cf.source === 'ai' ? 'AI 判断' : '程序检测'}</span>
                          </span>
                        ))}
                      </div>
                      <div className="grid gap-2 md:grid-cols-[1fr_auto_1fr] md:items-stretch">
                        <CardMini label="旧卡" card={old ?? (x.conflicts[0] ? { type: x.conflicts[0].type, name: x.conflicts[0].name, summary: '', data: {}, known_by: [] } : null)} dim={c === 'replace' || c === 'delete_old'} />
                        <ArrowRight className="mx-auto hidden h-4 w-4 self-center text-muted-foreground md:block" />
                        <CardMini label="新内容" card={x.card} fresh dim={c === 'keep_old'} />
                      </div>
                      <TropeAlert hits={x.trope_hits} compact />
                      <div className="flex flex-wrap gap-1">
                        {CHOICES.map((o) => (
                          <button key={o.key} type="button" title={o.tip} disabled={pid == null && (o.key === 'replace' || o.key === 'delete_old')}
                            onClick={() => setChoice((m) => ({ ...m, [x.key]: o.key }))}
                            className={cn('h-7 rounded-md px-2.5 text-[12.5px] transition disabled:opacity-40', c === o.key ? 'bg-foreground text-background' : 'bg-subtle text-foreground/75 hover:text-foreground')}>
                            {o.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {clean.length > 0 && (
        <section>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="flex items-center gap-1.5 text-[14px] font-semibold"><Plus className="h-4 w-4 text-primary" />新增设定 <span className="text-xs font-normal text-muted-foreground">勾选要采纳的</span></h3>
            <Button size="xs" variant="ghost" onClick={() => setPicked(picked.size === clean.length ? new Set() : new Set(clean.map((x) => x.key)))}>{picked.size === clean.length ? '全不选' : '全选'}</Button>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {clean.map((x) => (
              <label key={x.key} className={cn('flex cursor-pointer gap-2.5 rounded-xl bg-surface p-3 shadow-card hairline transition', !picked.has(x.key) && 'opacity-55')}>
                <input type="checkbox" className="mt-1 h-4 w-4 accent-primary" checked={picked.has(x.key)} onChange={() => setPicked((s) => { const n = new Set(s); n.has(x.key) ? n.delete(x.key) : n.add(x.key); return n })} />
                <div className="min-w-0 flex-1">
                  <CardBody card={x.card} />
                  <TropeAlert hits={x.trope_hits} compact className="mt-2" />
                </div>
              </label>
            ))}
          </div>
        </section>
      )}

      {proposal.removals.length > 0 && (
        <section>
          <h3 className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold"><Trash2 className="h-4 w-4 text-danger" />重写后没有对应的旧卡 <span className="text-xs font-normal text-muted-foreground">勾选的会删除，取消勾选就保留</span></h3>
          <div className="grid gap-2 md:grid-cols-2">
            {proposal.removals.map((r) => (
              <label key={r.card_id} className="flex cursor-pointer gap-2.5 rounded-lg bg-surface p-2.5 hairline">
                <input type="checkbox" className="mt-1 h-4 w-4 accent-primary" checked={removeIds.has(r.card_id)} onChange={() => setRemoveIds((s) => { const n = new Set(s); n.has(r.card_id) ? n.delete(r.card_id) : n.add(r.card_id); return n })} />
                <div className="min-w-0 text-[13px]"><span className="font-medium">{r.name}</span> <span className="text-xs text-muted-foreground">{cardTypeLabel(r.type)}</span><p className="line-clamp-2 text-xs text-muted-foreground">{r.summary}</p></div>
              </label>
            ))}
          </div>
        </section>
      )}

      {!proposal.items.length && !proposal.removals.length && <p className="py-8 text-center text-sm text-muted-foreground">AI 这次没有给出需要改的设定。</p>}

      <div className="sticky bottom-0 -mx-6 flex items-center justify-end gap-2 border-t bg-popover px-6 py-3">
        <span className="mr-auto text-xs text-muted-foreground">将执行 {ops.length} 项操作</span>
        {onCancel && <Button variant="ghost" onClick={onCancel}>放弃</Button>}
        <Button variant="primary" icon={<Check className="h-4 w-4" />} loading={busy} disabled={!ops.length} onClick={apply}>采纳</Button>
      </div>
    </div>
  )
}

function CardBody({ card }: { card: CardDraft }) {
  const keys = Object.keys(card.data ?? {})
  return (
    <>
      <div className="flex items-center gap-1.5"><span className="truncate text-[13.5px] font-semibold">{card.name}</span><Badge tone="outline" className="h-5 text-[11px]">{cardTypeLabel(card.type)}</Badge></div>
      <p className="mt-1 line-clamp-3 text-[12.5px] leading-relaxed text-muted-foreground">{card.summary || '（无简介）'}</p>
      {keys.length > 0 && <p className="mt-1 truncate text-[11.5px] text-muted-foreground/80">{keys.length} 项属性</p>}
    </>
  )
}

function CardMini({ label, card, fresh, dim }: { label: string; card: CardDraft | null; fresh?: boolean; dim?: boolean }) {
  return (
    <div className={cn('rounded-lg px-3 py-2 transition', fresh ? 'bg-success-soft/50' : 'bg-subtle', dim && 'opacity-45')}>
      <div className="mb-0.5 text-[11px] text-muted-foreground">{label}</div>
      {card ? <CardBody card={card} /> : <span className="text-xs text-muted-foreground">（无）</span>}
    </div>
  )
}
