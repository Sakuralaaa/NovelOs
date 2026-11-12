import { Bot } from '@/components/icons'
import { PageHeader } from '@/components/common/States'
import { AgentChat } from '@/components/agent/AgentChat'
import { BookCrumb } from './_shared'
import { useBookId } from '@/hooks/useBookId'

export default function AgentPage() {
  const id = useBookId()
  return (
    <div className="page flex h-full max-w-[1100px] flex-col !pb-6">
      <BookCrumb bookId={id} page="Agent" />
      <PageHeader className="mt-3" eyebrow={<span className="flex items-center gap-1.5"><Bot className="h-3.5 w-3.5" />本书专属</span>} title="Agent"
        desc="告诉它要改什么，它会先读现状，再指挥设定库、大纲、章节、伏笔、包装去改。改动先出提案，你采纳才写入。" />
      <div className="min-h-[520px] flex-1"><AgentChat bookId={id} variant="page" autoFocus /></div>
    </div>
  )
}
