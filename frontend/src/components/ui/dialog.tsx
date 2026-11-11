import * as React from 'react'
import * as D from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({ className, children, title, desc, footer, wide }: {
  className?: string; children?: React.ReactNode; title: React.ReactNode; desc?: React.ReactNode; footer?: React.ReactNode; wide?: boolean
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px] data-[state=open]:animate-fade-in" />
      <D.Content
        className={cn(
          'fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-2rem)] -translate-x-1/2 rounded-xl bg-popover shadow-pop hairline data-[state=open]:animate-zoom-in focus:outline-none',
          wide ? 'max-w-2xl' : 'max-w-md',
          className,
        )}
      >
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <div>
            <D.Title className="text-base font-semibold tracking-tight">{title}</D.Title>
            {desc ? <D.Description className="mt-1 text-[13px] text-muted-foreground">{desc}</D.Description> : <D.Description className="sr-only">对话框</D.Description>}
          </div>
          <D.Close className="focus-ring -mr-2 rounded-md p-1.5 text-muted-foreground hover:bg-muted"><X className="h-4 w-4" /></D.Close>
        </div>
        <div className="max-h-[65vh] overflow-y-auto px-6 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t px-6 py-3.5">{footer}</div>}
      </D.Content>
    </D.Portal>
  )
}

/** 右侧抽屉 */
export function Sheet({ open, onOpenChange, title, desc, children, footer, width = 520 }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: React.ReactNode; desc?: React.ReactNode; children: React.ReactNode; footer?: React.ReactNode; width?: number
}) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-50 bg-black/25 backdrop-blur-[1px] data-[state=open]:animate-fade-in" />
        <D.Content
          style={{ width: `min(${width}px, 100vw)` }}
          className="fixed inset-y-0 right-0 z-50 flex flex-col bg-popover shadow-pop hairline data-[state=open]:animate-slide-in-right focus:outline-none"
        >
          <div className="flex items-start justify-between gap-4 border-b px-6 py-4">
            <div>
              <D.Title className="text-base font-semibold tracking-tight">{title}</D.Title>
              {desc ? <D.Description className="mt-0.5 text-[13px] text-muted-foreground">{desc}</D.Description> : <D.Description className="sr-only">抽屉</D.Description>}
            </div>
            <D.Close className="focus-ring -mr-2 rounded-md p-1.5 text-muted-foreground hover:bg-muted"><X className="h-4 w-4" /></D.Close>
          </div>
          <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t px-6 py-3.5">{footer}</div>}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
