import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, qk } from '@/lib/api'
import type { ReskinResult, Teardown } from '@/lib/types'

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

/** 拆解 / 重新拆解。结果写回缓存，抽屉关掉再打开也还在 */
export const useRunTeardown = (itemId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: ['teardown', itemId],
    mutationFn: (refresh: boolean = false) => api.runTeardown(itemId, refresh),
    meta: { errorTitle: '拆解失败' },
    onSuccess: (d) => qc.setQueryData(qk.teardown(itemId), d),
  })
}

/** 深度拆解（粘贴试读原文，≤20000 字） */
export const useDeepTeardown = (itemId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: ['teardown-deep', itemId],
    mutationFn: (text: string) => api.deepTeardown(itemId, text),
    meta: { errorTitle: '深度拆解失败' },
    onSuccess: (d) => qc.setQueryData(qk.teardown(itemId), d),
  })
}

/** 生成 3 个换皮选题（存进选题库） */
export const useReskin = (itemId: number) => {
  const qc = useQueryClient()
  return useMutation({
    mutationKey: ['reskin', itemId],
    mutationFn: () => api.reskin(itemId),
    meta: { errorTitle: '生成换皮选题失败' },
    onSuccess: (d) => {
      qc.setQueryData(qk.reskin(itemId), d)
      qc.invalidateQueries({ queryKey: qk.ideas, exact: true })
    },
  })
}

/** 上次生成的换皮选题（只在本次会话内保留） */
export const useLastReskin = (itemId: number) =>
  useQuery<ReskinResult | null>({ queryKey: qk.reskin(itemId), queryFn: () => null, enabled: false, staleTime: Infinity, gcTime: Infinity })

export const useIsMutatingKey = (key: readonly unknown[]) => useIsMutating({ mutationKey: key }) > 0
