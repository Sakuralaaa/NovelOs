import { useEffect, useRef } from 'react'

/** combo 例："mod+s"、"mod+k"、"mod+b"。mod = Ctrl / ⌘ */
export function useHotkey(combo: string, handler: (e: KeyboardEvent) => void, enabled = true) {
  const ref = useRef(handler)
  ref.current = handler
  useEffect(() => {
    if (!enabled) return
    const parts = combo.toLowerCase().split('+')
    const key = parts[parts.length - 1]
    const mod = parts.includes('mod')
    const shift = parts.includes('shift')
    const fn = (e: KeyboardEvent) => {
      if (e.isComposing) return
      if (mod !== (e.metaKey || e.ctrlKey)) return
      if (shift !== e.shiftKey) return
      if (e.key.toLowerCase() !== key) return
      e.preventDefault()
      ref.current(e)
    }
    window.addEventListener('keydown', fn)
    return () => window.removeEventListener('keydown', fn)
  }, [combo, enabled])
}

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)
export const modKey = isMac ? '⌘' : 'Ctrl'
