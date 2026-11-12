import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/common/States'

export default function NotFound() {
  return (
    <div className="page">
      <EmptyState kind="error" title="页面不存在" action={<Link to="/"><Button variant="primary">回到首页</Button></Link>} />
    </div>
  )
}
