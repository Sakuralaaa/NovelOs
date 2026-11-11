import { useEffect, useRef } from 'react'

export function useDebouncedCallback<A extends unknown[]>(fn: (...a: A) => void, ms: number) {
  const t = useRef<ReturnType<typeof setTimeout>>()
  const f = useRef(fn)
  f.current = fn
  useEffect(() => () => clearTimeout(t.current), [])
  const call = (...a: A) => {
    clearTimeout(t.current)
    t.current = setTimeout(() => f.current(...a), ms)
  }
  call.cancel = () => clearTimeout(t.current)
  return call
}
