import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Eye, EyeOff, Loader2, LockKeyhole } from '@/components/icons'
import { api, qk } from '@/lib/api'
import { LogoMark } from '@/components/common/States'
import { cn } from '@/lib/utils'

export function useAuth() {
  return useQuery({ queryKey: qk.auth, queryFn: api.authStatus, staleTime: 60_000, retry: 1 })
}

export function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const { data, isLoading, error, refetch } = useAuth()

  useEffect(() => {
    const onUnauth = () => qc.invalidateQueries({ queryKey: qk.auth })
    window.addEventListener('novelos:unauthorized', onUnauth)
    return () => window.removeEventListener('novelos:unauthorized', onUnauth)
  }, [qc])

  if (isLoading) return <Splash />
  if (error) return <Splash error={(error as Error).message} onRetry={() => refetch()} />
  if (data?.enabled && !data.authenticated) return <LoginPage />
  return <>{children}</>
}

function Splash({ error, onRetry }: { error?: string; onRetry?: () => void }) {
  return (
    <div className="flex h-[100dvh] flex-col items-center justify-center gap-4">
      <LogoMark className={cn(!error && 'animate-pulse')} />
      {error && (
        <div className="text-center">
          <p className="text-sm text-muted-foreground">{error}</p>
          <button onClick={onRetry} className="mt-3 text-sm font-medium text-primary hover:underline">重试</button>
        </div>
      )}
    </div>
  )
}

function LoginPage() {
  const qc = useQueryClient()
  const [pw, setPw] = useState('')
  const [show, setShow] = useState(false)
  const [remember, setRemember] = useState(true)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [shake, setShake] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => { input.current?.focus() }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!pw || busy) return
    setBusy(true)
    setErr('')
    try {
      await api.login(pw, remember)
      qc.clear()
      await qc.invalidateQueries({ queryKey: qk.auth })
    } catch (e: any) {
      setErr(e?.message || '登录失败')
      setShake((n) => n + 1)
      setPw('')
      input.current?.focus()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-[100dvh] items-center justify-center overflow-hidden px-5">
      
      <div className="relative w-full max-w-[380px]">
        <div className="mb-8 flex flex-col items-center">
          <LogoMark className="h-12 w-12" />
          <h1 className="mt-5 text-[24px] font-bold">NovelOS</h1>
        </div>

        <form
          key={shake}
          onSubmit={submit}
          className={cn('rounded-2xl border bg-surface p-6 shadow-lift', shake > 0 && 'animate-shake')}
        >
          <label htmlFor="pw" className="mb-2 block text-[13px] font-medium">密码</label>
          <div className={cn(
            'flex h-11 items-center rounded-lg border bg-background pl-3 pr-1 transition-[border,box-shadow] focus-within:border-primary/60 focus-within:shadow-glow',
            err && 'border-danger/60',
          )}>
            <LockKeyhole className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              id="pw"
              ref={input}
              type={show ? 'text' : 'password'}
              autoComplete="current-password"
              value={pw}
              onChange={(e) => { setPw(e.target.value); if (err) setErr('') }}
              className="h-full min-w-0 flex-1 bg-transparent px-2.5 text-[14px] outline-none placeholder:text-muted-foreground/60"
              placeholder="输入访问密码"
            />
            <button type="button" tabIndex={-1} onClick={() => setShow((s) => !s)} className="flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground" aria-label={show ? '隐藏密码' : '显示密码'}>
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <div className="mt-2 h-5 text-[12.5px] text-danger">{err}</div>

          <label className="mt-1 flex cursor-pointer select-none items-center gap-2 text-[13px] text-muted-foreground">
            <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="h-4 w-4 rounded border-input accent-[hsl(var(--primary))]" />
            30 天内保持登录
          </label>

          <button
            type="submit"
            disabled={!pw || busy}
            className="mt-5 inline-flex h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary text-[14px] font-medium text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.16),0_1px_2px_rgb(30_27_75/0.2)] transition hover:brightness-[1.06] disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <>登录<ArrowRight className="h-4 w-4" /></>}
          </button>
        </form>
      </div>
    </div>
  )
}
