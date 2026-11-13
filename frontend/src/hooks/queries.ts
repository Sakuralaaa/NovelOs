import { useCallback, useState } from 'react'
import { useIsMutating, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, qk } from '@/lib/api'
import { useActiveJob, useJobs } from '@/lib/jobs'
import type { Job, ReskinResult, Teardown } from '@/lib/types'

export const useStatus = () => useQuery({ queryKey: qk.status, queryFn: api.status, staleTime: 30_000 })
export const useChannels = () => useQuery({ queryKey: qk.channels, queryFn: api.channels })
export const useBooks = () => useQuery({ queryKey: qk.books, queryFn: api.books })
export const useBook = (id: number) => useQuery({ queryKey: qk.book(id), queryFn: () => api.book(id), enabled: !!id })
export const useJobsList = (bookId?: number) =>
  useQuery({ queryKey: qk.jobs(bookId), queryFn: () => api.jobs(bookId), refetchInterval: 5000 })

// ---------- v0.7 榜单仿写 ----------

/** 读拆解缓存；还没拆过（404）返回 null，不算错误 */
export const useTeardown = (itemId?: number) =>
  useQuery({
    queryKey: qk.teardown(itemId ?? 0),
    enabled: !!itemId,
    staleTime: 5 * 60_000,
    retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 1,
    queryFn: async (): Promise<Teardown | null> => {
      try {
        return await api.teardown(itemId!)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
  })

// v0.7.1：拆解 / 深度拆解 / 换皮选题都是后台任务（POST 立即返回 Job），避免 Cloudflare 等代理约 100 秒超时（524）。
// 面板按条目查任务列表：关掉再打开、刷新页面都能看到进行中的任务和进度；完成后刷新拆解，换皮结果取最近一次成功任务的 result。

const isActive = (j?: Job | null) => !!j && (j.status === 'queued' || j.status === 'running')

/** 这本书的仿写任务；有进行中的任务时每 1.5 秒刷新一次 */
export const useItemJobs = (itemId: number) =>
  useQuery({
    queryKey: qk.itemJobs(itemId),
    queryFn: () => api.itemJobs(itemId),
    enabled: !!itemId,
    refetchInterval: (q) => ((q.state.data ?? []).some(isActive) ? 1500 : false),
    refetchIntervalInBackground: true,
  })

export type ImitateKind = 'teardown' | 'deep' | 'reskin'
const IMITATE_JOB: Record<ImitateKind, string> = { teardown: 'radar_teardown', deep: 'radar_deep', reskin: 'radar_reskin' }
const IMITATE_LABEL: Record<ImitateKind, string> = { teardown: '拆解榜单书', deep: '深度拆解', reskin: '生成换皮选题' }

/** 发起一个仿写任务并跟踪：busy / 进度 / 后端错误信息（任务失败时取 Job.error，不只是状态码） */
export function useImitateTask<A = void>(itemId: number, kind: ImitateKind, call: (arg: A) => Promise<Job>) {
  const qc = useQueryClient()
  const { start } = useJobs()
  const jobsQ = useItemJobs(itemId)
  const key = `imitate-${kind}:${itemId}`
  const tracked = useActiveJob(key)
  const latest = jobsQ.data?.find((j) => j.kind === IMITATE_JOB[kind]) ?? null
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const active = tracked ?? (isActive(latest) ? latest : null)
  const busy = starting || !!active

  const run = useCallback(async (arg: A) => {
    setStartError(null)
    setStarting(true)
    let job: Job
    try {
      job = await call(arg)
    } catch (e: any) {
      setStartError(e?.message || `${IMITATE_LABEL[kind]}启动失败`)
      setStarting(false)
      return null
    }
    const refresh = () => qc.invalidateQueries({ queryKey: qk.itemJobs(itemId) })
    await start(Promise.resolve(job), { label: IMITATE_LABEL[kind], key, onSuccess: refresh, onError: refresh })
    await refresh()
    setStarting(false)
    return job
  }, [call, itemId, key, kind, qc, start])

  const error = startError ?? (!busy && latest?.status === 'failed' ? (latest.error || latest.message || `${IMITATE_LABEL[kind]}失败`) : null)
  return {
    run, busy, error, latest,
    /** 任务列表第一次加载完成（用来判断要不要自动拆解，避免和进行中的任务重复） */
    ready: !jobsQ.isLoading,
    progress: active?.progress ?? 0,
    message: active ? active.message || '排队中' : '',
  }
}

export const useRunTeardown = (itemId: number) =>
  useImitateTask<boolean>(itemId, 'teardown', useCallback((refresh: boolean) => api.runTeardown(itemId, refresh), [itemId]))

/** 深度拆解（粘贴试读原文，≤20000 字；为空/超限后端同步返回 400） */
export const useDeepTeardown = (itemId: number) =>
  useImitateTask<string>(itemId, 'deep', useCallback((text: string) => api.deepTeardown(itemId, text), [itemId]))

/** 生成 3 个换皮选题（存进选题库） */
export const useReskin = (itemId: number) =>
  useImitateTask<void>(itemId, 'reskin', useCallback(() => api.reskin(itemId), [itemId]))

/** 最近一次成功的换皮结果（来自任务结果，关掉面板、刷新页面后仍能看到） */
export const useLastReskin = (itemId: number): ReskinResult | null => {
  const { data } = useItemJobs(itemId)
  const ok = data?.find((j) => j.kind === 'radar_reskin' && j.status === 'succeeded')
  return (ok?.result as ReskinResult | undefined) ?? null
}

export const useIsMutatingKey = (key: readonly unknown[]) => useIsMutating({ mutationKey: key }) > 0
