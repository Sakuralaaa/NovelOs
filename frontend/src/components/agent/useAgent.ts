import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, qk } from '@/lib/api'
import type { AgentSessionDetail } from '@/lib/types'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1'

export const useAgentTools = () => useQuery({ queryKey: qk.agentTools, queryFn: api.agentTools, staleTime: 5 * 60_000 })
export const useAgentSessions = (bookId: number) =>
  useQuery({ queryKey: qk.agentSessions(bookId), queryFn: () => api.agentSessions(bookId), enabled: !!bookId })

/** 会话是否还在动：Agent 在跑，或者有提案的长任务（写章、生图）在跑 */
export function isBusy(d?: AgentSessionDetail) {
  if (!d) return false
  return !!d.job || d.proposals.some((p) => p.status === 'running')
}

/**
 * 会话详情。运行中：真实后端订阅 SSE（/agent/sessions/{id}/events，逐步推送新消息与状态），收到事件就刷新；
 * mock 模式或 SSE 连不上时退化为轮询。
 */
export function useAgentSession(sid: number | null) {
  const qc = useQueryClient()
  const sseOk = useRef(false)
  const q = useQuery({
    queryKey: qk.agentSession(sid ?? -1),
    queryFn: () => api.agentSession(sid!),
    enabled: !!sid,
    refetchInterval: (query) => (isBusy(query.state.data) ? (sseOk.current ? 4000 : 900) : false),
    refetchIntervalInBackground: true,
  })
  const busy = isBusy(q.data)
  const lastId = q.data?.messages.at(-1)?.id ?? 0

  useEffect(() => {
    if (!sid || !busy || USE_MOCK || typeof EventSource === 'undefined') return
    const es = new EventSource(`/api/agent/sessions/${sid}/events?after=${lastId}`, { withCredentials: true })
    let timer: number | undefined
    const refresh = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => qc.invalidateQueries({ queryKey: qk.agentSession(sid) }), 60)
    }
    es.onopen = () => { sseOk.current = true }
    es.addEventListener('message', refresh)
    es.addEventListener('state', refresh)
    es.addEventListener('done', () => {
      refresh()
      qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== 'job' && x.queryKey[0] !== 'agent' })
      es.close()
    })
    es.onerror = () => { sseOk.current = false; es.close() }
    return () => { window.clearTimeout(timer); es.close(); sseOk.current = false }
    // 只在开始忙碌 / 切换会话时建立连接
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sid, busy])

  // 忙碌结束后，书里其它数据（设定卡、大纲、章节……）可能被自动采纳改过，统一刷新
  const wasBusy = useRef(false)
  useEffect(() => {
    if (wasBusy.current && !busy) {
      qc.invalidateQueries({ predicate: (x) => x.queryKey[0] !== 'job' && !(x.queryKey[0] === 'agent' && x.queryKey[1] === 'session') })
    }
    wasBusy.current = busy
  }, [busy, qc])
  return q
}
