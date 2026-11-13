import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import * as D from '@radix-ui/react-dialog'
import {
  AlertTriangle, ArrowRight, Check, ChevronDown, Feather, Info, Lightbulb, Loader2, RefreshCw, ShieldCheck, Sparkles, X, XCircle,
} from '@/components/icons'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/misc'
import { ErrorState } from '@/components/common/States'
import { useDeepTeardown, useLastReskin, useReskin, useRunTeardown, useTeardown } from '@/hooks/queries'
import type { DeepTeardown, Idea, KeywordHit, RankItem, ReskinResult, TeardownCore } from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

export const DEEP_LIMIT = 20000
const pct = (v: number) => `${Math.round((v ?? 0) * 100)}%`
const bare = (s: string) => s.replace(/\s/g, '').length

/** 榜单仿写面板：平板/桌面是右侧抽屉，手机是底部抽屉 */
export function ImitatePanel({ item, onClose }: { item: RankItem | null; onClose: () => void }) {
  // 关闭动画期间保留上一本书，避免内容闪空
  const [shown, setShown] = useState<RankItem | null>(item)
  useEffect(() => { if (item) setShown(item) }, [item])
  return (
    <D.Root open={!!item} onOpenChange={(o) => { if (!o) onClose() }}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[1px] data-[state=open]:animate-fade-in" />
        <D.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          className={cn(
            'fixed z-50 flex flex-col bg-background shadow-pop hairline focus:outline-none',
            'inset-x-0 bottom-0 max-h-[92dvh] rounded-t-2xl data-[state=open]:animate-slide-in-up',
            'md:inset-y-0 md:left-auto md:right-0 md:h-full md:max-h-none md:w-[min(640px,100vw)] md:rounded-none md:data-[state=open]:animate-slide-in-right',
          )}
        >
          <div className="mx-auto mt-2 h-1.5 w-10 shrink-0 rounded-full bg-muted md:hidden" aria-hidden />
          {shown && <PanelBody key={shown.id ?? shown.book_id_ext} item={shown} onClose={onClose} />}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}

function PanelBody({ item, onClose }: { item: RankItem; onClose: () => void }) {
  const id = item.id ?? 0
  const nav = useNavigate()
  const q = useTeardown(id || undefined)
  const run = useRunTeardown(id)
  const reskin = useReskin(id)
  const last = useLastReskin(id)
  const tearing = run.busy
  const reskinning = reskin.busy
  const td = q.data?.teardown ?? null
  const ideasRef = useRef<HTMLDivElement>(null)

  // 第一次打开、还没拆过、也没有进行中/刚失败的拆解任务：自动拆一次
  const auto = useRef(false)
  useEffect(() => {
    if (!id || auto.current || q.isLoading || q.error || !run.ready || tearing || run.error) return
    if (q.data === null || (q.data && !q.data.teardown)) { auto.current = true; void run.run(false) }
  }, [id, q.isLoading, q.data, q.error, run.ready, tearing, run.error]) // eslint-disable-line react-hooks/exhaustive-deps

  // 换皮任务完成后滚到选题区（面板开着时）
  const wasReskinning = useRef(reskinning)
  useEffect(() => {
    if (wasReskinning.current && !reskinning && last) setTimeout(() => ideasRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
    wasReskinning.current = reskinning
  }, [reskinning, last])

  const doReskin = () => { void reskin.run() }
  const openIdea = (i: Idea) => { onClose(); nav(`/ideas/${i.id}`) }

  return (
    <>
      <div className="flex items-start gap-3 border-b px-5 pb-3.5 pt-3 md:pt-4">
        <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary"><Feather className="h-[18px] w-[18px]" weight="duotone" /></span>
        <div className="min-w-0 flex-1">
          <D.Title className="truncate text-[16px] font-semibold tracking-tight">仿写《{item.title}》</D.Title>
          <D.Description className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-muted-foreground">
            <span>{item.author}</span><span className="opacity-40">·</span><span>{item.category}</span>
            <span className="opacity-40">·</span><span className="num">第 {item.rank} 名</span>
            <span className="opacity-40">·</span><span className="num">在读 {fmtNum(item.read_count)}</span>
          </D.Description>
        </div>
        <D.Close className="focus-ring -mr-1.5 rounded-md p-2 text-muted-foreground hover:bg-muted" aria-label="关闭"><X className="h-4 w-4" /></D.Close>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5">
        <div className="mb-5 flex items-start gap-2 rounded-xl bg-subtle px-3.5 py-2.5 text-[12.5px] leading-relaxed text-muted-foreground">
          <ShieldCheck className="mt-[2px] h-4 w-4 shrink-0 text-success" />
          <span>只学结构、不抄内容：拆解只用书名、简介、标签和榜单数据，换皮选题会自检与原书的相似点。</span>
        </div>

        {!id ? (
          <div className="rounded-xl border border-dashed px-5 py-10 text-center">
            <div className="text-[14.5px] font-semibold">这条榜单数据缺少编号</div>
            <p className="mt-1.5 text-[13px] text-muted-foreground">可能是旧版本留下的快照，刷新一次榜单后就能仿写了。</p>
          </div>
        ) : (
          <>
            <SectionTitle
              n={1} title="结构拆解"
              extra={td && (
                <div className="flex items-center gap-2">
                  {q.data?.cached && <Badge tone="outline">缓存 · {fmtDateTime(q.data.created_at)}</Badge>}
                  <Button size="xs" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={tearing} onClick={() => void run.run(true)}>重新拆解</Button>
                </div>
              )}
            />
            {q.isLoading || (tearing && !td) ? (
              <Thinking text="正在拆这本书的爽点、金手指和开篇……" sub="后台任务，通常要 20–60 秒，可以先关掉面板，回来还能看到进度和结果。"
                progress={tearing ? run.progress : undefined} message={run.message} />
            ) : q.error ? (
              <ErrorState error={q.error} onRetry={() => q.refetch()} className="py-10" />
            ) : !td ? (
              run.error ? (
                <div className="rounded-xl border border-dashed px-5 py-8 text-center">
                  <XCircle className="mx-auto h-7 w-7 text-danger/70" />
                  <div className="mt-2 text-[14px] font-semibold">拆解没成功</div>
                  <p className="mx-auto mt-1 max-w-sm break-words text-[12.5px] text-muted-foreground">{run.error}</p>
                  <Button className="mt-4" size="sm" variant="primary" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => void run.run(false)}>再试一次</Button>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed px-5 py-8 text-center">
                  <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} onClick={() => void run.run(false)}>开始拆解</Button>
                </div>
              )
            ) : (
              <>
                {tearing && <JobProgress className="mb-3" message={run.message || '重新拆解中'} progress={run.progress} />}
                {run.error && !tearing && <ErrorLine className="mb-3" text={`重新拆解失败：${run.error}`} />}
                <div className={cn('transition-opacity', tearing && 'pointer-events-none opacity-50')}>
                  <TeardownCards td={td} />
                </div>
              </>
            )}

            {td && (
              <>
                <DeepSection itemId={id} deep={q.data?.deep ?? null} />

                <div ref={ideasRef} className="scroll-mt-4">
                  <SectionTitle n={3} title="换皮选题" />
                  <IdeasSection
                    busy={reskinning} error={reskin.error} result={last} progress={reskin.progress} message={reskin.message}
                    onRun={doReskin} onOpen={openIdea}
                    onAll={() => { onClose(); nav('/ideas') }}
                  />
                </div>
              </>
            )}
          </>
        )}
      </div>

      {id > 0 && td && (
        <div className="flex items-center gap-3 border-t bg-surface/80 px-5 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur">
          <p className="hidden min-w-0 flex-1 text-[12.5px] text-muted-foreground sm:block">保留爽点结构，换掉人设、金手指外形和世界观，存进选题库。</p>
          <Button variant="primary" size="lg" className="flex-1 sm:flex-none" icon={<Lightbulb className="h-4 w-4" />} loading={reskinning} onClick={doReskin}>
            {reskinning ? (reskin.message && reskin.message !== '排队中' ? `${reskin.message}…` : '正在想选题…') : last ? '再生成 3 个' : '生成 3 个换皮选题'}
          </Button>
        </div>
      )}
    </>
  )
}

