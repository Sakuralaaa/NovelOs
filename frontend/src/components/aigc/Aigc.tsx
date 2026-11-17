import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Highlighter, KeyRound, RefreshCw, ShieldCheck } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { JobInline } from '@/components/common/JobInline'
import { api, qk } from '@/lib/api'
import type { TrackedJob } from '@/lib/jobs'
import type { AigcResult, AigcSegment } from '@/lib/types'
import { cn, fmtDateTime, fmtNum } from '@/lib/utils'

export const AIGC_DISCLAIMER = '检测结果仅供自查；发布时请按平台要求如实申报 AI 辅助创作。'
export const AIGC_MAX = 120000

export const LEVEL: Record<AigcResult['level'], { label: string; text: string; bg: string; ring: string; bar: string }> = {
  low: { label: '低', text: 'text-success', bg: 'bg-success-soft', ring: 'ring-success/25', bar: 'bg-success' },
  mid: { label: '中', text: 'text-warning', bg: 'bg-warning-soft', ring: 'ring-warning/30', bar: 'bg-warning' },
  high: { label: '高', text: 'text-danger', bg: 'bg-danger-soft', ring: 'ring-danger/25', bar: 'bg-danger' },
}
export const SEG_STYLE = {
  ai: { label: 'AI', mark: 'bg-danger/15 shadow-[inset_0_-2px_0_0_hsl(var(--danger)/0.65)]', dot: 'bg-danger' },
  suspect: { label: '疑似', mark: 'bg-warning/20 shadow-[inset_0_-2px_0_0_hsl(var(--warning)/0.7)]', dot: 'bg-warning' },
  human: { label: '人工', mark: '', dot: 'bg-success' },
} as const

/** 0–1 或 0–100 都按百分比显示 */
export const pct = (v?: number | null) => {
  if (v === null || v === undefined || Number.isNaN(v)) return 0
  return Math.max(0, Math.min(100, v <= 1 ? v * 100 : v))
}
const levelOf = (r: AigcResult): AigcResult['level'] => (LEVEL[r.level] ? r.level : pct(r.softmax) >= 85 ? 'high' : pct(r.softmax) >= 50 ? 'mid' : 'low')

export const useZhuque = () => useQuery({ queryKey: qk.zhuque, queryFn: api.zhuqueSettings, retry: false, staleTime: 60_000 })

/** 浏览器能算就算 sha256（hex），用来和后端 content_hash 对比；算不了返回 null */
export async function sha256Hex(text: string): Promise<string | null> {
  try {
    if (!window.isSecureContext || !crypto?.subtle) return null
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')
  } catch { return null }
}
export function useSha256(text: string, enabled = true) {
  const [h, setH] = useState<string | null>(null)
  useEffect(() => {
    if (!enabled) return
    let live = true
    const t = setTimeout(() => { void sha256Hex(text).then((x) => { if (live) setH(x) }) }, 400)
    return () => { live = false; clearTimeout(t) }
  }, [text, enabled])
  return h
}

/** 未配置朱雀密钥 */
export function ZhuqueSetupHint({ className }: { className?: string }) {
  return (
    <div className={cn('rounded-xl border border-dashed px-4 py-5 text-center', className)}>
      <KeyRound className="mx-auto h-6 w-6 text-muted-foreground" />
      <div className="mt-2 text-[14px] font-semibold">还没有配置朱雀 API Key</div>
      <p className="mx-auto mt-1 max-w-xs text-[12.5px] leading-relaxed text-muted-foreground">在 EdgeOne Makers 免费创建一个 API Key，粘贴到设置页就能检测 AI 率。</p>
      <Link to="/settings#aigc" className="focus-ring mt-3 inline-flex h-9 items-center gap-1 rounded-md bg-primary px-3.5 text-[13px] font-medium text-primary-foreground">去设置<ArrowRight className="h-3.5 w-3.5" /></Link>
    </div>
  )
}

