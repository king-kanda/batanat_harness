import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Loader2, RefreshCw, TriangleAlert } from 'lucide-react'

import { StatusBadge } from '#/components/status-badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Empty } from '#/components/ui/empty'
import { Stat } from '#/components/ui/stat'
import { API_BASE_URL, ApiError, api } from '#/lib/api'

export const Route = createFileRoute('/')({ component: Dashboard })

const HEALTH_TONE = { ok: 'ok', degraded: 'degraded', failing: 'down' } as const

function Dashboard() {
  const queryClient = useQueryClient()
  const dashboard = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
    refetchInterval: 30_000,
  })

  const syncTenders = useMutation({
    mutationFn: api.sync.tenders,
    onSuccess: () => queryClient.invalidateQueries(),
  })

  if (dashboard.isPending) {
    return <Card><CardContent className="text-muted-foreground/80 text-xs">Loading…</CardContent></Card>
  }

  if (dashboard.isError) {
    const message =
      dashboard.error instanceof ApiError ? dashboard.error.message : 'Unexpected error'
    return (
      <Card>
        <CardContent className="space-y-2">
          <p className="text-status-down flex items-center gap-2 text-sm">
            <TriangleAlert className="size-4" aria-hidden /> {message}
          </p>
          <pre className="bg-muted border-border text-muted-foreground overflow-x-auto rounded border p-3 font-mono text-[11px]">
            cd apps/api && uv run fastapi dev src/batanat_api/main.py
          </pre>
          <p className="text-muted-foreground/80 text-[11px]">API expected at {API_BASE_URL}</p>
        </CardContent>
      </Card>
    )
  }

  const data = dashboard.data
  // Fields with server-side defaults are optional in the generated contract.
  const needsAttention = data.connections_needing_attention ?? []

  return (
    <div className="space-y-4">
      {(data.kill_switch || data.crm_dry_run) && (
        <div className="border-status-degraded/30 bg-status-degraded/10 text-status-degraded flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-xs">
          <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
          {data.kill_switch && <span>Kill switch engaged — no agent runs will start.</span>}
          {data.crm_dry_run && (
            <span>CRM dry run — approved writes are logged, not sent to Zoho.</span>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Opportunities" value={data.opportunities_today} hint="last 24h" />
        <Stat label="Tenders" value={data.tenders_today} hint="last 24h" />
        <Stat
          label="Approvals"
          value={data.pending_approvals}
          hint="awaiting you"
          tone={data.pending_approvals > 0 ? 'degraded' : 'neutral'}
        />
        <Stat
          label="Connections"
          value={`${data.connections_healthy}/${data.connections_total}`}
          hint={
            needsAttention.length ? needsAttention.join(', ') : 'all healthy'
          }
          tone={needsAttention.length ? 'down' : 'ok'}
        />
      </div>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Tender sources</CardTitle>
            <CardDescription>
              Which sites are answering. A degraded source falls back to search.
            </CardDescription>
          </div>
          <Button onClick={() => syncTenders.mutate()} disabled={syncTenders.isPending}>
            {syncTenders.isPending ? (
              <Loader2 className="size-3 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="size-3" aria-hidden />
            )}
            Run now
          </Button>
        </CardHeader>
        <div>
          {data.sources?.length ? (
            data.sources.map((source) => (
              <div
                key={source.key}
                className="border-border flex items-baseline gap-3 border-b px-4 py-2 last:border-b-0"
              >
                <span className="text-foreground w-24 shrink-0 font-mono text-xs">{source.key}</span>
                <StatusBadge tone={HEALTH_TONE[source.health]}>{source.health}</StatusBadge>
                <span className="text-muted-foreground/80 truncate text-[11px]" title={source.last_error ?? ''}>
                  {source.last_error ?? source.name}
                </span>
              </div>
            ))
          ) : (
            <Empty title="No sources configured">Run `make seed` to load them.</Empty>
          )}
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Next scheduled runs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 text-xs">
            {data.next_runs?.length ? (
              data.next_runs.map((job) => (
                <div key={job.id} className="text-muted-foreground flex justify-between">
                  <span className="font-mono">{job.id}</span>
                  <span className="tabular">{job.next_run_at}</span>
                </div>
              ))
            ) : (
              <p className="text-muted-foreground/80">
                The scheduler is off. Set <span className="font-mono">ENABLE_SCHEDULER=true</span>{' '}
                to run tenders at 11:00 and 17:00 EAT.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Recent activity</CardTitle>
            <Link to="/activity" className="text-muted-foreground/80 text-xs hover:underline">
              All runs
            </Link>
          </CardHeader>
          <div>
            {data.recent_runs?.length ? (
              data.recent_runs.map((run) => (
                <Link
                  key={run.id}
                  to="/activity"
                  className="border-border hover:bg-muted flex items-baseline gap-2 border-b px-4 py-2 text-xs last:border-b-0"
                >
                  <span className="text-muted-foreground w-28 shrink-0 font-mono">
                    {run.trigger_type}
                  </span>
                  <StatusBadge tone={run.status === 'succeeded' ? 'ok' : 'down'}>{run.status}</StatusBadge>
                  <span className="text-muted-foreground/80 truncate">{run.summary ?? '—'}</span>
                </Link>
              ))
            ) : (
              <Empty title="No runs yet">
                Runs appear when an email arrives, the tender cron fires, or you use chat.
              </Empty>
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