function SectionTitle({ n, title, extra }: { n: number; title: string; extra?: React.ReactNode }) {
  return (
    <div className="mb-3 mt-1 flex min-h-[28px] items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <span className="num flex h-5 w-5 items-center justify-center rounded-full bg-foreground text-[11px] font-semibold text-background">{n}</span>
        <h3 className="text-[14.5px] font-semibold tracking-tight">{title}</h3>
      </div>
      {extra}
    </div>
  )
}

/** 后台任务进度：进度文字 + 进度条（来自 Job.progress / Job.message） */
function JobProgress({ message, progress, className }: { message: string; progress: number; className?: string }) {
  return (
    <div className={cn('rounded-lg bg-primary-soft/60 px-3 py-2', className)}>
      <div className="flex items-center gap-2 text-[12.5px] text-primary">
        <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
        <span className="min-w-0 flex-1 truncate">{message || '排队中'}</span>
        <span className="num shrink-0 text-[11.5px] opacity-80">{Math.round(progress || 0)}%</span>
      </div>
      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-primary/10">
        <div className="h-full rounded-full bg-primary/70 transition-[width] duration-500" style={{ width: `${Math.max(4, Math.min(100, progress || 0))}%` }} />
      </div>
    </div>
  )
}

function ErrorLine({ text, className }: { text: string; className?: string }) {
  return <p className={cn('break-words rounded-lg bg-danger-soft/60 px-3 py-2 text-[12.5px] text-danger', className)}>{text}</p>
}

