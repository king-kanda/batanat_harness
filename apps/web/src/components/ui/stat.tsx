import type * as React from 'react'

import { Card } from '#/components/ui/card'
import { cn } from '#/lib/utils'

const TONE = {
  neutral: 'text-foreground',
  ok: 'text-status-ok',
  degraded: 'text-status-degraded',
  down: 'text-status-down',
} as const

export function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: React.ReactNode
  hint?: string
  tone?: keyof typeof TONE
}) {
  return (
    <Card className="gap-0 py-4">
      <div className="px-4">
        <div className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
          {label}
        </div>
        <div className={cn('tabular mt-1 text-2xl font-bold tracking-tight', TONE[tone])}>
          {value}
        </div>
        {hint && <div className="text-muted-foreground mt-0.5 truncate text-[11px]">{hint}</div>}
      </div>
    </Card>
  )
}
