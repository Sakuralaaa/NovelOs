import { useEffect, useState } from 'react'
import { Link, useMatch } from 'react-router-dom'
import * as D from '@radix-ui/react-dialog'
import { ArrowUpRight, Bot, X } from '@/components/icons'
import { Tip } from '@/components/ui/tooltip'
import { useHotkey, modKey } from '@/hooks/useHotkey'
import { AgentChat } from './AgentChat'
import { useAgentSessions } from './useAgent'

/** 书内各页右下角的 Agent 按钮 + 右侧抽屉（Agent 页本身不显示） */
export function AgentDrawer() {
  const m = useMatch('/books/:bookId/*')
  const bookId = m && /^\d+$/.test(m.params.bookId ?? '') ? Number(m.params.bookId) : 0
  const onAgentPage = !!m && (m.params['*'] ?? '').startsWith('agent')
  const [open, setOpen] = useState(false)
  const sessions = useAgentSessions(bookId)
  const running = (sessions.data ?? []).some((s) => s.running)
  useHotkey('mod+j', () => { if (bookId && !onAgentPage) setOpen((o) => !o) })
  useEffect(() => { setOpen(false) }, [bookId])
  if (!bookId || onAgentPage) return null
  return (
    <>
      <Tip content={`本书 Agent（${modKey}+J）`} side="left">
        <button onClick={() => setOpen(true)} aria-label="打开本书 Agent"
          className="focus-ring fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-pop transition hover:scale-[1.04] active:scale-95 md:bottom-7 md:right-7">
          <Bot className="h-6 w-6" weight="duotone" />
          {running && <span className="absolute -right-0.5 -top-0.5 flex h-3.5 w-3.5"><span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-warning opacity-70" /><span className="relative inline-flex h-3.5 w-3.5 rounded-full bg-warning ring-2 ring-background" /></span>}
        </button>
      </Tip>
      <D.Root open={open} onOpenChange={setOpen}>
        <D.Portal>
          <D.Overlay className="fixed inset-0 z-50 bg-black/20 data-[state=open]:animate-fade-in" />
          <D.Content style={{ width: 'min(520px, 100vw)' }} onOpenAutoFocus={(e) => e.preventDefault()}
            className="fixed inset-y-0 right-0 z-50 flex flex-col bg-background shadow-pop hairline data-[state=open]:animate-slide-in-right focus:outline-none">
            <div className="flex items-center gap-2 border-b px-4 py-3">
              <Bot className="h-[18px] w-[18px] text-primary" weight="duotone" />
              <D.Title className="flex-1 text-[14.5px] font-semibold">本书 Agent</D.Title>
              <D.Description className="sr-only">和本书的专属 Agent 对话</D.Description>
              <Link to={`/books/${bookId}/agent`} onClick={() => setOpen(false)} className="flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-muted-foreground hover:bg-muted hover:text-foreground">
                全屏<ArrowUpRight className="h-3 w-3" />
              </Link>
              <D.Close className="focus-ring rounded-md p-1.5 text-muted-foreground hover:bg-muted"><X className="h-4 w-4" /></D.Close>
            </div>
            <div className="min-h-0 flex-1"><AgentChat bookId={bookId} variant="drawer" autoFocus /></div>
          </D.Content>
        </D.Portal>
      </D.Root>
    </>
  )
}
