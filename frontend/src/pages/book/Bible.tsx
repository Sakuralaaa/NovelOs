import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { AlertTriangle, Archive, At, ChevronDown, Eye, Globe2, Gem, History, Lock, MapPin, MessageSquareQuote, Plus, RotateCcw, Shield, Sparkles, Trash2, Unlock, User, Wand2, X, Zap } from '@/components/icons'
import { Switch } from '@/components/ui/switch'
import { FieldAiButton } from '@/components/bible/FieldAi'
import { SoulCard, emptySoul, soulFilled } from '@/components/bible/SoulCard'
import { toast } from 'sonner'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/dialog'
import { Field, Input, Textarea } from '@/components/ui/input'
import { Select, type Opt } from '@/components/ui/select'
import { useChannels } from '@/hooks/queries'
import { TagInput } from '@/components/ui/tag-input'
import { EmptyState, ErrorState, PageHeader } from '@/components/common/States'
import { JobInline } from '@/components/common/JobInline'
import { AskBox, TropeAlert, useModelRoute } from '@/components/common/AiAsk'
import { ConflictReview } from '@/components/common/ConflictReview'
import { Segmented } from '@/components/ui/tabs'
import { GridSkeleton } from '../_skeleton'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'
import { api, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { BibleProposal, Card as CardT, CardType, CardVersion, Soul } from '@/lib/types'
import { CARD_TYPES, cn, fmtTime } from '@/lib/utils'

const TYPE_ICON: Record<CardType, typeof Globe2> = { world: Globe2, cheat: Sparkles, power: Zap, faction: Shield, character: User, item: Gem, location: MapPin }
const TYPE_COLOR: Record<CardType, string> = {
  world: 'from-sky-500/15 text-sky-600 dark:text-sky-400', cheat: 'from-primary/15 text-primary',
  power: 'from-amber-500/15 text-amber-600 dark:text-amber-400',
  faction: 'from-rose-500/15 text-rose-600 dark:text-rose-400', character: 'from-amber-500/15 text-amber-600 dark:text-amber-400',
  item: 'from-emerald-500/15 text-emerald-600 dark:text-emerald-400', location: 'from-teal-500/15 text-teal-600 dark:text-teal-400',
}
/** 人物卡约定键（合约 v0.1 增补），在专用表单中编辑 */
const CHAR_KEYS = ['voice', 'catchphrases', 'habits', 'demeanor'] as const

/** 设定库管理页带上已弃用条目（契约：默认列表不含 deprecated） */
const allKey = (id: number) => [...qk.cards(id), 'all'] as const

export default function Bible() {
  const id = useBookId()
  const [filter, setFilter] = useState<'all' | CardType>('all')
  const [editing, setEditing] = useState<Partial<CardT> | null>(null)
  const [autoSoul, setAutoSoul] = useState(false)
  const [showDep, setShowDep] = useState(false)
  const [sp, setSp] = useSearchParams()
  const { start } = useJobs()
  const qc = useQueryClient()
  const job = useActiveJob(`bible:${id}`)
  const cards = useQuery({ queryKey: allKey(id), queryFn: () => api.allCards(id) })
  const all = cards.data ?? []
  const list = all.filter((c) => c.status !== 'deprecated')
  const deprecated = all.filter((c) => c.status === 'deprecated')
  const groups = CARD_TYPES.map((t) => ({ ...t, items: list.filter((c) => c.type === t.key) })).filter((g) => (filter === 'all' ? g.items.length : g.key === filter))
  const charNames = list.filter((c) => c.type === 'character').map((c) => c.name)

  // 从完整度待办跳来：?entry=ID 打开条目，&soul=1 自动补全灵魂五维
  useEffect(() => {
    const e = Number(sp.get('entry'))
    if (!e || !cards.data) return
    const c = cards.data.find((x) => x.id === e)
    if (c) { setEditing(c); setAutoSoul(sp.get('soul') === '1') }
    sp.delete('entry'); sp.delete('soul'); setSp(sp, { replace: true })
  }, [cards.data, sp, setSp])

  const patchCard = useMutation({
    mutationFn: ({ c, b }: { c: CardT; b: Partial<CardT> }) => api.updateCard(c.id, b),
    meta: { errorTitle: '更新设定失败' },
    onMutate: ({ c, b }) => { qc.setQueryData<CardT[]>(allKey(id), (old) => old?.map((x) => (x.id === c.id ? { ...x, ...b } : x))) },
    onSuccess: (r, { b }) => {
      qc.invalidateQueries({ queryKey: qk.cards(id) }); qc.invalidateQueries({ queryKey: ['refs', id] }); qc.invalidateQueries({ queryKey: qk.completeness(id) })
      if (b.status === 'deprecated') toast.success(`已弃用「${r.name}」`, { description: '不再进入写作上下文，可在列表底部恢复', action: { label: '撤销', onClick: () => patchCard.mutate({ c: r, b: { status: 'active' } }) } })
      else if (b.status === 'active') toast.success(`已恢复「${r.name}」`)
      else if (b.locked !== undefined) toast.success(b.locked ? `已锁定「${r.name}」` : `已解锁「${r.name}」`)
    },
    onError: () => qc.invalidateQueries({ queryKey: allKey(id) }),
  })

  const gen = () => start(api.generateBible(id), { key: `bible:${id}`, label: '生成设定', successMsg: '设定库已生成，挑几张看看吧' })
  const [aiOpen, setAiOpen] = useState(false)
  const [histOpen, setHistOpen] = useState(false)
  const tropeCount = list.filter((c) => c.trope_hits?.length).length
  const openNew = (type: CardType) => { setAutoSoul(false); setEditing({ type, name: '', summary: '', data: {}, known_by: [], ref_enabled: true, status: 'active' }) }
  const open = (c: CardT) => { setAutoSoul(false); setEditing(c) }

  return (
    <div className="page">
      <BookCrumb bookId={id} page="设定库" />
      <PageHeader className="mt-3" title="设定库"
        actions={<>
          <Button icon={<Plus className="h-4 w-4" />} onClick={() => openNew(filter === 'all' ? 'character' : filter)}>新建设定</Button>
          <Button variant="ghost" icon={<RotateCcw className="h-4 w-4" />} onClick={() => setHistOpen(true)}>历史版本</Button>
          <Button variant="primary" loading={!!job} icon={<Wand2 className="h-4 w-4" />} onClick={() => (list.length ? setAiOpen(true) : gen())}>AI 生成设定</Button>
        </>} />
      {job && <JobInline job={job} className="mb-5" />}
      {tropeCount > 0 && (
        <div className="mb-5 flex items-center gap-2 rounded-lg bg-warning-soft px-3.5 py-2.5 text-[13px] text-warning">
          <AlertTriangle className="h-4 w-4 shrink-0" />有 {tropeCount} 张设定命中禁用套路（卡片上标黄），点开卡片可以一键让 AI 换掉。
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center gap-1.5">
        <TypeChip active={filter === 'all'} onClick={() => setFilter('all')}>全部 <span className="opacity-60">{list.length}</span></TypeChip>
        {CARD_TYPES.map((t) => {
          const Icon = TYPE_ICON[t.key]
          return <TypeChip key={t.key} active={filter === t.key} onClick={() => setFilter(t.key)}><Icon className="h-3.5 w-3.5" />{t.label} <span className="opacity-60">{list.filter((c) => c.type === t.key).length}</span></TypeChip>
        })}
        <span className="ml-auto hidden items-center gap-1 text-[12px] text-muted-foreground sm:flex"><At className="h-3.5 w-3.5" />在章节要求、章纲、Agent 里输入 @ 可引用开着「@引用」的条目</span>
      </div>

      {cards.isLoading ? <GridSkeleton n={6} h="h-44" /> : cards.error ? <ErrorState error={cards.error} onRetry={() => cards.refetch()} /> : !all.length ? (
        <EmptyState kind="cards" title="设定库还是空的"
          action={<><Button onClick={() => openNew('character')}>手动新建</Button><Button variant="primary" loading={!!job} icon={<Sparkles className="h-4 w-4" />} onClick={gen}>AI 生成设定</Button></>} />
      ) : !groups.length ? (
        <EmptyState compact kind="cards" title={`还没有「${CARD_TYPES.find((t) => t.key === filter)?.label ?? '设定'}」`} action={<Button size="sm" onClick={() => openNew(filter === 'all' ? 'character' : filter)}>新建一张</Button>} />
      ) : (
        <div className="space-y-8">
          {groups.map((g) => {
            const Icon = TYPE_ICON[g.key]
            return (
              <section key={g.key}>
                <div className="mb-3 flex items-baseline gap-2">
                  <h2 className="flex items-center gap-1.5 text-[15px] font-semibold"><Icon className="h-4 w-4 text-muted-foreground" />{g.label}</h2>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {g.items.map((c) => <BibleCard key={c.id} card={c} onClick={() => open(c)} onToggleRef={(v) => patchCard.mutate({ c, b: { ref_enabled: v } })} onToggleLock={() => patchCard.mutate({ c, b: { locked: !c.locked } })} />)}
                  <button onClick={() => openNew(g.key)} className="flex min-h-[120px] items-center justify-center gap-1.5 rounded-xl border border-dashed text-[13px] text-muted-foreground transition hover:border-primary/50 hover:bg-primary-soft/40 hover:text-primary">
                    <Plus className="h-4 w-4" />添加{g.label}
                  </button>
                </div>
              </section>
            )
          })}
        </div>
      )}

      {deprecated.length > 0 && (
        <section className="mt-10 rounded-xl border border-dashed bg-subtle/30">
          <button onClick={() => setShowDep((x) => !x)} aria-expanded={showDep} className="flex min-h-[48px] w-full items-center gap-2 px-4 text-left text-[13.5px] text-muted-foreground hover:text-foreground">
            <Archive className="h-4 w-4" />已弃用 <span className="num">{deprecated.length}</span>
            <span className="hidden text-[12px] sm:inline">· 不进入写作上下文、不能被 @ 引用，可随时恢复</span>
            <ChevronDown className={cn('ml-auto h-4 w-4 transition-transform', showDep && 'rotate-180')} />
          </button>
          {showDep && (
            <div className="grid gap-2 px-3 pb-3 md:grid-cols-2 xl:grid-cols-3">
              {deprecated.map((c) => {
                const Icon = TYPE_ICON[c.type]
                return (
                  <div key={c.id} className="flex min-h-[56px] items-center gap-3 rounded-lg bg-surface/60 px-3 py-2 opacity-70 grayscale transition hover:opacity-100 hairline">
                    <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <button className="min-w-0 flex-1 text-left" onClick={() => open(c)}>
                      <div className="truncate text-[13.5px] font-medium line-through decoration-foreground/30">{c.name}</div>
                      <div className="truncate text-[12px] text-muted-foreground">{c.summary || '暂无简介'}</div>
                    </button>
                    <Button size="sm" variant="ghost" className="h-10 shrink-0" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={patchCard.isPending && patchCard.variables?.c.id === c.id} onClick={() => patchCard.mutate({ c, b: { status: 'active' } })}>恢复</Button>
                  </div>
                )
              })}
            </div>
          )}
        </section>
      )}

      <CardEditor bookId={id} card={editing} onClose={() => { setEditing(null); setAutoSoul(false) }} charNames={charNames} autoSoul={autoSoul}
        onStatus={(c, status) => patchCard.mutateAsync({ c, b: { status } }).then(() => setEditing(null))}
        onLock={(c, locked) => patchCard.mutateAsync({ c, b: { locked } })} />
      <BibleAiSheet bookId={id} open={aiOpen} onOpenChange={setAiOpen} />
      <SnapshotSheet bookId={id} open={histOpen} onOpenChange={setHistOpen} />
    </div>
  )
}

const MODES: { value: 'rewrite' | 'add' | 'optimize'; label: string; desc: string; ph: string }[] = [
  { value: 'optimize', label: '优化', desc: '在现有设定上改进，可以改写已有的卡，也会补新卡。', ph: '例如：反派动机写得更具体；金手指的边界改成每天三次' },
  { value: 'add', label: '纯增加', desc: '只新增，不动旧卡。', ph: '例如：补两个第二卷会出场的对手势力和一个中立情报贩子' },
  { value: 'rewrite', label: '完全重写', desc: '基于书的信息和你的要求重新生成整套设定，替换前先预览，旧版本可回滚。', ph: '例如：世界观换成近未来都市，主角不要是世家子弟' },
]

/** AI 生成设定：三种模式 → 预览 → 冲突审阅 → 采纳（自动快照，可回滚） */
function BibleAiSheet({ bookId, open, onOpenChange }: { bookId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [mode, setMode] = useState<'rewrite' | 'add' | 'optimize'>('optimize')
  const [ask, setAsk] = useState('')
  const [proposal, setProposal] = useState<BibleProposal | null>(null)
  const storage = useModelRoute('novelos.bible-route')
  const { start } = useJobs()
  const job = useActiveJob(`bible-propose:${bookId}`)
  const m = MODES.find((x) => x.value === mode)!
  const go = () => start(api.proposeBible(bookId, { mode, instruction: ask.trim(), route: storage.model }), {
    key: `bible-propose:${bookId}`, label: `AI ${m.label}设定`, silent: true,
    onSuccess: (j) => { setProposal(j.result as BibleProposal); toast.success('生成好了，看看再决定采纳哪些') },
  })
  return (
    <Sheet open={open} onOpenChange={onOpenChange} width={780} title="AI 生成设定" desc="什么都不会直接写入设定库：先预览，有冲突的逐条决定，采纳前自动存快照。">
      {proposal ? (
        <ConflictReview bookId={bookId} proposal={proposal} onCancel={() => setProposal(null)} onDone={() => { setProposal(null); setAsk(''); onOpenChange(false) }} />
      ) : (
        <div className="space-y-4">
          <Segmented block value={mode} onChange={setMode} options={MODES.map((x) => ({ value: x.value, label: x.label }))} />
          <p className="text-[13px] text-muted-foreground">{m.desc}</p>
          <AskBox title="写要求（可留空）" placeholder={m.ph} value={ask} onChange={setAsk} onSubmit={go} job={job} storage={storage} allowEmpty submitLabel={`AI ${m.label}`} />
        </div>
      )}
    </Sheet>
  )
}

function SnapshotSheet({ bookId, open, onOpenChange }: { bookId: number; open: boolean; onOpenChange: (o: boolean) => void }) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: qk.bibleSnapshots(bookId), queryFn: () => api.bibleSnapshots(bookId), enabled: open })
  const [confirm, setConfirm] = useState<number | null>(null)
  const m = useMutation({
    mutationFn: (sid: number) => api.restoreBible(bookId, sid),
    meta: { errorTitle: '回滚失败' },
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: qk.cards(bookId) }); setConfirm(null); toast.success(`已回滚，恢复 ${r.restored} 张设定`, { description: '回滚前的样子也存了一份快照' }) },
  })
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title="设定库历史版本" desc="每次 AI 批量改设定、重新生成、回滚之前都会自动存一份快照。">
      {!q.data?.length ? <p className="py-10 text-center text-sm text-muted-foreground">{q.isLoading ? '加载中…' : '还没有快照。AI 批量改设定后这里会出现可回滚的旧版本。'}</p> : (
        <div className="space-y-2">
          {q.data.map((s) => (
            <div key={s.id} className="rounded-lg bg-surface p-3 hairline">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0"><div className="truncate text-[13.5px] font-medium">{s.note || '快照'}</div><div className="text-xs text-muted-foreground">{fmtTime(s.created_at)} · {s.count} 张卡</div></div>
                {confirm === s.id
                  ? <Button size="sm" variant="danger" loading={m.isPending} onClick={() => m.mutate(s.id)}>确认回滚</Button>
                  : <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => setConfirm(s.id)}>回滚到这里</Button>}
              </div>
              {s.names.length > 0 && <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">{s.names.join('、')}</p>}
            </div>
          ))}
        </div>
      )}
    </Sheet>
  )
}