function Thinking({ text, sub, rows = 3, progress, message }: { text: string; sub?: string; rows?: number; progress?: number; message?: string }) {
  return (
    <div className="rounded-xl border bg-surface p-4">
      <div className="flex items-center gap-2 text-[13px] font-medium text-primary"><Loader2 className="h-4 w-4 animate-spin" />{text}</div>
      {sub && <p className="mt-1 pl-6 text-[12px] text-muted-foreground">{sub}</p>}
      {progress !== undefined && <JobProgress className="mt-3" message={message || '排队中'} progress={progress} />}
      <div className="mt-4 space-y-2.5">
        <Skeleton className="h-16 rounded-lg" />
        <div className="grid gap-2.5 sm:grid-cols-2">{Array.from({ length: rows + 1 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-lg" />)}</div>
      </div>
    </div>
  )
}

function TeardownCards({ td }: { td: TeardownCore }) {
  const gf = td.golden_finger ?? { type: '', delivery: '' }
  return (
    <div className="space-y-3">
      <div className="relative overflow-hidden rounded-xl border border-primary/20 bg-primary-soft/60 px-4 py-3.5">
        <div className="text-[12px] font-medium text-primary">爽点公式</div>
        <p className="mt-1 font-serif text-[16px] font-semibold leading-relaxed">{td.payoff_formula || '—'}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <InfoCard label="金手指">
          {gf.type && <Badge tone="primary" className="mb-1.5">{gf.type}</Badge>}
          <p>{gf.delivery || (gf.type ? '' : '—')}</p>
        </InfoCard>
        <InfoCard label="主角人设">{td.protagonist_template || '—'}</InfoCard>
        <InfoCard label="开篇钩子">{td.opening_hook || '—'}</InfoCard>
        <InfoCard label="目标读者">{td.target_readers || '—'}</InfoCard>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <ListCard tone="success" label="可借鉴的结构" items={td.transferable} />
        <ListCard tone="danger" label="必须换掉" items={td.must_replace} />
      </div>
      <Warnings items={td.warnings} />
    </div>
  )
}

function InfoCard({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border bg-surface px-4 py-3">
      <div className="text-[12px] text-muted-foreground">{label}</div>
      <div className="mt-1 text-[13.5px] leading-relaxed">{children}</div>
    </div>
  )
}

function ListCard({ tone, label, items }: { tone: 'success' | 'danger'; label: string; items?: string[] }) {
  const ok = tone === 'success'
  return (
    <div className={cn('rounded-xl border px-4 py-3', ok ? 'border-success/20 bg-success-soft/40' : 'border-danger/20 bg-danger-soft/40')}>
      <div className={cn('text-[12px] font-medium', ok ? 'text-success' : 'text-danger')}>{label}</div>
      {items?.length ? (
        <ul className="mt-1.5 space-y-1.5">
          {items.map((x, i) => (
            <li key={i} className="flex gap-2 text-[13px] leading-relaxed">
              {ok ? <Check className="mt-[3px] h-3.5 w-3.5 shrink-0 text-success" strokeWidth={2.5} /> : <X className="mt-[3px] h-3.5 w-3.5 shrink-0 text-danger" strokeWidth={2.5} />}
              <span className="min-w-0 break-words">{x}</span>
            </li>
          ))}
        </ul>
      ) : <p className="mt-1 text-[13px] text-muted-foreground">—</p>}
    </div>
  )
}

export function Warnings({ items, className }: { items?: string[]; className?: string }) {
  if (!items?.length) return null
  return (
    <div className={cn('rounded-xl border border-warning/25 bg-warning-soft px-4 py-3', className)}>
      <div className="flex items-center gap-1.5 text-[12.5px] font-medium text-warning"><AlertTriangle className="h-3.5 w-3.5" />提醒（只提醒，不拦截）</div>
      <ul className="mt-1.5 space-y-1">
        {items.map((w, i) => <li key={i} className="break-words text-[12.5px] leading-relaxed text-foreground/80">· {w}</li>)}
      </ul>
    </div>
  )
}

// ---------------- 深度拆解 ----------------

function DeepSection({ itemId, deep }: { itemId: number; deep: DeepTeardown | null }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const m = useDeepTeardown(itemId)
  const busy = m.busy
  const n = useMemo(() => bare(text), [text])
  const over = n > DEEP_LIMIT
  // 任务提交成功就清空输入框（原文不保存）；进度和结果在下面显示，关掉面板也会继续
  const go = async () => { if (await m.run(text)) setText('') }
  useEffect(() => { if (busy) setOpen(true) }, [busy])

  return (
    <div className="mt-7">
      <SectionTitle n={2} title="深度拆解" extra={deep && <Badge tone="success" dot>已拆 {deep.chapters.length} 章</Badge>} />
      {deep && <DeepResult deep={deep} />}

      <div className={cn('rounded-xl border bg-surface', deep && 'mt-3')}>
        <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center gap-3 px-4 py-3 text-left">
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-medium">{deep ? '换一段试读原文重新拆' : '粘贴试读原文，按章拆节奏'}</div>
            <div className="mt-0.5 text-[12px] text-muted-foreground">程序算字数、对白比例、第一个冲突与金手指出现的位置，模型补每章冲突/爽点/钩子</div>
          </div>
          <ChevronDown className={cn('h-4 w-4 shrink-0 text-muted-foreground transition-transform', open && 'rotate-180')} />
        </button>
        {open && (
          <div className="space-y-3 border-t px-4 py-3.5">
            <Textarea
              rows={8} value={text} disabled={busy} onChange={(e) => setText(e.target.value)}
              placeholder={'把前几章粘贴到这里，章节标题单独成行效果最好，例如：\n第一章 xxx\n正文……\n第二章 xxx\n正文……'}
              className={cn('min-h-[180px] font-serif text-[13.5px]', over && 'border-danger/60 focus:border-danger')}
            />
            <div>
              <div className="h-1 overflow-hidden rounded-full bg-muted">
                <div className={cn('h-full rounded-full transition-[width] duration-300', over ? 'bg-danger' : n > DEEP_LIMIT * 0.9 ? 'bg-warning' : 'bg-primary/70')}
                  style={{ width: `${Math.min(100, (n / DEEP_LIMIT) * 100)}%` }} />
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-3 text-[12px]">
                <span className={cn('num', over ? 'font-medium text-danger' : 'text-muted-foreground')}>
                  {n.toLocaleString('zh-CN')} / {DEEP_LIMIT.toLocaleString('zh-CN')} 字{over && `，超出 ${(n - DEEP_LIMIT).toLocaleString('zh-CN')} 字`}
                </span>
                {text && !busy && <button className="text-muted-foreground hover:text-foreground" onClick={() => setText('')}>清空</button>}
              </div>
            </div>
            <p className="flex gap-1.5 text-[11.5px] leading-relaxed text-muted-foreground">
              <Info className="mt-[2px] h-3.5 w-3.5 shrink-0" />
              <span>NovelOS 不抓取番茄正文（平台禁止，正文字体也做了加密）。请粘贴你合法获得的文本；原文只用来计算和拆解，不保存。字数按去掉空白后计算。</span>
            </p>
            {busy && <JobProgress message={m.message ? `${m.message}（字数多时要 1 分钟左右，可以先关掉面板）` : '正在逐章拆解……'} progress={m.progress} />}
            {m.error && !busy && <ErrorLine text={m.error} />}
            <div className="flex justify-end">
              <Button variant="primary" icon={<Sparkles className="h-4 w-4" />} loading={busy} disabled={!n || over} onClick={() => void go()}>开始深度拆解</Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function hitTile(label: string, h: KeywordHit | null) {
  if (!h) return <Tile label={label} value={<span className="text-muted-foreground">没找到</span>} />
  return <Tile label={label} value={`第 ${h.chapter} 章`} sub={`第 ${h.at_char.toLocaleString('zh-CN')} 字 · 「${h.keyword}」`} />
}

function DeepResult({ deep }: { deep: DeepTeardown }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        <Tile label="总字数" value={fmtNum(deep.total_words)} />
        <Tile label="对白比例" value={pct(deep.dialogue_ratio)} />
        {hitTile('首个冲突', deep.first_conflict)}
        {hitTile('金手指露出', deep.first_cheat)}
      </div>
      {deep.rhythm && (
        <div className="rounded-xl border bg-surface px-4 py-3">
          <div className="text-[12px] text-muted-foreground">节奏</div>
          <p className="mt-1 text-[13.5px] leading-relaxed">{deep.rhythm}</p>
        </div>
      )}
      {deep.chapters.length > 0 && (
        <div className="overflow-hidden rounded-xl border bg-surface">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-[12.5px]">
              <thead>
                <tr className="border-b bg-subtle/50 text-left text-[11.5px] text-muted-foreground">
                  <th className="h-9 w-12 pl-3 font-medium">章</th>
                  <th className="h-9 w-[64px] text-right font-medium">字数</th>
                  <th className="h-9 w-[52px] pr-2 text-right font-medium">对白</th>
                  <th className="h-9 px-2 font-medium">冲突</th>
                  <th className="h-9 px-2 font-medium">爽点</th>
                  <th className="h-9 pl-2 pr-3 font-medium">钩子</th>
                </tr>
              </thead>
              <tbody>
                {deep.chapters.map((c) => (
                  <tr key={c.index} className="border-b border-border/60 align-top last:border-0">
                    <td className="py-2.5 pl-3">
                      <div className="num font-semibold">{c.index}</div>
                    </td>
                    <td className="num py-2.5 text-right text-muted-foreground">{fmtNum(c.words)}</td>
                    <td className="num py-2.5 pr-2 text-right text-muted-foreground">{pct(c.dialogue_ratio)}</td>
                    <td className="px-2 py-2.5 leading-relaxed">
                      {c.title && <div className="mb-0.5 truncate text-[11.5px] text-muted-foreground" title={c.title}>{c.title}</div>}
                      {c.conflict || '—'}
                    </td>
                    <td className="px-2 py-2.5 leading-relaxed">{c.payoff || '—'}</td>
                    <td className="py-2.5 pl-2 pr-3 leading-relaxed">{c.hook || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {deep.learnable?.length > 0 && <ListCard tone="success" label="可以学的写法" items={deep.learnable} />}
      {deep.overlap > 0 && !deep.warnings?.length && (
        <Warnings items={[`拆解结果里有 ${deep.overlap} 处和原文连续相同，用的时候记得改写`]} />
      )}
      <Warnings items={deep.warnings} />
    </div>
  )
}

function Tile({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-xl border bg-surface px-3 py-2.5">
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
      <div className="num mt-0.5 text-[18px] font-semibold leading-snug">{value}</div>
      {sub && <div className="num mt-0.5 truncate text-[11.5px] text-muted-foreground" title={sub}>{sub}</div>}
    </div>
  )
}

// ---------------- 换皮选题 ----------------

function IdeasSection({ busy, error, result, progress, message, onRun, onOpen, onAll }: {
  busy: boolean; error: string | null; result: ReskinResult | null; progress: number; message: string
  onRun: () => void; onOpen: (i: Idea) => void; onAll: () => void
}) {
  if (busy) {
    return (
      <div className="space-y-2.5">
        <div className="flex items-center gap-2 text-[13px] font-medium text-primary"><Loader2 className="h-4 w-4 animate-spin" />正在换皮：保留结构，换人设、金手指外形和世界观……</div>
        <JobProgress message={message ? `${message}（后台任务，可以先关掉面板）` : '排队中'} progress={progress} />
        {[0, 1, 2].map((i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)}
      </div>
    )
  }
  if (!result) {
    return (
      <div className="rounded-xl border border-dashed px-5 py-6 text-center">
        <p className="text-[13px] text-muted-foreground">基于上面的拆解，出 3 个结构相近、皮完全不同的选题，自动存进选题库，可以直接采纳建书。</p>
        {!!error && <p className="mx-auto mt-3 max-w-sm break-words rounded-lg bg-danger-soft/60 px-3 py-2 text-[12.5px] text-danger">{error}</p>}
        <Button className="mt-4" variant="soft" icon={<Lightbulb className="h-4 w-4" />} onClick={onRun}>{error ? '再试一次' : '生成 3 个换皮选题'}</Button>
      </div>
    )
  }
  return (
    <div className="space-y-2.5">
      {!!error && <ErrorLine text={`最近一次生成失败：${error}（下面是上一次的结果）`} />}
      {result.ideas.map((i) => <IdeaCard key={i.id} idea={i} onOpen={() => onOpen(i)} />)}
      <Warnings items={result.warnings.filter((w) => !result.ideas.some((i) => w.startsWith(`《${i.title}》`)))} />
      <div className="flex items-center justify-between pt-1 text-[12.5px] text-muted-foreground">
        <span>已存进选题库</span>
        <button onClick={onAll} className="flex items-center gap-1 text-primary hover:underline">去选题库<ArrowRight className="h-3 w-3" /></button>
      </div>
    </div>
  )
}

function IdeaCard({ idea, onOpen }: { idea: Idea; onOpen: () => void }) {
  const warns = idea.source?.warnings ?? []
  const similar = (idea.source?.self_check ?? []).filter((c) => c.similar).length
  return (
    <button onClick={onOpen}
      className="card-hover group block w-full rounded-xl border bg-surface px-4 py-3.5 text-left transition active:scale-[0.995]">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[14.5px] font-semibold">{idea.title}</span>
            {idea.genre && <span className="text-[12px] text-muted-foreground">{idea.genre}</span>}
          </div>
          <p className="mt-1 line-clamp-2 text-[13px] leading-relaxed text-foreground/75">{idea.logline}</p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {warns.length ? <Badge tone="warning" title={warns.join('\n')}><AlertTriangle className="h-3 w-3" />{warns.length} 条提醒</Badge> : <Badge tone="success"><ShieldCheck className="h-3 w-3" />自检通过</Badge>}
            {similar > 0 && <Badge tone="danger">{similar} 项偏像</Badge>}
            {idea.scores?.overall ? <Badge tone="outline" className="num">综合 {idea.scores.overall}</Badge> : null}
          </div>
          {warns.length > 0 && <p className="mt-1.5 line-clamp-1 text-[12px] text-warning">{warns[0]}</p>}
        </div>
        <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground transition group-hover:translate-x-0.5 group-hover:text-primary" />
      </div>
    </button>
  )
}
