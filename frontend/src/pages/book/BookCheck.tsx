import { Link, useSearchParams } from 'react-router-dom'
import { FilmSlate, FlagCheckered, Scales, Stethoscope } from '@/components/icons'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Segmented } from '@/components/ui/tabs'
import { PageHeader } from '@/components/common/States'
import { BookCheckPanel } from '@/components/check/BookCheckPanel'
import { AdaptPanel } from '@/components/check/AdaptPanel'
import { HomogeneityPanel } from '@/components/check/Homogeneity'
import { useBook } from '@/hooks/queries'
import { useBookId } from '@/hooks/useBookId'
import { BookCrumb } from './_shared'

type Tab = 'book' | 'adapt' | 'homo'

export default function BookCheckPage() {
  const id = useBookId()
  const { data: book } = useBook(id)
  const [sp, setSp] = useSearchParams()
  const tab = (['book', 'adapt', 'homo'].includes(sp.get('tab') ?? '') ? sp.get('tab') : 'book') as Tab
  const setTab = (t: Tab) => { const n = new URLSearchParams(sp); if (t === 'book') n.delete('tab'); else n.set('tab', t); setSp(n, { replace: true }) }
  return (
    <div className="page max-w-[1080px]">
      <BookCrumb bookId={id} page="体检" />
      <PageHeader className="mt-3" title="作品体检" desc="收尾前的内容质量检查：整书问题清单、短剧可改编度、和榜单的同质化程度。"
        actions={<Link to={`/books/${id}/wanben`}><Button icon={<FlagCheckered className="h-4 w-4" />}>完本模式</Button></Link>} />
      <Segmented block value={tab} onChange={setTab} className="mb-6 h-10 sm:inline-flex sm:w-auto" options={[
        { value: 'book', label: <span className="inline-flex items-center gap-1.5"><Stethoscope className="h-4 w-4" />整书体检</span> },
        { value: 'adapt', label: <span className="inline-flex items-center gap-1.5"><FilmSlate className="h-4 w-4" />可改编度</span> },
        { value: 'homo', label: <span className="inline-flex items-center gap-1.5"><Scales className="h-4 w-4" />同质化</span> },
      ]} />
      {tab === 'book' && <BookCheckPanel bookId={id} />}
      {tab === 'adapt' && <AdaptPanel bookId={id} maxChapter={book?.stats.chapters ?? 1} />}
      {tab === 'homo' && <Card className="p-4 sm:p-5"><HomogeneityPanel target="book" id={id} /></Card>}
    </div>
  )
}
