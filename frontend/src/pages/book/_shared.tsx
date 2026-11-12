import { Link } from 'react-router-dom'
import { ChevronRight } from '@/components/icons'
import { useBook } from '@/hooks/queries'

export function BookCrumb({ bookId, page }: { bookId: number; page?: string }) {
  const { data } = useBook(bookId)
  return (
    <div className="flex items-center gap-1 text-[12.5px] text-muted-foreground">
      <Link to="/books" className="hover:text-foreground">我的书</Link>
      <ChevronRight className="h-3 w-3" />
      <Link to={`/books/${bookId}`} className="max-w-[240px] truncate hover:text-foreground">{data?.title ?? '…'}</Link>
      {page && <><ChevronRight className="h-3 w-3" /><span className="text-foreground/80">{page}</span></>}
    </div>
  )
}