function TypeChip({ active, children, onClick }: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return <button onClick={onClick} className={cn('flex h-8 items-center gap-1.5 rounded-full px-3 text-[13px] transition', active ? 'bg-foreground text-background' : 'bg-surface text-foreground/75 hairline hover:text-foreground')}>{children}</button>
}

function BibleCard({ card: c, onClick, onToggleRef, onToggleLock }: { card: CardT; onClick: () => void; onToggleRef: (v: boolean) => void; onToggleLock: () => void }) {
  const Icon = TYPE_ICON[c.type]
  const entries = Object.entries(c.data ?? {}).filter(([k]) => !(c.type === 'character' && (CHAR_KEYS as readonly string[]).includes(k))).slice(0, 3)
  const cp: string[] = Array.isArray(c.data?.catchphrases) ? c.data.catchphrases : []
  const refOn = c.ref_enabled !== false
  const soulN = c.type === 'character' ? soulFilled(c.soul) : -1
  return (
    <motion.div layout role="button" tabIndex={0} onClick={onClick} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } }}
      className="focus-ring group flex cursor-pointer flex-col rounded-xl bg-surface p-4 text-left hairline shadow-card transition hover:-translate-y-0.5 hover:shadow-lift">
      <div className="flex items-center gap-2.5">
        <div className={cn('flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br to-transparent', TYPE_COLOR[c.type])}><Icon className="h-4 w-4" /></div>
        <div className="min-w-0 flex-1 truncate font-semibold group-hover:text-primary">{c.name}</div>
        {soulN >= 0 && <span title="灵魂五维已填项数" className={cn('num shrink-0 rounded px-1.5 py-0.5 text-[11px]', soulN === 5 ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground')}>魂 {soulN}/5</span>}
        {!!c.trope_hits?.length && <span title={`命中禁用套路：${c.trope_hits.map((h) => h.name).join('、')}`} className="shrink-0 rounded bg-warning-soft px-1.5 py-0.5 text-[11px] text-warning">套路</span>}
        <button type="button" onClick={(e) => { e.stopPropagation(); onToggleLock() }} onKeyDown={(e) => e.stopPropagation()}
          aria-label={c.locked ? '解锁' : '锁定'} title={c.locked ? '已锁定，点击解锁' : '锁定'}
          className={cn('-my-1 -mr-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition hover:bg-subtle', c.locked ? 'text-primary' : 'text-muted-foreground/50 opacity-0 group-hover:opacity-100 focus:opacity-100')}>
          {c.locked ? <Lock className="h-4 w-4" /> : <Unlock className="h-4 w-4" />}
        </button>
      </div>
      <p className="mt-2.5 line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">{c.summary || '暂无简介'}</p>
      {c.type === 'character' && (c.data?.voice || cp.length > 0) && (
        <div className="mt-2.5 flex items-start gap-1.5 rounded-md bg-subtle px-2.5 py-1.5 text-[12px] leading-relaxed text-foreground/75">
          <MessageSquareQuote className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
          <span className="line-clamp-2">{cp.length ? cp.map((x) => `“${x}”`).join(' ') : c.data.voice}</span>
        </div>
      )}
      {entries.length > 0 && (
        <dl className="mt-2.5 space-y-1 text-[12px]">
          {entries.map(([k, v]) => (
            <div key={k} className="flex gap-2"><dt className="shrink-0 text-muted-foreground">{keyLabel(k)}</dt><dd className="truncate">{k === 'role' && typeof v === 'string' ? (ROLE_LABEL[v] ?? v) : typeof v === 'string' ? v : Array.isArray(v) ? v.join('；') : JSON.stringify(v)}</dd></div>
          ))}
        </dl>
      )}
      <div className="mt-auto flex items-center justify-between gap-2 pt-3">
        <div className="flex min-w-0 flex-wrap items-center gap-1">
          {c.known_by?.length ? <><Eye className="h-3 w-3 text-muted-foreground" />{c.known_by.slice(0, 2).map((k) => <Badge key={k} tone="outline" className="h-5 text-[11px]">{k}</Badge>)}{c.known_by.length > 2 && <span className="text-[11px] text-muted-foreground">+{c.known_by.length - 2}</span>}</> : <span className="text-[11.5px] text-muted-foreground/70">仅作者可见</span>}
        </div>
        <label onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()} title={refOn ? '可以在章节要求、章纲、Agent 里 @ 引用' : '不会出现在 @ 补全里'}
          className={cn('-my-1.5 -mr-1.5 flex h-10 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg px-1.5 text-[11.5px] transition hover:bg-subtle', refOn ? 'text-primary' : 'text-muted-foreground')}>
          <At className="h-3.5 w-3.5" />用于 @引用
          <Switch checked={refOn} onCheckedChange={onToggleRef} />
        </label>
      </div>
    </motion.div>
  )
}

