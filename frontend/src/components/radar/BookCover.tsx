import { useEffect, useState } from 'react'
import { assetUrl } from '@/lib/api'
import { cn } from '@/lib/utils'

// 占位封面：按书名散列选一组渐变，书名竖排/横排叠在上面，和番茄书架的 3:4 封面比例一致
const PALETTES: [string, string, string][] = [
  ['#2b1d16', '#9b3a2c', '#f2c9a0'],
  ['#14233a', '#2f5d8a', '#bcd7ef'],
  ['#1f2a1e', '#4d7a45', '#d4e8c2'],
  ['#2a1630', '#7b3f8c', '#ecc8f2'],
  ['#2e2214', '#a8752b', '#f5dfb0'],
  ['#1b1b1f', '#55525c', '#e4e1ea'],
  ['#331317', '#b23a48', '#f8c9cf'],
  ['#0f2a2a', '#2b7a78', '#bfe9e5'],
]
function hash(s: string) {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619)
  return Math.abs(h)
}

export function CoverPlaceholder({ title, className, size = 'md' }: { title: string; className?: string; size?: 'sm' | 'md' | 'lg' }) {
  const h = hash(title || '?')
  const [a, b, c] = PALETTES[h % PALETTES.length]
  const t = (title || '未命名').replace(/[：:，,！!？?\s].*$/, '') || title
  const short = t.slice(0, size === 'sm' ? 6 : 8)
  return (
    <div className={cn('relative h-full w-full overflow-hidden', className)}
      style={{ background: `linear-gradient(150deg, ${a} 0%, ${b} 78%)` }}>
      <div className="absolute inset-0" style={{ background: `radial-gradient(circle at ${30 + (h % 40)}% ${20 + (h % 30)}%, ${c}66 0, transparent 58%)` }} />
      <div className="absolute -bottom-6 -left-4 h-2/5 w-[130%] rotate-[-8deg] bg-black/25" />
      <div className={cn('absolute inset-x-0 flex flex-col items-center px-1.5 text-center font-serif font-bold leading-tight text-white drop-shadow-[0_1px_2px_rgb(0_0_0/0.45)]',
        size === 'lg' ? 'top-[18%] text-[22px] tracking-[0.12em]' : size === 'sm' ? 'top-[16%] text-[12px] tracking-[0.06em]' : 'top-[16%] text-[15px] tracking-[0.08em]')}>
        <span className="line-clamp-3 break-all">{short}</span>
      </div>
      <div className={cn('absolute inset-x-0 bottom-[7%] text-center text-white/70', size === 'lg' ? 'text-[11px] tracking-[0.3em]' : 'text-[8.5px] tracking-[0.2em]')}>番茄小说</div>
    </div>
  )
}

/** 榜单书封面：后端代理的封面图，失败或为空时显示渐变占位 */
export function BookCover({ src, title, className, size = 'md', rank }: { src?: string | null; title: string; className?: string; size?: 'sm' | 'md' | 'lg'; rank?: number }) {
  const url = assetUrl(src)
  const [failed, setFailed] = useState(false)
  const [loaded, setLoaded] = useState(false)
  useEffect(() => { setFailed(false); setLoaded(false) }, [url])
  const showImg = !!url && !failed
  return (
    <div className={cn('relative aspect-[3/4] shrink-0 overflow-hidden rounded-md bg-muted shadow-[0_1px_2px_rgb(0_0_0/0.12),0_4px_12px_-4px_rgb(0_0_0/0.25)] ring-1 ring-black/5', className)}>
      {(!showImg || !loaded) && <CoverPlaceholder title={title} size={size} className="absolute inset-0" />}
      {showImg && (
        <img src={url!} alt={title} loading="lazy" decoding="async" referrerPolicy="no-referrer" draggable={false}
          onLoad={() => setLoaded(true)} onError={() => setFailed(true)}
          className={cn('absolute inset-0 h-full w-full object-cover transition-opacity duration-300', loaded ? 'opacity-100' : 'opacity-0')} />
      )}
      {/* 书脊高光 */}
      <div className="pointer-events-none absolute inset-y-0 left-0 w-[6%] bg-gradient-to-r from-black/20 to-transparent" />
      {rank !== undefined && rank <= 3 && (
        <span className="absolute left-0 top-0 rounded-br-md px-1.5 py-0.5 text-[10px] font-bold text-white" style={{ background: RANK_COLORS[rank - 1] }}>TOP{rank}</span>
      )}
    </div>
  )
}

export const RANK_COLORS = ['#b4321f', '#c95a1c', '#cf8a1d']
