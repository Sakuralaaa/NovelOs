import { useEffect, useRef } from 'react'
import { useJobsList } from '@/hooks/queries'
import { useActiveJob, useJobs, type TrackedJob } from '@/lib/jobs'
import type { Job } from '@/lib/types'
import { jobLabel } from '@/lib/utils'

const running = (j?: Job | null) => !!j && (j.status === 'queued' || j.status === 'running')

/**
 * v0.11：按「书 + 任务类型」找进行中的后台任务。
 * - 本页发起的任务用 key 跟踪（按钮 loading / JobInline）；
 * - 刷新页面、换设备打开时，从任务列表里找到正在跑的同类任务，交给 JobsProvider 接管（同一个 key），完成后照常刷新数据。
 * 返回 active（进行中，可直接给 JobInline）与 latest（最近一条同类任务，可能已失败/中断，用来显示「续跑」）。
 */
export function useKindJob(bookId: number, kind: string | string[], key: string, label?: string, opts?: { onSuccess?: (j: Job) => void }) {
  const kinds = Array.isArray(kind) ? kind : [kind]
  const tracked = useActiveJob(key)
  const list = useJobsList(bookId)
  const { start } = useJobs()
  const latest = list.data?.find((j) => kinds.includes(j.kind)) ?? null
  const adopted = useRef<number | null>(null)
  const onSuccess = useRef(opts?.onSuccess)
  onSuccess.current = opts?.onSuccess

  useEffect(() => {
    if (tracked || !latest || !running(latest) || adopted.current === latest.id) return
    adopted.current = latest.id
    void start(Promise.resolve(latest), { key, label: label ?? jobLabel(latest.kind), onSuccess: (j) => onSuccess.current?.(j) })
  }, [tracked, latest, key, label, start])

  const active: TrackedJob | undefined = tracked ?? (running(latest) && latest ? {
    id: latest.id, label: label ?? jobLabel(latest.kind), status: latest.status, progress: latest.progress, message: latest.message, startedAt: Date.now(), key,
  } : undefined)
  return { active, latest, busy: !!active }
}