const tropeReplaceInstruction = (hits: { name: string; hits: string[] }[]) =>
  `去掉这些俗套：${hits.map((h) => h.name).join('、')}（命中：${hits.flatMap((h) => h.hits).join('、')}）。换成更新鲜的来历、动机或金手指来源，其余没提到的内容尽量保留，不要再出现上面这些词。`

/** data 约定键用英文存（写作上下文按键取值），界面上一律显示中文 */
const KEY_LABEL: Record<string, string> = {
  input: '用法', trigger: '触发方式', cost: '代价', limit: '边界', growth: '成长线', levels: '境界划分',
  role: '定位', knows: '已知', unknown: '未知', misbelief: '误解', sensory: '感官', era: '时代', rules: '规则',
  leader: '首领', stance: '立场', voice: '说话方式', catchphrases: '口头禅', habits: '小动作', demeanor: '神态习惯',
}
const LABEL_KEY = Object.fromEntries(Object.entries(KEY_LABEL).map(([k, v]) => [v, k]))
const keyLabel = (k: string) => KEY_LABEL[k] ?? k
const ROLE_LABEL: Record<string, string> = { protagonist: '主角', antagonist: '反派', ally: '盟友', supporting: '配角', mentor: '师父', rival: '对手', love: '感情线' }
const ROLE_KEY = Object.fromEntries(Object.entries(ROLE_LABEL).map(([k, v]) => [v, k]))

