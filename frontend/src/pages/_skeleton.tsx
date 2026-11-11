import { Skeleton } from '@/components/ui/misc'

export function PageSkeleton() {
  return (
    <div className="page">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="mt-3 h-7 w-64" />
      <Skeleton className="mt-2 h-4 w-96 max-w-full" />
      <div className="mt-8 grid gap-4 md:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}
      </div>
      <Skeleton className="mt-4 h-64 rounded-xl" />
    </div>
  )
}

export function GridSkeleton({ n = 6, h = 'h-40', cols = 'md:grid-cols-2 lg:grid-cols-3' }: { n?: number; h?: string; cols?: string }) {
  return (
    <div className={`grid gap-4 ${cols}`}>
      {Array.from({ length: n }).map((_, i) => <Skeleton key={i} className={`${h} rounded-xl`} />)}
    </div>
  )
}
