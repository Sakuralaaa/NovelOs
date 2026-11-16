import { ArrowDown, ArrowUp, ArrowUpRight, Feather, Scissors, Sparkles } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { BookCover, RANK_COLORS } from '@/components/radar/BookCover'
import type { RankBoard, RankItem } from '@/lib/types'
import { cn, fmtNum } from '@/lib/utils'

/** x 天前更新 */
export function fmtAgoDays(iso?: string | null) {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const d = Math.floor((Date.now() - t) / 86400000)
  if (d <= 0) {
    const h = Math.floor((Date.now() - t) / 3600000)
    return h <= 0 ? '刚刚更新' : `${h} 小时前更新`
  }
  if (d < 365) return `${d} 天前更新`
  return `${Math.floor(d / 365)} 年前更新`
}
export const chapterText = (n?: number | null) => (n && n > 0 ? `${n.toLocaleString('zh-CN')} 章` : '— 章')

export function RankDiff({ v, className }: { v?: number; className?: string }) {
  if (!v) return null
  const up = v > 0
  return (
    <span className={cn('num inline-flex items-center gap-px rounded px-1 py-px text-[10.5px] font-semibold leading-none', up ? 'bg-danger-soft text-danger' : 'bg-success-soft text-success', className)}
      title={up ? `上升 ${v} 名` : `下降 ${-v} 名`}>
      {up ? <ArrowUp className="h-2.5 w-2.5" strokeWidth={3} /> : <ArrowDown className="h-2.5 w-2.5" strokeWidth={3} />}{Math.abs(v)}
    </span>
  )
}

export function BoardTag({ board }: { board?: RankBoard }) {
  const b = board ?? 'read'
  return <span className={cn('shrink-0 rounded px-1.5 py-px text-[10.5px] font-medium', b === 'new' ? 'bg-primary-soft text-primary' : 'bg-muted text-muted-foreground')}>{b === 'new' ? '新书' : '阅读'}</span>
}

/** 名次：大号数字，前三名强调色 */
export function RankNumber({ n, className }: { n: number; className?: string }) {
  const top = n <= 3
  return (
    <span className={cn('num block text-center font-serif font-bold italic leading-none tracking-tight', n >= 100 ? 'text-[22px]' : 'text-[28px]', !top && 'text-foreground/25', className)}
      style={top ? { color: RANK_COLORS[n - 1] } : undefined}>
      {n}
    </span>
  )
}

/** 番茄书架式卡片：名次 + 竖版封面 + 书名/作者/章节/在读 + 两行简介 + 题材标签 + 操作 */
export function ShelfCard({ item: i, n, onOpen, onAnalyze, onImitate, onTeardown }: {
  item: RankItem; n: number; onOpen: () => void; onAnalyze: () => void; onImitate: () => void; onTeardown?: () => void
}) {
  const tags = [...new Set([i.category, ...(i.tags ?? [])].filter(Boolean))].slice(0, 4)
  const ago = fmtAgoDays(i.last_update_at)
  const stop = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); fn() }
  return (
    <div role="button" tabIndex={0} onClick={onOpen} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen() } }}
      className="card-hover focus-ring group relative flex min-w-0 cursor-pointer gap-3 rounded-xl border bg-surface p-3.5 text-left transition active:scale-[0.995] sm:gap-3.5 sm:p-4">
      <div className="flex w-8 shrink-0 flex-col items-center gap-1.5 pt-1 sm:w-9">
        <RankNumber n={n} />
        <RankDiff v={i.rank_diff} />
      </div>
      <BookCover src={i.cover} title={i.title} className="w-[76px] self-start sm:w-[84px]" size="sm" />
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-w-0 items-center gap-1.5">
          <h3 className="truncate text-[15.5px] font-bold leading-snug tracking-tight">{i.title}</h3>
          <BoardTag board={i.board} />
        </div>
        <div className="num mt-1 flex min-w-0 items-center gap-1 truncate text-[12.5px] text-muted-foreground">
          <span className="truncate">{i.author || '佚名'}</span>
          <span className="opacity-40">·</span><span className="shrink-0">{chapterText(i.chapter_count)}</span>
          <span className="opacity-40">·</span><span className="shrink-0">在读 {fmtNum(i.read_count)}</span>
        </div>
        <p className="mt-1.5 line-clamp-2 text-[13px] leading-[1.6] text-foreground/70">{i.abstract || '暂无简介'}</p>
        <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5 overflow-hidden" style={{ maxHeight: 24 }}>
          {tags.map((t, k) => (
            <span key={t} className={cn('h-[22px] shrink-0 rounded-md px-1.5 text-[11.5px] leading-[22px]', k === 0 ? 'bg-primary-soft font-medium text-primary' : 'bg-muted/80 text-muted-foreground')}>{t}</span>
          ))}
          {ago && <span className="ml-auto shrink-0 text-[11.5px] text-muted-foreground/80">{ago}</span>}
        </div>
        <div className="mt-auto flex min-w-0 flex-wrap items-center gap-1.5 pt-3">
          <Button size="sm" variant="ghost" className="h-10 px-2.5 sm:h-8" icon={<Sparkles className="h-3.5 w-3.5" />} onClick={stop(onAnalyze)}>AI 分析</Button>
          {onTeardown && <Button size="sm" variant="ghost" className="h-10 px-2.5 sm:h-8" icon={<Scissors className="h-3.5 w-3.5" />} onClick={stop(onTeardown)}>拆书</Button>}
          <Button size="sm" variant="soft" className="h-10 px-2.5 sm:h-8" icon={<Feather className="h-3.5 w-3.5" />} onClick={stop(onImitate)}>仿写立项</Button>
          {i.source_url ? (
            <a href={i.source_url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}
              className="focus-ring ml-auto inline-flex h-10 shrink-0 items-center gap-1 rounded-md px-2.5 text-[13px] font-medium text-foreground/70 transition hover:bg-muted hover:text-foreground sm:h-8">
              原文<ArrowUpRight className="h-3.5 w-3.5" />
            </a>
          ) : null}
        </div>
      </div>
    </div>
  )
}
