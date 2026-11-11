import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'
const get = (): Theme => (document.documentElement.classList.contains('dark') ? 'dark' : 'light')
const listeners = new Set<(t: Theme) => void>()

export function setTheme(t: Theme) {
  document.documentElement.classList.toggle('dark', t === 'dark')
  document.querySelector('meta[name=theme-color]')?.setAttribute('content', t === 'dark' ? '#121318' : '#fafaf9')
  try { localStorage.setItem('novelos-theme', t) } catch { /* ignore */ }
  listeners.forEach((l) => l(t))
}
export function toggleTheme() { setTheme(get() === 'dark' ? 'light' : 'dark') }

export function useTheme() {
  const [t, setT] = useState<Theme>(get)
  useEffect(() => { listeners.add(setT); return () => { listeners.delete(setT) } }, [])
  return t
}
