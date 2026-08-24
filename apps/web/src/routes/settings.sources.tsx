import type { TenderSourceView } from '@batanat/schema'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink, Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { StatusBadge, toneFor } from '#/components/status-badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Empty } from '#/components/ui/empty'
import { Input } from '#/components/ui/input'
import { Label } from '#/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { api } from '#/lib/api'
import { humanise } from '#/lib/labels'

export const Route = createFileRoute('/settings/sources')({ component: Sources })

function Sources() {
  const queryClient = useQueryClient()
  const sources = useQuery({ queryKey: ['sources'], queryFn: api.sources.list })
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard })
  const [error, setError] = useState<string | null>(null)

  const sweep = useMutation({
    mutationFn: api.sync.tenders,
    onSuccess: () => queryClient.invalidateQueries(),
    onError: (e: Error) => setError(e.message),
  })

  return (
    <div className="space-y-4">
      {error && (
        <div className="border-status-down/30 bg-status-down/10 text-status-down rounded-lg border px-3 py-2 text-xs">
          {error}
        </div>
      )}

      <Tabs defaultValue="sources" className="space-y-4">
        <TabsList>
          <TabsTrigger value="sources">
            Sources{sources.data?.length ? ` (${sources.data.length})` : ''}
          </TabsTrigger>
          <TabsTrigger value="add">Add a site</TabsTrigger>
          <TabsTrigger value="schedule">Schedule</TabsTrigger>
        </TabsList>

        <TabsContent value="sources">
          <Card className="gap-0 pb-0" data-tour="sources-panel">
            <CardHeader className="flex-wrap gap-2">
              <div className="min-w-0">
                <CardTitle>Tender sources</CardTitle>
                <CardDescription>
                  Which sites are answering. A degraded source falls back to web search, and the
                  report always names what it could not reach.
                </CardDescription>
              </div>
              <Button
                onClick={() => sweep.mutate()}
                disabled={sweep.isPending}
                size="sm"
                className="shrink-0"
              >
                {sweep.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" aria-hidden />
                ) : (
                  <RefreshCw className="size-3.5" aria-hidden />
                )}
                Run sweep now
              </Button>
            </CardHeader>

            {sources.isPending && (
              <CardContent className="text-muted-foreground pb-6 text-xs">Loading…</CardContent>
            )}
            {sources.data?.length === 0 && (
              <Empty title="No sources yet">Run `make seed`, or add a site on the next tab.</Empty>
            )}

            <div className="divide-border divide-y border-t">
              {sources.data?.map((source) => (
                <SourceRow key={source.key} source={source} onError={setError} />
              ))}
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="add">
          <AddSource onError={setError} />
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
              {dashboard.data?.next_runs?.length ? (
                dashboard.data.next_runs.map((job) => (
                  <div
                    key={job.id}
                    className="text-muted-foreground flex flex-wrap justify-between gap-2"
                  >
                    <span className="font-mono">{job.id}</span>
                    <span className="tabular">{job.next_run_at}</span>
                  </div>
                ))
              ) : (
                <div className="text-muted-foreground space-y-2">
                  <p>
                    The scheduler is off, so nothing runs on its own — sweeps and reports only
                    happen when you press a button. Set{' '}
                    <span className="font-mono">ENABLE_SCHEDULER=true</span> and restart the API to
                    turn on:
                  </p>
                  <ul className="space-y-1 pl-4">
                    <li className="list-disc">
                      <span className="font-medium">Tender sweep</span> — 11:00 and 17:00 daily,
                      each followed by a report
                    </li>
                    <li className="list-disc">
                      <span className="font-medium">Weekly digest</span> — 08:00 Monday, looking
                      back 72 hours
                    </li>
                    <li className="list-disc">
                      <span className="font-medium">Maintenance</span> — 02:00 daily: token
                      refresh, Gmail watch renewal, expiring old approvals
                    </li>
                  </ul>
                  <p>
                    Set your report recipients first, or the sweeps will run and have nowhere to
                    deliver.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

/**
 * One source. Stacks on narrow screens rather than pushing the error message
 * off the right edge — these errors are long by nature and are the whole point
 * of the row.
 */
function SourceRow({
  source,
  onError,
}: {
  source: TenderSourceView
  onError: (message: string | null) => void
}) {
  const queryClient = useQueryClient()
  const invalidate = () => {
    onError(null)
    queryClient.invalidateQueries({ queryKey: ['sources'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard'] })
  }

  const toggle = useMutation({
    mutationFn: () => api.sources.update(source.key, { is_enabled: !source.is_enabled }),
    onSuccess: invalidate,
    onError: (e: Error) => onError(e.message),
  })
  const remove = useMutation({
    mutationFn: () => api.sources.remove(source.key),
    onSuccess: invalidate,
    onError: (e: Error) => onError(e.message),
  })

  return (
    <div className="px-4 py-3 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{source.name}</span>
        <StatusBadge tone={source.is_enabled ? toneFor(source.health) : 'neutral'}>
          {source.is_enabled ? humanise(source.health) : 'Off'}
        </StatusBadge>
        {source.is_custom && <StatusBadge tone="neutral">Yours</StatusBadge>}

        <div className="ml-auto flex shrink-0 items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            onClick={() => toggle.mutate()}
            disabled={toggle.isPending}
          >
            {source.is_enabled ? 'Disable' : 'Enable'}
          </Button>
          {source.is_custom && (
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => remove.mutate()}
              disabled={remove.isPending}
              aria-label={`Remove ${source.name}`}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Button>
          )}
        </div>
      </div>

      {source.listing_url && (
        <a
          href={source.listing_url}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground mt-1 inline-flex items-center gap-1 text-xs break-all"
        >
          {source.listing_url}
          <ExternalLink className="size-3 shrink-0" aria-hidden />
        </a>
      )}

      {source.last_error && (
        // wrap, do not truncate: the error is the reason the row exists
        <p className="text-muted-foreground mt-1.5 text-xs leading-relaxed break-words">
          {source.last_error}
        </p>
      )}
    </div>
  )
}

function AddSource({ onError }: { onError: (message: string | null) => void }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [entity, setEntity] = useState('')
  const [added, setAdded] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: () => api.sources.create({ name, listing_url: url, entity: entity || undefined }),
    onSuccess: (source) => {
      onError(null)
      setAdded(source.name)
      setName('')
      setUrl('')
      setEntity('')
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
    onError: (e: Error) => onError(e.message),
  })

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Add a site to the sweep</CardTitle>
          <CardDescription>
            Point it at the page that lists tenders, not the site's home page. The sweep reads
            tables and lists of linked documents; sites that build their listing in JavaScript
            will come back empty, and the row will say so.
          </CardDescription>
        </div>
      </CardHeader>

      <CardContent>
        <form
          className="grid gap-4 sm:max-w-lg"
          onSubmit={(e) => {
            e.preventDefault()
            if (name && url) create.mutate()
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="source-name">Name</Label>
            <Input
              id="source-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="EPRA"
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="source-url">Tender listing URL</Label>
            <Input
              id="source-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.epra.go.ke/tenders/"
              required
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="source-entity">
              Procuring entity <span className="text-muted-foreground">(optional)</span>
            </Label>
            <Input
              id="source-entity"
              value={entity}
              onChange={(e) => setEntity(e.target.value)}
              placeholder="Energy and Petroleum Regulatory Authority"
            />
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={create.isPending || !name || !url}>
              {create.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <Plus className="size-4" aria-hidden />
              )}
              Add source
            </Button>
            {added && (
              <span className="text-status-ok text-xs">
                Added {added}. Run a sweep to see whether it parses.
              </span>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
