import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useSyncExternalStore, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { api, apiV094, qk } from './api'
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
  /** v0.9.4：中断且可续跑 */
  resumable?: boolean
}

/** v0.9.4：interrupted 也是终态（轮询 / SSE 到此结束），可点「继续」续跑 */
export const isJobDone = (s: Job['status'] | undefined) => s === 'succeeded' || s === 'failed' || s === 'interrupted'

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
      // v0.9.4：服务重启后中断、可续跑的任务也放进托盘，方便点「继续」
      const interrupted = list.filter((j) => j.status === 'interrupted' && j.resumable !== false).slice(0, 5)
      if (!running.length && !interrupted.length) return
      setJobs((js) => {
        const ids = new Set(js.map((j) => j.id))
        return [...js, ...running.filter((j) => !ids.has(j.id)).map(toTracked),
          ...interrupted.filter((j) => !ids.has(j.id)).map((j) => ({ ...toTracked(j), doneAt: Date.now() }))]
      })
    }).catch(() => {})
  }, [])

  const start = useCallback(async (p: Promise<Job>, o: StartOpts = {}) => {
    try {
      const job = await p
      callbacks.set(job.id, o)
      setJobs((js) => [...js.filter((j) => j.id !== job.id), { ...toTracked(job), label: o.label ?? jobLabel(job.kind), key: o.key }])
      qc.invalidateQueries({ queryKey: ['jobs'] })
      if (isJobDone(job.status)) finish(job, qc)
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
    progress: job.progress, message: job.message, error: job.error, startedAt: Date.now(), resumable: job.resumable,
  }
}

function finish(job: Job, qc: ReturnType<typeof useQueryClient>) {
  const cur = jobs.find((j) => j.id === job.id)
  if (cur?.doneAt) return
  setJobs((js) => js.map((j) => (j.id === job.id ? { ...j, status: job.status, progress: job.status === 'succeeded' ? 100 : j.progress, message: job.message, error: job.error, resumable: job.resumable, doneAt: Date.now() } : j)))
  const o = callbacks.get(job.id) ?? {}
  const label0 = cur?.label ?? jobLabel(job.kind)
  if (job.status === 'interrupted') {
    // 保留回调与托盘条目：续跑成功后照常触发 onSuccess
    qc.invalidateQueries({ queryKey: ['jobs'] })
    toast.warning(`${label0}已中断`, { description: job.resumable === false ? (job.message || '这个任务不支持续跑') : '服务重启打断了任务，可在任务托盘点「继续」从断点接着跑' })
    return
  }
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
    if (isJobDone(data.status)) finish(data, qc)
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

/** v0.9.4：续跑中断的任务（POST /jobs/{id}/resume）；409 提示不可续跑 */
export function useResumeJob() {
  const qc = useQueryClient()
  return useCallback(async (id: number, label?: string) => {
    try {
      const job = await apiV094.resumeJob(id)
      // 先覆盖缓存里的 interrupted，否则 Watcher 会立即再判一次终态
      qc.setQueryData(qk.job(id), job)
      setJobs((js) => {
        const has = js.some((j) => j.id === id)
        const next = { status: job.status, progress: job.progress, message: job.message, error: null, resumable: job.resumable, doneAt: undefined }
        return has ? js.map((j) => (j.id === id ? { ...j, ...next } : j)) : [...js, { ...toTracked(job), label: label ?? jobLabel(job.kind) }]
      })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      toast.success('已继续', { description: job.message || '从断点接着跑' })
      return job
    } catch (e: any) {
      if (e?.status === 409) {
        setJobs((js) => js.map((j) => (j.id === id ? { ...j, resumable: false } : j)))
        toast.error('这个任务不能续跑', { description: e?.message || '状态不对、不支持续跑或没有断点，请重新发起' })
      } else if (e?.status === 404) {
        dismissJob(id)
        toast.error('任务不存在了')
      } else toast.error('继续失败', { description: e?.message })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      return null
    }
  }, [qc])
}
