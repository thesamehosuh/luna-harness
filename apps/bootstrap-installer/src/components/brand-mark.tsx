import { LunaMark } from '../../../../web/src/components/LunaMark'
import { cn } from '../lib/utils'

// Retained bootstrap screens use the same harness mark as the current launcher.
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span className={cn('inline-flex size-14 shrink-0 items-center justify-center', className)} {...props}>
      <LunaMark className="size-full" />
    </span>
  )
}
