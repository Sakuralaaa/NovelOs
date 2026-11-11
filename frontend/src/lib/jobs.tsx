import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, qk } from './api'
import type { Job } from './types'
import { jobLabel } from './utils'

export interface TrackedJob {
  id: number
  label: string
  key?: string
  bookId?: number | null
  status: Job['status']
  progress: number
  message: string
  error?: string | null
  startedAt: number
  doneAt?: number
}

interface StartOpts {
  label?: string
  /** 用于让对应按钮显示 loading，例如 `write-next:3` */
  key?: string
  silent?: boolean
  successMsg?: string | ((job: Job) => string)
  onSuccess?: (job: Job) => void
  onError?: (job: Job) => void
}

// ---------- 极简 store ----------
const LS = 'novelos-jobs'
let jobs: TrackedJob[] = []
try {
  const raw = JSON.parse(localStorage.getItem(LS) || '[]') as TrackedJob[]
  jobs = raw.filter((j) => j.status === 'queued' || j.status === 'running')
} catch { /* ignore */ }
const listeners = new Set<() => void>()
const callbacks = new Map<number, StartOpts>()
function emit() {
  try { localStorage.setItem(LS, JSON.stringify(jobs.filter((j) => !j.doneAt))) } catch { /* ignore */ }
  listeners.forEach((l) => l())
}
function setJobs(fn: (j: TrackedJob[]) => TrackedJob[]) { jobs = fn(jobs); emit() }
const subscribe = (l: () => void) => { listeners.add(l); return () => listeners.delete(l) }

export function useTrackedJobs() {
  return useSyncExternalStore(subscribe, () => jobs)
}
/** 某个按钮对应的进行中任务 */
export function useActiveJob(key: string | undefined) {
  const all = useTrackedJobs()
  return key ? all.find((j) => j.key === key && !j.doneAt) : undefined
}
export function dismissJob(id: number) { setJobs((js) => js.filter((j) => j.id !== id)) }
export function clearFinished() { setJobs((js) => js.filter((j) => !j.doneAt)) }

// ---------- 通用轮询 hook ----------
export function useJobPolling(id: number | null | undefined) {
  return useQuery({
    queryKey: qk.job(id ?? -1),
    queryFn: () => api.job(id!),
    enabled: !!id,
    refetchInterval: (q) => {
      const s = q.state.data?.status
      return !s || s === 'queued' || s === 'running' ? 1500 : false
    },
    refetchIntervalInBackground: true,
    retry: 2,
  })
}

const Ctx = createContext<{ start: (p: Promise<Job>, o?: StartOpts) => Promise<Job | null> } | null>(null)

export function JobsProvider({ children }: { children: ReactNode }) {
  const tracked = useTrackedJobs()
  const qc = useQueryClient()
  const synced = useRef(false)

  // 首次加载：把后端正在跑的任务也收进托盘
  useEffect(() => {
    if (synced.current) return
    synced.current = true
    api.jobs().then((list) => {
      const running = list.filter((j) => j.status === 'running' || j.status === 'queued')
      if (!running.length) return
      setJobs((js) => {
        const ids = new Set(js.map((j) => j.id))
        return [...js, ...running.filter((j) => !ids.has(j.id)).map(toTracked)]
      })
    }).catch(() => {})
  }, [])

  const start = useCallback(async (p: Promise<Job>, o: StartOpts = {}) => {
    try {
      const job = await p
      callbacks.set(job.id, o)
      setJobs((js) => [...js.filter((j) => j.id !== job.id), { ...toTracked(job), label: o.label ?? jobLabel(job.kind), key: o.key }])
      qc.invalidateQueries({ queryKey: ['jobs'] })
      if (job.status === 'succeeded' || job.status === 'failed') finish(job, qc)
      return job
    } catch (e: any) {
      toast.error(o.label ? `${o.label}启动失败` : '任务启动失败', { description: e?.message })
      return null
    }
  }, [qc])

  const value = useMemo(() => ({ start }), [start])
  return (
    <Ctx.Provider value={value}>
      {children}
      {tracked.filter((j) => !j.doneAt).map((j) => <Watcher key={j.id} id={j.id} />)}
    </Ctx.Provider>
  )
}

function toTracked(job: Job): TrackedJob {
  return {
    id: job.id, label: jobLabel(job.kind), bookId: job.book_id, status: job.status,
    progress: job.progress, message: job.message, error: job.error, startedAt: Date.now(),
  }
}

function finish(job: Job, qc: ReturnType<typeof useQueryClient>) {
  const cur = jobs.find((j) => j.id === job.id)
  if (cur?.doneAt) return
  setJobs((js) => js.map((j) => (j.id === job.id ? { ...j, status: job.status, progress: job.status === 'succeeded' ? 100 : j.progress, message: job.message, error: job.error, doneAt: Date.now() } : j)))
  const o = callbacks.get(job.id) ?? {}
  callbacks.delete(job.id)
  // 生成类任务影响面广，直接让当前可见的数据全部重新拉取
  qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'job' })
  const label = cur?.label ?? jobLabel(job.kind)
  if (job.status === 'succeeded') {
    if (!o.silent) {
      const msg = typeof o.successMsg === 'function' ? o.successMsg(job) : o.successMsg
      toast.success(msg ?? `${label}完成`)
    }
    o.onSuccess?.(job)
  } else {
    toast.error(`${label}失败`, { description: job.error || job.message || '请稍后重试，或检查模型设置' })
    o.onError?.(job)
  }
  setTimeout(() => setJobs((js) => js.filter((j) => j.id !== job.id || !j.doneAt)), 8000)
}

function Watcher({ id }: { id: number }) {
  const qc = useQueryClient()
  const { data, error } = useJobPolling(id)
  useEffect(() => {
    if (!data) return
    if (data.status === 'succeeded' || data.status === 'failed') finish(data, qc)
    else setJobs((js) => js.map((j) => (j.id === id ? { ...j, status: data.status, progress: data.progress, message: data.message } : j)))
  }, [data, id, qc])
  useEffect(() => {
    if (error && (error as any).status === 404) dismissJob(id)
  }, [error, id])
  return null
}

export function useJobs() {
  const c = useContext(Ctx)
  if (!c) throw new Error('JobsProvider missing')
  return c
}
