import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Loader2, RefreshCw, TriangleAlert } from 'lucide-react'

import { ServiceRow } from '#/components/service-row'
import { Badge } from '#/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { API_BASE_URL, ApiError, api } from '#/lib/api'

export const Route = createFileRoute('/')({ component: Dashboard })

function Dashboard() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: api.health,
    refetchInterval: 10_000,
  })

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>System health</CardTitle>
            <CardDescription>
              Live probe of every backing service, refreshed every 10s.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {health.isFetching && (
              <Loader2 className="text-ink-faint size-3.5 animate-spin" aria-label="refreshing" />
            )}
            {health.data && (
              <Badge variant={health.data.status}>{health.data.status.toUpperCase()}</Badge>
            )}
          </div>
        </CardHeader>

        {health.isPending && (
          <CardContent className="text-ink-faint p-4 text-xs">Probing services…</CardContent>
        )}

        {health.isError && <UnreachablePanel error={health.error} />}

        {health.data && (
          <>
            <div>
              {health.data.services.map((service) => (
                <ServiceRow key={service.name} service={service} />
              ))}
            </div>
            <div className="border-border-subtle text-ink-faint flex flex-wrap items-center gap-x-4 gap-y-1 border-t px-4 py-2.5 text-[11px]">
              <span>
                api <span className="text-ink-muted font-mono">v{health.data.version}</span>
              </span>
              <span>
                env <span className="text-ink-muted font-mono">{health.data.app_env}</span>
              </span>
              {health.data.run_id && (
                <span>
                  run <span className="text-ink-muted font-mono">{health.data.run_id.slice(0, 12)}</span>
                </span>
              )}
              <span className="tabular">
                checked {new Date(health.data.checked_at).toLocaleTimeString()}
              </span>
              <button
                type="button"
                onClick={() => health.refetch()}
                className="text-ink-muted hover:text-ink ml-auto inline-flex items-center gap-1.5 hover:underline"
              >
                <RefreshCw className="size-3" aria-hidden />
                Refresh
              </button>
            </div>
          </>
        )}
      </Card>

      <NextUpPanel />
    </div>
  )
}

function UnreachablePanel({ error }: { error: Error }) {
  const message = error instanceof ApiError ? error.message : 'Unexpected error'

  return (
    <CardContent className="space-y-3">
      <div className="text-status-down flex items-start gap-2 text-sm">
        <TriangleAlert className="size-4 shrink-0 translate-y-0.5" aria-hidden />
        <div>
          <p className="font-medium">{message}</p>
          <p className="text-ink-muted mt-1 text-xs">
            The web app is running but the API is not answering at{' '}
            <span className="font-mono">{API_BASE_URL}</span>.
          </p>
        </div>
      </div>
      <pre className="bg-surface text-ink-muted border-border-subtle overflow-x-auto rounded border p-3 font-mono text-[11px]">
        cd apps/api && uv run fastapi dev src/batanat_api/main.py
      </pre>
    </CardContent>
  )
}

/** Phase 0 is scaffolding only — say so, rather than showing a blank console. */
function NextUpPanel() {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Nothing else here yet</CardTitle>
          <CardDescription>Phase 0 ships the scaffold and the contracts.</CardDescription>
        </div>
        <Badge>phase 0</Badge>
      </CardHeader>
      <CardContent className="text-ink-muted space-y-1.5 text-xs">
        <p>
          Opportunities, tenders, approvals and the run timeline appear here as later phases land.
          Connections come next, in phase 2 — until Gmail and Zoho are linked there is nothing for
          the agent to read.
        </p>
      </CardContent>
    </Card>
  )
}
