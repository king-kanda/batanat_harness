import type { ServiceHealth, ServiceStatus } from '@batanat/schema'
import { CircleAlert, CircleCheck, CircleX } from 'lucide-react'

import { cn } from '#/lib/utils'

const STATUS_ICON: Record<ServiceStatus, typeof CircleCheck> = {
  ok: CircleCheck,
  degraded: CircleAlert,
  down: CircleX,
}

const STATUS_COLOR: Record<ServiceStatus, string> = {
  ok: 'text-status-ok',
  degraded: 'text-status-degraded',
  down: 'text-status-down',
}

/** One dependency: name, state, how long the probe took, and what it said. */
export function ServiceRow({ service }: { service: ServiceHealth }) {
  const Icon = STATUS_ICON[service.status]

  return (
    <div className="border-border-subtle flex items-baseline gap-3 border-b px-4 py-2.5 last:border-b-0">
      <Icon
        className={cn('size-4 shrink-0 translate-y-0.5', STATUS_COLOR[service.status])}
        aria-hidden
      />
      <span className="text-ink w-24 shrink-0 font-mono text-sm">{service.name}</span>
      <span className={cn('w-20 shrink-0 text-xs font-medium', STATUS_COLOR[service.status])}>
        {service.status}
      </span>
      <span className="text-ink-faint tabular w-20 shrink-0 text-right text-xs">
        {service.latency_ms == null ? '—' : `${service.latency_ms.toFixed(0)} ms`}
      </span>
      <span className="text-ink-muted truncate text-xs" title={service.detail ?? undefined}>
        {service.detail ?? '—'}
      </span>
    </div>
  )
}
