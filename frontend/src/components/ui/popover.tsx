import * as React from 'react'
import * as P from '@radix-ui/react-popover'
import { cn } from '@/lib/utils'

export const Popover = P.Root
export const PopoverTrigger = P.Trigger
export const PopoverAnchor = P.Anchor
export const PopoverClose = P.Close

/** 轻量浮层：与 Tip 同一套圆角、阴影；触屏上点按打开 */
export const PopoverContent = React.forwardRef<HTMLDivElement, React.ComponentProps<typeof P.Content>>(
  ({ className, sideOffset = 8, align = 'start', collisionPadding = 12, ...p }, ref) => (
    <P.Portal>
      <P.Content ref={ref} sideOffset={sideOffset} align={align} collisionPadding={collisionPadding}
        className={cn('z-[60] w-[320px] max-w-[calc(100vw-24px)] rounded-xl bg-popover p-3.5 text-[13px] shadow-pop hairline animate-fade-in focus:outline-none', className)} {...p} />
    </P.Portal>
  ),
)
PopoverContent.displayName = 'PopoverContent'