type Row = { k: string; v: string; json?: boolean }
const toRows = (d: Record<string, any>, skip: readonly string[]): Row[] =>
  Object.entries(d ?? {}).filter(([k]) => !skip.includes(k)).map(([k, v]) => (k === 'role' && typeof v === 'string' ? { k: keyLabel(k), v: ROLE_LABEL[v] ?? v } : Array.isArray(v) && v.every((x) => typeof x === 'string') ? { k: keyLabel(k), v: v.join('；') } : typeof v === 'string' || typeof v === 'number' ? { k: keyLabel(k), v: String(v) } : { k: keyLabel(k), v: JSON.stringify(v), json: true }))

type Form = { type: CardType; name: string; summary: string; known_by: string[]; rows: Row[]; voice: string; catchphrases: string[]; habits: string[]; demeanor: string; soul: Soul; ref_enabled: boolean }

function CardEditor({ bookId, card, onClose, charNames, autoSoul, onStatus, onLock }: {
  bookId: number; card: Partial<CardT> | null; onClose: () => void; charNames: string[]; autoSoul?: boolean
  onStatus: (c: CardT, status: 'active' | 'deprecated') => Promise<unknown>
  onLock: (c: CardT, locked: boolean) => Promise<unknown>
}) {
  const open = !!card
  const isNew = !card?.id
  const [lockOv, setLockOv] = useState<boolean | null>(null)
  const locked = lockOv ?? !!card?.locked
  const [verOpen, setVerOpen] = useState(false)
  const [lockBusy, setLockBusy] = useState(false)
  const entryId = card?.id
  const deprecatedCard = card?.status === 'deprecated'
  const [form, setForm] = useState<Form>()
  const [lastId, setLastId] = useState<unknown>(undefined)
  const toForm = (c: Partial<CardT>) => {
    const d = c.data ?? {}
    return {
      type: c.type ?? 'character', name: c.name ?? '', summary: c.summary ?? '', known_by: c.known_by ?? [],
      rows: toRows(d, c.type === 'character' ? CHAR_KEYS : []),
      voice: typeof d.voice === 'string' ? d.voice : '', catchphrases: Array.isArray(d.catchphrases) ? d.catchphrases : [],
      habits: Array.isArray(d.habits) ? d.habits : [], demeanor: typeof d.demeanor === 'string' ? d.demeanor : '',
      soul: { ...emptySoul(), ...(c.soul ?? {}) }, ref_enabled: c.ref_enabled !== false,
    }
  }
  if (card && lastId !== card) {
    setLastId(card)
    setForm(toForm(card))
    setLockOv(null)
  }
  const { start } = useJobs()
  const [ask, setAsk] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const channels = useChannels()
  const opts: Opt[] = (channels.data ?? []).filter((c) => c.enabled).flatMap((c) => c.models.map((m) => ({ value: `${c.id}:${m}`, label: <span className="font-mono text-[12.5px]">{m}</span>, group: c.name })))
  const [route, setRouteState] = useState<string | null>(() => localStorage.getItem('novelos.card-route') || null)
  const model = route && opts.some((o) => o.value === route) ? route : null
  const setRoute = (v: string | null) => { setRouteState(v); if (v) localStorage.setItem('novelos.card-route', v); else localStorage.removeItem('novelos.card-route') }
  const qc = useQueryClient()
  const build = () => {
    const f = form!
    const data: Record<string, any> = {}
    f.rows.filter((r) => r.k.trim()).forEach((r) => {
      let v: any = r.v
      if (r.json) { try { v = JSON.parse(r.v) } catch { /* 保留字符串 */ } }
      const key = LABEL_KEY[r.k.trim()] ?? r.k.trim()
      if (key === 'role' && typeof v === 'string') v = ROLE_KEY[v] ?? v
      if (Array.isArray(card?.data?.[key]) && typeof v === 'string') v = v.split(/[；;]/).map((x: string) => x.trim()).filter(Boolean)
      data[key] = v
    })
    if (f.type === 'character') {
      if (f.voice.trim()) data.voice = f.voice.trim()
      if (f.catchphrases.length) data.catchphrases = f.catchphrases
      if (f.habits.length) data.habits = f.habits
      if (f.demeanor.trim()) data.demeanor = f.demeanor.trim()
    }
    const out: Partial<CardT> = { type: f.type, name: f.name.trim(), summary: f.summary, data, known_by: f.known_by, ref_enabled: f.ref_enabled }
    // 灵魂五维按键合并：只传人物的；空串表示清空该项
    if (f.type === 'character') out.soul = f.soul
    return out
  }
  const save = useMutation({
    mutationFn: () => (isNew ? api.createCard(bookId, build()) : api.updateCard(card!.id!, build())),
    meta: { errorTitle: '保存失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.cards(bookId) }); qc.invalidateQueries({ queryKey: qk.completeness(bookId) }); qc.invalidateQueries({ queryKey: ['refs', bookId] }); toast.success(isNew ? '已新建设定' : '已保存'); onClose() },
  })
  /** 字段级 AI 采纳：同步写库（写前自动存快照），同时更新表单里的这一项，其它没保存的修改保留 */
  const adoptField = async (field: string, value: unknown) => {
    if (!entryId) return
    try {
      await api.applyFieldAi(bookId, entryId, { field, value })
    } catch (e: any) { toast.error('采纳失败', { description: e?.message }); throw e }
    qc.invalidateQueries({ queryKey: qk.cards(bookId) }); qc.invalidateQueries({ queryKey: qk.completeness(bookId) })
    setForm((f) => {
      if (!f) return f
      if (field === 'name' || field === 'summary') return { ...f, [field]: String(value ?? '') }
      if (field.startsWith('soul.')) return { ...f, soul: { ...f.soul, [field.slice(5)]: String(value ?? '') } }
      const k = field.slice(5)
      if (k === 'voice' || k === 'demeanor') return { ...f, [k]: String(value ?? '') }
      if (k === 'catchphrases' || k === 'habits') return { ...f, [k]: Array.isArray(value) ? value.map(String) : String(value ?? '').split(/[；;]/).map((x) => x.trim()).filter(Boolean) }
      return { ...f, rows: f.rows.map((x) => ((LABEL_KEY[x.k.trim()] ?? x.k.trim()) === k ? (typeof value === 'string' ? { k: x.k, v: value } : Array.isArray(value) && value.every((y) => typeof y === 'string') ? { k: x.k, v: value.join('；') } : { k: x.k, v: JSON.stringify(value), json: true }) : x)) }
    })
    toast.success('已采纳并保存', { description: '写入前存了设定快照，可在「历史版本」回滚' })
  }
  const adoptSoul = async (soul: Soul) => {
    if (!entryId) return
    try { await api.updateCard(entryId, { soul }) } catch (e: any) { toast.error('采纳失败', { description: e?.message }); throw e }
    qc.invalidateQueries({ queryKey: qk.cards(bookId) }); qc.invalidateQueries({ queryKey: qk.completeness(bookId) })
    setForm((f) => (f ? { ...f, soul: { ...f.soul, ...soul } } : f))
    toast.success('灵魂五维已保存')
  }
  const [statusBusy, setStatusBusy] = useState(false)
  const del = useMutation({
    mutationFn: () => api.deleteCard(card!.id!),
    meta: { errorTitle: '删除失败' },
    onSuccess: () => { qc.invalidateQueries({ queryKey: qk.cards(bookId) }); toast.success('已删除'); onClose() },
  })
  const [confirmDel, setConfirmDel] = useState(false)
  if (!form) return null
  const set = (p: Partial<typeof form>) => setForm({ ...form, ...p })
  const suggest = (field: string | null, instruction: string) => {
    const tag = field ?? '__card'
    setBusy(tag)
    start(api.suggestCard(bookId, { card_id: card?.id ?? null, field, instruction, route: model, draft: build() }), {
      key: `card-ai:${bookId}:${card?.id ?? 'new'}:${tag}`, label: 'AI 改设定', silent: true,
      onSuccess: (j) => {
        setBusy(null)
        const r = j.result as any
        if (!r) return
        if (r.card) { setForm(toForm(r.card)); setAsk(''); toast.success('改好了，确认后保存'); return }
        const v = r.value
        setForm((f) => {
          if (!f) return f
          if (field === 'name' || field === 'summary' || field === 'voice' || field === 'demeanor') return { ...f, [field]: String(v) }
          if (field === 'catchphrases' || field === 'habits') return { ...f, [field]: Array.isArray(v) ? v.map(String) : [String(v)] }
          if (field?.startsWith('data.')) {
            const k = field.slice(5)
            return { ...f, rows: f.rows.map((x) => ((LABEL_KEY[x.k.trim()] ?? x.k.trim()) === k ? (typeof v === 'string' ? { k: x.k, v } : Array.isArray(v) && v.every((y: unknown) => typeof y === 'string') ? { k: x.k, v: v.join('；') } : { k: x.k, v: JSON.stringify(v), json: true }) : x)) }
          }
          return f
        })
      },
      onError: (j) => { setBusy(null); toast.error('AI 改写失败', { description: j.error ?? undefined }) },
    })
  }
  const ai = (field: string, label: string) => locked ? undefined : entryId ? (
    <FieldAiButton bookId={bookId} entryId={entryId} field={field.includes('.') || field === 'name' || field === 'summary' ? field : `data.${field}`} label={label}
      onAdopt={(v) => adoptField(field.includes('.') || field === 'name' || field === 'summary' ? field : `data.${field}`, v)} className="-my-1.5" />
  ) : (
    <button type="button" disabled={!!busy} onClick={() => suggest(field, ask.trim())} title={ask.trim() ? `按上面的要求改${label}` : `AI 改${label}`}
        className="focus-ring inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11.5px] font-normal text-muted-foreground transition hover:bg-primary-soft hover:text-primary disabled:opacity-50">
        <Wand2 className={cn('h-3 w-3', busy === field && 'animate-pulse')} />{busy === field ? '改写中' : 'AI 改'}
    </button>
  )
  const isChar = form.type === 'character'

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) { onClose(); setConfirmDel(false) } }} title={isNew ? '新建设定' : `编辑：${card?.name}`}
      footer={<div className="flex w-full flex-wrap items-center gap-2">
        {!isNew && (confirmDel
          ? <Button variant="danger" className="h-10" loading={del.isPending} onClick={() => del.mutate()}>确认删除</Button>
          : <Button variant="ghost" className="h-10 text-danger hover:bg-danger-soft hover:text-danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDel(true)}>删除</Button>)}
        {!isNew && <Button variant="ghost" className="h-10" loading={lockBusy} icon={locked ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}
          onClick={async () => { setLockBusy(true); try { await onLock(card as CardT, !locked); setLockOv(!locked) } finally { setLockBusy(false) } }}>{locked ? '解锁' : '锁定'}</Button>}
        {!isNew && <Button variant="ghost" className="h-10" icon={<History className="h-4 w-4" />} onClick={() => setVerOpen(true)}>版本{card?.versions ? <span className="num ml-1 opacity-60">{card.versions}</span> : null}</Button>}
        {!isNew && <Button variant="ghost" className="h-10" loading={statusBusy} icon={deprecatedCard ? <RotateCcw className="h-4 w-4" /> : <Archive className="h-4 w-4" />}
          onClick={async () => { setStatusBusy(true); try { await onStatus(card as CardT, deprecatedCard ? 'active' : 'deprecated') } finally { setStatusBusy(false) } }}>{deprecatedCard ? '恢复' : '弃用'}</Button>}
        <div className="ml-auto flex gap-2">
          <Button variant="ghost" className="h-10" onClick={onClose}>取消</Button>
          <Button variant="primary" className="h-10" disabled={!form.name.trim()} loading={save.isPending} onClick={() => save.mutate()}>保存</Button>
        </div>
      </div>}>
      <div className="space-y-5">
        {deprecatedCard && <div className="flex items-center gap-2 rounded-lg bg-muted px-3.5 py-2.5 text-[13px] text-muted-foreground"><Archive className="h-4 w-4 shrink-0" />这条设定已弃用：不进入写作上下文、不能被 @ 引用。点底部「恢复」重新启用。</div>}
        {locked && <div className="flex items-center gap-2 rounded-lg bg-primary-soft/50 px-3.5 py-2.5 text-[13px] text-primary"><Lock className="h-4 w-4 shrink-0" />已锁定，AI 不会改动这张设定</div>}
        {!isNew && !locked && <TropeAlert hits={(card as CardT | null)?.trope_hits} busy={busy === '__card'} onReplace={() => suggest(null, tropeReplaceInstruction((card as CardT).trope_hits ?? []))} />}
        {!locked && <div className="space-y-2 rounded-xl bg-primary-soft/40 p-3 hairline">
          <div className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-[13px] font-semibold"><Wand2 className="h-4 w-4 text-primary" />{isNew ? '让 AI 写这张' : '让 AI 改这张'}</span>
            <div className="w-[200px]"><Select value={model} onChange={setRoute} options={opts} allowEmpty emptyLabel="默认（策划模型）" placeholder="默认（策划模型）" /></div>
          </div>
          <div className="flex gap-2">
            <Input value={ask} onChange={(e) => setAsk(e.target.value)} className="bg-surface text-[13px]"
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && ask.trim()) suggest(null, ask.trim()) }}
              placeholder={isNew ? '例如：反派宗门的大长老，笑面虎' : '例如：口头禅换一句更狠的，境界压到炼气三层'} />
            <Button size="sm" className="h-9 shrink-0" loading={busy === '__card'} disabled={!!busy || (!ask.trim() && isNew && !form.name.trim())} onClick={() => suggest(null, ask.trim())}>{isNew ? 'AI 写' : '整张改'}</Button>
          </div>
        </div>}
        <div className="grid grid-cols-[140px_1fr] gap-3">
          <Field label="类型"><Select value={form.type} onChange={(v) => v && set({ type: v as CardType })} options={CARD_TYPES.map((t) => ({ value: t.key, label: t.label }))} /></Field>
          <Field label="名称" hint={entryId ? ai('name', '名称') : undefined}><Input autoFocus value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder={isChar ? '人物名' : '设定名称'} /></Field>
        </div>
        <label className="flex min-h-[48px] cursor-pointer items-center justify-between gap-3 rounded-xl bg-subtle/60 px-3.5 py-2 hairline">
          <span className="min-w-0"><span className="flex items-center gap-1.5 text-[13px] font-medium"><At className="h-4 w-4 text-primary" />用于 @引用</span>
            <span className="block text-[12px] text-muted-foreground">在章节要求、章纲、Agent 里输入 @{form.name || '名称'}，生成时会带上这条设定的完整内容</span></span>
          <Switch checked={form.ref_enabled} onCheckedChange={(v) => set({ ref_enabled: v })} />
        </label>
        <Field label="简介" hint={ai('summary', '简介')}><Textarea value={form.summary} onChange={(e) => set({ summary: e.target.value })} placeholder="一两句话说清楚它是什么" /></Field>

        {isChar && (
          <SoulCard bookId={bookId} entryId={entryId} value={form.soul} onChange={(soul) => set({ soul })} autoFill={autoSoul}
            onAdoptField={(k, v) => adoptField(`soul.${k}`, v)} onAdoptAll={adoptSoul} aiOff={locked} />
        )}
        {isChar && (
          <div className="space-y-4 rounded-xl bg-amber-500/[0.06] p-4 hairline">
            <div>
              <div className="flex items-center gap-1.5 text-[13px] font-semibold"><MessageSquareQuote className="h-4 w-4 text-amber-500" />人物声音</div>
            </div>
            <Field label="说话方式" hint={ai('voice', '说话方式')}><Textarea value={form.voice} onChange={(e) => set({ voice: e.target.value })} className="min-h-[64px] bg-surface" placeholder="例如：话少，短句，爱用反问；生气时反而更客气" /></Field>
            <Field label="口头禅" hint={ai('catchphrases', '口头禅')}><TagInput value={form.catchphrases} onChange={(v) => set({ catchphrases: v })} placeholder="例如：行。（回车添加）" /></Field>
            <Field label="小动作" hint={ai('habits', '小动作')}><TagInput value={form.habits} onChange={(v) => set({ habits: v })} placeholder="例如：想事情时摩挲袖口" /></Field>
            <Field label="神态习惯" hint={ai('demeanor', '神态习惯')}><Input value={form.demeanor} onChange={(e) => set({ demeanor: e.target.value })} className="bg-surface" placeholder="例如：眼皮半耷拉着，看人先看手" /></Field>
          </div>
        )}

        <div>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-[13px] font-medium">详细属性</span>
            <Button size="xs" variant="ghost" icon={<Plus className="h-3 w-3" />} onClick={() => set({ rows: [...form.rows, { k: '', v: '' }] })}>添加一项</Button>
          </div>
          <div className="space-y-1.5">
            {form.rows.length === 0 && <p className="rounded-md border border-dashed px-3 py-3 text-center text-xs text-muted-foreground">例如：年龄 / 身份 / 境界 / 弱点，点“添加一项”</p>}
            {form.rows.map((r, i) => (
              <div key={i} className="flex gap-1.5">
                <Input value={r.k} onChange={(e) => set({ rows: form.rows.map((x, j) => (j === i ? { ...x, k: e.target.value } : x)) })} placeholder="属性" className="w-[120px] shrink-0" />
                <Input value={r.v} onChange={(e) => set({ rows: form.rows.map((x, j) => (j === i ? { ...x, v: e.target.value } : x)) })} placeholder="内容" className={cn(r.json && 'font-mono text-xs')} />
                {locked ? null : entryId && r.k.trim() && (card?.data ?? {})[LABEL_KEY[r.k.trim()] ?? r.k.trim()] !== undefined
                  ? <FieldAiButton bookId={bookId} entryId={entryId} field={`data.${LABEL_KEY[r.k.trim()] ?? r.k.trim()}`} label={r.k.trim()} onAdopt={(v) => adoptField(`data.${LABEL_KEY[r.k.trim()] ?? r.k.trim()}`, v)} className="h-9 shrink-0" />
                  : <Button size="icon" variant="ghost" disabled={!!busy || !r.k.trim()} onClick={() => suggest(`data.${LABEL_KEY[r.k.trim()] ?? r.k.trim()}`, ask.trim())} aria-label="AI 改这一项" title="AI 改这一项"><Wand2 className={cn('h-4 w-4', busy === `data.${LABEL_KEY[r.k.trim()] ?? r.k.trim()}` && 'animate-pulse text-primary')} /></Button>}
                <Button size="icon" variant="ghost" onClick={() => set({ rows: form.rows.filter((_, j) => j !== i) })} aria-label="删除"><X className="h-4 w-4" /></Button>
              </div>
            ))}
          </div>
        </div>

        <Field label="知情者">
          <TagInput value={form.known_by} onChange={(v) => set({ known_by: v })} placeholder="输入人物名，回车添加" suggestions={charNames.filter((n) => n !== form.name)} />
        </Field>
      </div>
      {entryId && <CardVersionSheet bookId={bookId} cardId={entryId} name={card?.name ?? ''} open={verOpen} onOpenChange={setVerOpen}
        onRestored={(c) => { setForm(toForm(c)); setLastId(card) }} />}
    </Sheet>
  )
}

