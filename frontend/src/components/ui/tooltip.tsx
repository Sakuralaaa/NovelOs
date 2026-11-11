import * as T from '@radix-ui/react-tooltip'
import type { ReactNode } from 'react'

export const TooltipProvider = T.Provider
export function Tip({ content, children, side = 'top' }: { content: ReactNode; children: ReactNode; side?: 'top' | 'right' | 'bottom' | 'left' }) {
  if (!content) return <>{children}</>
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content side={side} sideOffset={6} className="z-[70] max-w-xs rounded-md bg-foreground px-2.5 py-1.5 text-xs leading-snug text-background shadow-pop animate-fade-in">
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  )
}
