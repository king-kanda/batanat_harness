import type * as React from 'react'

import { Badge } from '#/components/ui/badge'
import { cn } from '#/lib/utils'

/**
 * Status is the only thing in this UI that gets colour, so it gets its own
 * component rather than a pile of one-off classes. Everything maps onto three
 * states: fine, worth a look, broken.
 */
export type Tone = 'ok' | 'degraded' | 'down' | 'neutral'

const TONE_CLASS: Record<Tone, string> = {
  ok: 'border-status-ok/30 bg-status-ok/10 text-status-ok',
  degraded: 'border-status-degraded/30 bg-status-degraded/10 text-status-degraded',
  down: 'border-status-down/30 bg-status-down/10 text-status-down',
  neutral: 'border-border bg-muted text-muted-foreground',
}

/** Map any of the API's status strings onto a tone. */
export function toneFor(value: string | null | undefined): Tone {
  switch (value) {
    case 'ok':
    case 'succeeded':
    case 'connected':
    case 'executed':
    case 'sent':
      return 'ok'
    case 'degraded':
    case 'pending':
    case 'limit_exceeded':
    case 'running':
      return 'degraded'
    case 'failing':
    case 'down':
    case 'failed':
    case 'expired':
    case 'error':
    case 'revoked':
      return 'down'
    default:
      return 'neutral'
  }
}

export function StatusBadge({
  tone,
  className,
  children,
  ...props
}: React.ComponentProps<'span'> & { tone: Tone }) {
  return (
    <Badge variant="outline" className={cn(TONE_CLASS[tone], 'font-medium', className)} {...props}>
      {children}
    </Badge>
  )
}

/** A bare dot, for dense rows where a full badge is too heavy. */
export function StatusDot({ tone, className }: { tone: Tone; className?: string }) {
  const colour = {
    ok: 'bg-status-ok',
    degraded: 'bg-status-degraded',
    down: 'bg-status-down',
    neutral: 'bg-muted-foreground/40',
  }[tone]
  return <span className={cn('inline-block size-2 shrink-0 rounded-full', colour, className)} />
}
