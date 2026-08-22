import { cva, type VariantProps } from 'class-variance-authority'
import type * as React from 'react'

import { cn } from '#/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 rounded-md text-xs font-medium whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent',
  {
    variants: {
      variant: {
        primary: 'bg-accent/15 text-accent border border-accent/30 hover:bg-accent/25',
        secondary:
          'border border-border-subtle text-ink-muted hover:text-ink hover:border-ink-faint',
        danger:
          'border border-status-down/30 text-status-down hover:bg-status-down/10',
        ghost: 'text-ink-muted hover:text-ink',
      },
      size: {
        sm: 'h-7 px-2.5',
        md: 'h-8 px-3',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'sm' },
  },
)

function Button({
  className,
  variant,
  size,
  ...props
}: React.ComponentProps<'button'> & VariantProps<typeof buttonVariants>) {
  return (
    <button
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  )
}

export { Button, buttonVariants }
