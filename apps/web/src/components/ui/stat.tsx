import type * as React from 'react'

import { cn } from '#/lib/utils'

export function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
}: {
  label: string
  value: React.ReactNode
  hint?: string
  tone?: 'neutral' | 'ok' | 'degraded' | 'down'
}) {
  const toneClass = {
    neutral: 'text-ink',
    ok: 'text-status-ok',
    degraded: 'text-status-degraded',
    down: 'text-status-down',
  }[tone]

  return (
    <div className="border-border-subtle bg-surface-raised rounded-lg border p-3">
      <div className="text-ink-faint text-[11px] tracking-wide uppercase">{label}</div>
      <div className={cn('tabular mt-1 text-2xl font-semibold', toneClass)}>{value}</div>
      {hint && <div className="text-ink-faint mt-0.5 text-[11px]">{hint}</div>}
    </div>
  )
}
