import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'

import { cn } from '#/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap',
  {
    variants: {
      variant: {
        neutral: 'border-border-subtle text-ink-muted',
        ok: 'border-status-ok/30 text-status-ok bg-status-ok/10',
        degraded: 'border-status-degraded/30 text-status-degraded bg-status-degraded/10',
        down: 'border-status-down/30 text-status-down bg-status-down/10',
      },
    },
    defaultVariants: { variant: 'neutral' },
  },
)

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<'span'> & VariantProps<typeof badgeVariants>) {
  return (
    <span data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
