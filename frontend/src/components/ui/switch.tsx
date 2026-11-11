import * as Sw from '@radix-ui/react-switch'
import { cn } from '@/lib/utils'

export function Switch({ checked, onCheckedChange, className, id }: { checked: boolean; onCheckedChange: (v: boolean) => void; className?: string; id?: string }) {
  return (
    <Sw.Root
      id={id}
      checked={checked}
      onCheckedChange={onCheckedChange}
      className={cn('focus-ring relative h-[22px] w-[38px] shrink-0 rounded-full bg-input transition-colors data-[state=checked]:bg-primary', className)}
    >
      <Sw.Thumb className="block h-[18px] w-[18px] translate-x-[2px] rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
    </Sw.Root>
  )
}
