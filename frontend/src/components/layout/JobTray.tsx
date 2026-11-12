import { useState } from 'react'
import { useMatch } from 'react-router-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, ChevronDown, Loader2, X, XCircle } from '@/components/icons'
import { Progress } from '@/components/ui/misc'
import { clearFinished, dismissJob, useTrackedJobs } from '@/lib/jobs'
import { cn } from '@/lib/utils'

export function JobTray() {
  const jobs = useTrackedJobs()
  const [open, setOpen] = useState(true)
  // 书内页面右下角有 Agent 按钮，任务托盘让到它上面
  const inBook = useMatch('/books/:bookId/*')
  const agentFab = !!inBook && /^\d+$/.test(inBook.params.bookId ?? '') && !(inBook.params['*'] ?? '').startsWith('agent')
  if (!jobs.length) return null
  const running = jobs.filter((j) => !j.doneAt)
  return (
    <div className={cn('pointer-events-none fixed right-4 z-40', agentFab ? 'bottom-[76px] md:bottom-[92px] md:right-7' : 'bottom-4')} style={{ width: 340, maxWidth: 'calc(100vw - 2rem)' }}>
      <motion.div layout initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="pointer-events-auto overflow-hidden rounded-xl bg-popover shadow-pop hairline">
        <button onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left">
          <span className="flex items-center gap-2 text-[13px] font-semibold">
            {running.length ? <Loader2 className="h-4 w-4 animate-spin text-primary" /> : <CheckCircle2 className="h-4 w-4 text-success" />}
            {running.length ? `${running.length} 个任务进行中` : '任务已完成'}
          </span>
          <span className="flex items-center gap-1">
            {!running.length && (
              <span role="button" tabIndex={0} onClick={(e) => { e.stopPropagation(); clearFinished() }} className="rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted">清除</span>
            )}
            <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform', !open && 'rotate-180')} />
          </span>
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div initial={{ height: 0 }} animate={{ height: 'auto' }} exit={{ height: 0 }} transition={{ duration: 0.18 }} className="overflow-hidden">
              <div className="max-h-[300px] space-y-1 overflow-y-auto border-t px-2 py-2">
                {jobs.map((j) => (
                  <div key={j.id} className="group rounded-lg px-2 py-2 hover:bg-subtle">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex min-w-0 items-center gap-2">
                        {j.status === 'succeeded' ? <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" /> : j.status === 'failed' ? <XCircle className="h-3.5 w-3.5 shrink-0 text-danger" /> : <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-primary" />}
                        <span className="truncate text-[13px] font-medium">{j.label}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="num text-xs text-muted-foreground">{j.status === 'failed' ? '失败' : `${Math.round(j.progress)}%`}</span>
                        {j.doneAt && (
                          <button onClick={() => dismissJob(j.id)} className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-muted group-hover:opacity-100" aria-label="移除">
                            <X className="h-3 w-3" />
                          </button>
                        )}
                      </div>
                    </div>
                    {!j.doneAt && <Progress className="mt-1.5" value={j.progress} indeterminate={j.status === 'queued'} />}
                    {(j.message || j.error) && (
                      <p className={cn('mt-1 truncate text-xs', j.status === 'failed' ? 'text-danger' : 'text-muted-foreground')}>{j.error || j.message}</p>
                    )}
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  )
}