/** 结果卡：大数字 + 档位 + 三段占比 + 元信息 */
export function AigcSummary({ r, stale, staleNote, onRerun, running, compact }: {
  r: AigcResult; stale?: boolean; staleNote?: string; onRerun?: () => void; running?: boolean; compact?: boolean
}) {
  const lv = LEVEL[levelOf(r)]
  const big = pct(r.softmax)
  const lr = r.labels_ratio ?? { human: 0, ai: 0, suspect: 0 }
  const parts = [
    { k: 'human', label: '人工', v: pct(lr.human), c: 'bg-success/80' },
    { k: 'suspect', label: '疑似', v: pct(lr.suspect), c: 'bg-warning/85' },
    { k: 'ai', label: 'AI', v: pct(lr.ai), c: 'bg-danger/80' },
  ]
  const sum = parts.reduce((n, p) => n + p.v, 0) || 1
  return (
    <div className={cn('rounded-xl p-4 ring-1 ring-inset', lv.bg, lv.ring, stale && 'opacity-90')}>
      {stale && (
        <div className="-mx-1 -mt-1 mb-3 flex items-center gap-2 rounded-lg bg-surface/80 px-2.5 py-2 text-[12.5px] text-warning">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          <span className="min-w-0 flex-1">{staleNote || '检测后正文有修改，结果已过期'}</span>
          {onRerun && <button onClick={onRerun} disabled={running} className="shrink-0 font-medium underline-offset-2 hover:underline disabled:opacity-50">重新检测</button>}
        </div>
      )}
      <div className="flex items-end justify-between gap-3">
        <div>
          <div className="text-[12px] text-muted-foreground">整体 AI 置信度</div>
          <div className={cn('num mt-0.5 flex items-baseline font-semibold leading-none tracking-tight', lv.text, compact ? 'text-[38px]' : 'text-[46px]')}>
            {big.toFixed(big >= 10 ? 0 : 1)}<span className="ml-0.5 text-[18px]">%</span>
          </div>
        </div>
        <span className={cn('mb-1 inline-flex h-7 items-center rounded-full bg-surface px-3 text-[13px] font-semibold shadow-xs', lv.text)}>{lv.label} 风险</span>
      </div>
      <div className="mt-4">
        <div className="flex h-2.5 overflow-hidden rounded-full bg-surface">
          {parts.map((p) => p.v > 0 && <div key={p.k} className={cn('h-full transition-[width] duration-500', p.c)} style={{ width: `${(p.v / sum) * 100}%` }} />)}
        </div>
        <div className="mt-2 grid grid-cols-3 gap-1 text-[12px]">
          {parts.map((p) => (
            <div key={p.k} className="flex items-center gap-1.5">
              <i className={cn('h-2 w-2 shrink-0 rounded-sm', p.c)} /><span className="text-muted-foreground">{p.label}</span><span className="num font-semibold">{p.v.toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
      <div className="num mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-black/5 pt-2.5 text-[11.5px] text-muted-foreground dark:border-white/10">
        {r.ai_segment_ratio !== undefined && r.ai_segment_ratio !== null
          ? <span>AI 段 {pct(r.ai_segment_ratio).toFixed(0)}% · 疑似段 {pct(r.suspect_segment_ratio ?? 0).toFixed(0)}%</span>
          : r.ratio !== undefined && r.ratio !== null && <span>AI 比例 {pct(r.ratio).toFixed(0)}%</span>}
        {!!r.chars && <span>{r.chars.toLocaleString('zh-CN')} 字</span>}
        <span>{fmtNum(r.tokens)} tokens{r.chunks > 1 ? ` · 分 ${r.chunks} 段` : ''}</span>
        {r.checked_at && <span>检测于 {fmtDateTime(r.checked_at)}</span>}
      </div>
    </div>
  )
}

/** AI / 疑似片段列表，点一下定位到正文 */
export function SegmentList({ text, segments, onLocate, max = 30 }: { text: string; segments: AigcSegment[]; onLocate: (s: AigcSegment) => void; max?: number }) {
  const list = useMemo(() => segments.filter((s) => s.label !== 'human' && s.end > s.start).sort((a, b) => b.conf - a.conf || a.start - b.start), [segments])
  const [all, setAll] = useState(false)
  if (!list.length) return <p className="rounded-lg bg-subtle px-3 py-3 text-center text-[12.5px] text-muted-foreground">没有标出 AI 或疑似片段</p>
  const shown = all ? list : list.slice(0, max)
  return (
    <div className="space-y-1.5">
      {shown.map((s, i) => {
        const snip = text.slice(s.start, s.end).replace(/\s+/g, ' ').trim()
        const st = SEG_STYLE[s.label]
        return (
          <button key={`${s.start}-${i}`} onClick={() => onLocate(s)}
            className="group flex w-full items-start gap-2 rounded-lg border bg-surface px-3 py-2 text-left transition hover:border-foreground/15 hover:bg-subtle active:scale-[0.995]">
            <span className={cn('mt-[3px] inline-flex h-[18px] shrink-0 items-center rounded px-1.5 text-[10.5px] font-semibold text-white', st.dot)}>{st.label}</span>
            <span className="min-w-0 flex-1">
              <span className="line-clamp-2 font-serif text-[13px] leading-relaxed text-foreground/85">{snip || <span className="text-muted-foreground">（位置 {s.start}–{s.end}）</span>}</span>
              <span className="num mt-0.5 block text-[11px] text-muted-foreground">置信 {pct(s.conf).toFixed(0)}% · {s.end - s.start} 字</span>
            </span>
          </button>
        )
      })}
      {list.length > max && <Button size="xs" variant="ghost" className="w-full" onClick={() => setAll(!all)}>{all ? '收起' : `显示全部 ${list.length} 段`}</Button>}
    </div>
  )
}

/** 只读原文 + AI/疑似段高亮（独立检测页用） */
export function HighlightedText({ text, segments, show, focus, onPick, className }: {
  text: string; segments: AigcSegment[]; show: boolean; focus?: AigcSegment | null; onPick?: (s: AigcSegment) => void; className?: string
}) {
  const nodes = useMemo(() => {
    const segs = show ? segments.filter((s) => s.label !== 'human' && s.end > s.start).sort((a, b) => a.start - b.start) : []
    const out: React.ReactNode[] = []
    let pos = 0
    segs.forEach((s, i) => {
      if (s.start < pos) return
      out.push(text.slice(pos, s.start))
      const f = focus && focus.start === s.start && focus.end === s.end
      out.push(
        <mark key={i} id={`aigc-seg-${s.start}`} onClick={() => onPick?.(s)}
          className={cn('cursor-pointer rounded-sm text-inherit', SEG_STYLE[s.label].mark, f && 'animate-flash ring-2 ring-primary/40')}>
          {text.slice(s.start, Math.min(s.end, text.length))}
        </mark>,
      )
      pos = s.end
    })
    out.push(text.slice(pos))
    return out
  }, [text, segments, show, focus, onPick])
  return <div className={cn('prose-zh whitespace-pre-wrap break-words font-serif text-[16px] leading-[1.9]', className)}>{nodes}</div>
}

export function HighlightToggle({ checked, onChange, disabled, note }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; note?: string }) {
  return (
    <label className={cn('flex min-h-[44px] cursor-pointer items-center justify-between gap-3 rounded-lg bg-subtle px-3 py-2', disabled && 'pointer-events-none opacity-50')}>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5 text-[13px] font-medium"><Highlighter className="h-3.5 w-3.5" />在正文中高亮</span>
        <span className="mt-0.5 flex items-center gap-2.5 text-[11.5px] text-muted-foreground">
          <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-danger/70" />AI</span>
          <span className="flex items-center gap-1"><i className="h-2 w-2 rounded-sm bg-warning/80" />疑似</span>
          {note && <span className="truncate text-warning">{note}</span>}
        </span>
      </span>
      <Switch checked={checked} onCheckedChange={onChange} />
    </label>
  )
}

export function Disclaimer({ className }: { className?: string }) {
  return <p className={cn('flex items-start gap-1.5 text-[11.5px] leading-relaxed text-muted-foreground', className)}><ShieldCheck className="mt-[2px] h-3.5 w-3.5 shrink-0" />{AIGC_DISCLAIMER}</p>
}

/** 章节页右侧「AI 率」面板 */
export function AigcPanel({ aigc, text, job, onRun, stale, staleNote, showHl, onToggleHl, onLocate, disabled, reportUrl }: {
  aigc: AigcResult | null | undefined; text: string; job?: TrackedJob; onRun: () => void; stale: boolean; staleNote?: string
  showHl: boolean; onToggleHl: (v: boolean) => void; onLocate: (s: AigcSegment) => void; disabled?: string | false; reportUrl?: string
}) {
  const cfg = useZhuque()
  const configured = !!cfg.data?.zhuque_configured
  const running = !!job
  return (
    <div className="space-y-4">
      {cfg.data && !configured && !aigc ? <ZhuqueSetupHint /> : (
        <>
          {job && <JobInline job={job} />}
          {aigc ? (
            <>
              <AigcSummary r={aigc} stale={stale} staleNote={staleNote} onRerun={configured ? onRun : undefined} running={running} compact />
              <HighlightToggle checked={showHl} onChange={onToggleHl} note={stale && showHl ? '位置可能偏移' : undefined} />
              {reportUrl && <a href={reportUrl} target="_blank" rel="noreferrer" className="inline-flex h-10 items-center gap-1 text-[13px] text-primary hover:underline">检测报告（可打印成 PDF）</a>}
              <div>
                <h4 className="mb-2 text-[13px] font-semibold">AI / 疑似片段</h4>
                <SegmentList text={text} segments={aigc.segments ?? []} onLocate={onLocate} />
              </div>
            </>
          ) : !running && (
            <div className="rounded-xl bg-subtle px-4 py-6 text-center">
              <div className="text-[14px] font-semibold">还没有检测过这一章</div>
              <p className="mx-auto mt-1 max-w-[240px] text-[12.5px] leading-relaxed text-muted-foreground">用腾讯朱雀检测正文的 AI 生成概率，标出可疑片段。</p>
            </div>
          )}
          {!configured && aigc && cfg.data && <p className="text-[12px] text-muted-foreground">朱雀密钥未配置，<Link className="text-primary hover:underline" to="/settings#aigc">去设置</Link>后才能重新检测。</p>}
          <Button className="w-full" variant={aigc && !stale ? 'secondary' : 'primary'} size="lg" loading={running}
            disabled={!configured || !!disabled || !text.trim()} title={disabled || undefined}
            icon={<RefreshCw className="h-4 w-4" />} onClick={onRun}>
            {running ? '检测中…' : aigc ? '重新检测' : '检测 AI 率'}
          </Button>
          {disabled && <p className="-mt-2 text-center text-[11.5px] text-muted-foreground">{disabled}</p>}
        </>
      )}
      <Disclaimer />
    </div>
  )
}
