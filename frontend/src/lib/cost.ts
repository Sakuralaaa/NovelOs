import { useSyncExternalStore } from 'react'

/** v0.9.3：AI 操作前的成本提示，可在设置里关掉（只存本机 localStorage） */
const LS = 'novelos-cost-hint'
const listeners = new Set<() => void>()
const read = () => { try { return localStorage.getItem(LS) !== '0' } catch { return true } }
export function setCostHint(on: boolean) {
  try { localStorage.setItem(LS, on ? '1' : '0') } catch { /* ignore */ }
  listeners.forEach((l) => l())
}
export function useCostHint() {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l) }, read)
}

export const fmtTokens = (n?: number | null) => {
  const v = Number(n) || 0
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(v >= 10_000_000 ? 0 : 1)}M`
  if (v >= 10_000) return `${(v / 1000).toFixed(v >= 100_000 ? 0 : 1)}k`
  return v.toLocaleString('zh-CN')
}
export const fmtSeconds = (s?: number | null) => {
  const v = Math.max(0, Math.round(Number(s) || 0))
  if (v < 60) return `约 ${v || 1} 秒`
  const m = Math.round(v / 60)
  return m < 60 ? `约 ${m} 分钟` : `约 ${(v / 3600).toFixed(1)} 小时`
}

/** v0.12：人民币金额，小额保留到分以下 */
export const fmtCny = (v: number) => (v <= 0 ? '¥0' : v < 0.01 ? '<¥0.01' : `¥${v < 10 ? v.toFixed(2) : v.toFixed(1)}`)
