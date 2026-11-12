import { Loader2 } from '@/components/icons'
import { Progress } from '@/components/ui/misc'
import type { TrackedJob } from '@/lib/jobs'
import { cn } from '@/lib/utils'

/** 卡片内联的任务进度条 */
export function JobInline({ job, className }: { job?: TrackedJob; className?: string }) {
  if (!job) return null
  return (
    <div className={cn('rounded-lg bg-primary-soft/70 px-3.5 py-2.5', className)}>
      <div className="mb-1.5 flex items-center justify-between gap-3 text-[12.5px]">
        <span className="flex min-w-0 items-center gap-1.5 font-medium text-primary">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
          <span className="truncate">{job.message || `${job.label}…`}</span>
        </span>
        <span className="num shrink-0 text-muted-foreground">{Math.round(job.progress)}%</span>
      </div>
      <Progress value={job.progress} />
    </div>
  )
}
