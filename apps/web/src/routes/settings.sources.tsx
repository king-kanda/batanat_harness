import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Loader2, RefreshCw, TriangleAlert } from 'lucide-react'

import { StatusBadge, toneFor } from '#/components/status-badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { Empty } from '#/components/ui/empty'
import { api } from '#/lib/api'

export const Route = createFileRoute('/settings/sources')({ component: Sources })

/** Where the tenders come from, whether those sites are answering, and when we next look. */
function Sources() {
  const queryClient = useQueryClient()
  const dashboard = useQuery({
    queryKey: ['dashboard'],
    queryFn: api.dashboard,
    refetchInterval: 60_000,
  })

  const sweep = useMutation({
    mutationFn: api.sync.tenders,
    onSuccess: () => queryClient.invalidateQueries(),
  })

  const data = dashboard.data

  return (
    <div className="space-y-4">
      {(data?.kill_switch || data?.crm_dry_run) && (
        <div className="border-status-degraded/30 bg-status-degraded/10 text-status-degraded flex flex-wrap items-center gap-3 rounded-lg border px-3 py-2 text-xs">
          <TriangleAlert className="size-3.5 shrink-0" aria-hidden />
          {data.kill_switch && <span>Kill switch engaged — no agent runs will start.</span>}
          {data.crm_dry_run && (
            <span>CRM dry run — approved writes are logged, not sent to Zoho.</span>
          )}
        </div>
      )}

      <Tabs defaultValue="sources" className="space-y-4">
      <TabsList>
        <TabsTrigger value="sources">Sources</TabsTrigger>
        <TabsTrigger value="schedule">Schedule</TabsTrigger>
      </TabsList>

      <TabsContent value="sources">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Tender sources</CardTitle>
            <CardDescription>
              Which sites are answering. A degraded source falls back to web search, and the
              report always names what it could not reach.
            </CardDescription>
          </div>
          <Button onClick={() => sweep.mutate()} disabled={sweep.isPending} size="sm">
            {sweep.isPending ? (
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
            ) : (
              <RefreshCw className="size-3.5" aria-hidden />
            )}
            Run sweep now
          </Button>
        </CardHeader>

        <div>
          {data?.sources?.length ? (
            data.sources.map((source) => (
              <div
                key={source.key}
                className="border-border flex items-baseline gap-3 border-b px-6 py-2.5 last:border-b-0"
              >
                <span className="w-24 shrink-0 font-mono text-xs">{source.key}</span>
                <StatusBadge tone={toneFor(source.health)}>{source.health}</StatusBadge>
                <span
                  className="text-muted-foreground truncate text-[11px]"
                  title={source.last_error ?? ''}
                >
                  {source.last_error ?? source.name}
                </span>
              </div>
            ))
          ) : (
            <Empty title="No sources configured">Run `make seed` to load them.</Empty>
          )}
        </div>
      </Card>
      </TabsContent>

      <TabsContent value="schedule">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Schedule</CardTitle>
            <CardDescription>All times are Africa/Nairobi.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-1.5 text-xs">
          {data?.next_runs?.length ? (
            data.next_runs.map((job) => (
              <div key={job.id} className="text-muted-foreground flex justify-between">
                <span className="font-mono">{job.id}</span>
                <span className="tabular">{job.next_run_at}</span>
              </div>
            ))
          ) : (
            <p className="text-muted-foreground">
              The scheduler is off. Set <span className="font-mono">ENABLE_SCHEDULER=true</span> to
              sweep tenders at 11:00 and 17:00, and run maintenance at 02:00.
            </p>
          )}
        </CardContent>
      </Card>
      </TabsContent>
      </Tabs>
    </div>
  )
}