/** v0.12 单卡版本：每次手动保存、采纳 AI、批量改之前的样子，可逐条回滚（回滚前也会存一版） */
function CardVersionSheet({ bookId, cardId, name, open, onOpenChange, onRestored }: {
  bookId: number; cardId: number; name: string; open: boolean; onOpenChange: (o: boolean) => void; onRestored: (c: CardT) => void
}) {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: [...qk.cards(bookId), 'versions', cardId], queryFn: () => api.cardVersions(cardId), enabled: open })
  const [sel, setSel] = useState<number | null>(null)
  const m = useMutation({
    mutationFn: (n: number) => api.restoreCardVersion(cardId, n),
    meta: { errorTitle: '回滚失败' },
    onSuccess: (c) => { qc.invalidateQueries({ queryKey: qk.cards(bookId) }); setSel(null); onRestored(c); onOpenChange(false); toast.success(`「${c.name}」已回滚`) },
  })
  return (
    <Sheet open={open} onOpenChange={onOpenChange} title={`「${name}」的版本`}>
      {!q.data?.length ? <p className="py-10 text-center text-sm text-muted-foreground">{q.isLoading ? '加载中…' : '还没有旧版本'}</p> : (
        <div className="space-y-2">
          {q.data.map((v) => <VersionRow key={v.n} v={v} open={sel === v.n} onToggle={() => setSel(sel === v.n ? null : v.n)} busy={m.isPending && m.variables === v.n} onRestore={() => m.mutate(v.n)} />)}
        </div>
      )}
    </Sheet>
  )
}

function VersionRow({ v, open, onToggle, busy, onRestore }: { v: CardVersion; open: boolean; onToggle: () => void; busy: boolean; onRestore: () => void }) {
  const rows = Object.entries(v.data ?? {})
  return (
    <div className="rounded-lg bg-surface p-3 hairline">
      <div className="flex items-center justify-between gap-2">
        <button className="min-w-0 flex-1 text-left" onClick={onToggle} aria-expanded={open}>
          <div className="truncate text-[13.5px] font-medium">{v.label || '旧版本'}</div>
          <div className="text-xs text-muted-foreground">{fmtTime(v.at)} · {v.name}</div>
        </button>
        <Button size="sm" variant="ghost" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={busy} onClick={onRestore}>回滚到这版</Button>
      </div>
      {open && (
        <div className="mt-2 space-y-1.5 border-t pt-2 text-[12.5px]">
          <p className="leading-relaxed text-foreground/80">{v.summary || '暂无简介'}</p>
          {rows.length > 0 && <dl className="space-y-1">{rows.map(([k, x]) => (
            <div key={k} className="flex gap-2"><dt className="shrink-0 text-muted-foreground">{keyLabel(k)}</dt><dd className="min-w-0 break-words">{typeof x === 'string' ? (k === 'role' ? (ROLE_LABEL[x] ?? x) : x) : Array.isArray(x) ? x.join('；') : JSON.stringify(x)}</dd></div>
          ))}</dl>}
        </div>
      )}
    </div>
  )
}

