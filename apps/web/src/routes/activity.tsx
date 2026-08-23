import type { RunView, ToolCallView } from '@batanat/schema'
import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '#/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Empty } from '#/components/ui/empty'
import { api } from '#/lib/api'

export const Route = createFileRoute('/activity')({ component: Activity })

function Activity() {
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs.list })
  const policy = useQuery({ queryKey: ['policy'], queryFn: api.policy })

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Capability policy</CardTitle>
            <CardDescription>
              What each trigger may do. Decided from the trigger alone, before the model runs.
            </CardDescription>
          </div>
        </CardHeader>
        <div>
          {policy.data &&
            Object.entries(policy.data).map(([trigger, entry]) => (
              <div
                key={trigger}
                className="border-border-subtle flex flex-wrap items-baseline gap-2 border-b px-4 py-2 text-xs last:border-b-0"
              >
                <span className="text-ink w-36 shrink-0 font-mono">{trigger}</span>
                <Badge
                  variant={
                    entry.trust === 'trusted'
                      ? 'ok'
                      : entry.trust === 'untrusted'
                        ? 'degraded'
                        : 'neutral'
                  }
                >
                  {entry.trust}
                </Badge>
                <span className="text-ink-faint font-mono">
                  {entry.tools.length ? entry.tools.join(' · ') : 'no tools'}
                </span>
              </div>
            ))}
        </div>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Runs</CardTitle>
            <CardDescription>Expand a run to see every tool call it made.</CardDescription>
          </div>
        </CardHeader>
        <div>
          {runs.isPending && <CardContent className="text-ink-faint text-xs">Loading…</CardContent>}
          {runs.data?.length === 0 && (
            <Empty title="No runs yet">
              A run is recorded whenever an email arrives, the tender cron fires, or you send a
              chat message.
            </Empty>
          )}
          {runs.data?.map((run) => <RunRow key={run.id} run={run} />)}
        </div>
      </Card>
    </div>
  )
}

function RunRow({ run }: { run: RunView }) {
  const [open, setOpen] = useState(false)
  const detail = useQuery({
    queryKey: ['run', run.id],
    queryFn: () => api.runs.get(run.id),
    enabled: open,
  })

  return (
    <div className="border-border-subtle border-b last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="hover:bg-surface flex w-full items-baseline gap-2 px-4 py-2.5 text-left text-xs"
      >
        {open ? (
          <ChevronDown className="text-ink-faint size-3.5 shrink-0 translate-y-0.5" aria-hidden />
        ) : (
          <ChevronRight className="text-ink-faint size-3.5 shrink-0 translate-y-0.5" aria-hidden />
        )}
        <span className="text-ink w-32 shrink-0 font-mono">{run.trigger_type}</span>
        <Badge
          variant={
            run.status === 'succeeded' ? 'ok' : run.status === 'limit_exceeded' ? 'degraded' : 'down'
          }
        >
          {run.status}
        </Badge>
        <span className="text-ink-faint tabular w-16 shrink-0 text-right">
          {run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : '—'}
        </span>
        <span className="text-ink-faint tabular w-20 shrink-0 text-right">
          {(run.token_cost ?? 0).toLocaleString()} tok
        </span>
        <span className="text-ink-muted truncate">{run.summary ?? run.error ?? ''}</span>
        <span className="text-ink-faint tabular ml-auto shrink-0">
          {new Date(run.started_at).toLocaleString()}
        </span>
      </button>

      {open && (
        <div className="bg-surface border-border-subtle border-t px-4 py-3">
          <dl className="text-ink-faint mb-3 flex flex-wrap gap-x-5 gap-y-1 text-[11px]">
            <span>
              trust <span className="text-ink-muted font-mono">{run.trust_level}</span>
            </span>
            <span>
              iterations <span className="text-ink-muted tabular">{run.iterations}</span>
            </span>
            {detail.data?.skill_version != null && (
              <span>
                Skill.MD <span className="text-ink-muted">v{detail.data.skill_version}</span>
              </span>
            )}
            <span>
              run <span className="text-ink-muted font-mono">{run.id.slice(0, 8)}</span>
            </span>
          </dl>

          <div className="mb-3">
            <div className="text-ink-faint mb-1 text-[11px]">Tools bound to this run</div>
            <div className="flex flex-wrap gap-1">
              {run.bound_tools?.length ? (
                run.bound_tools.map((tool) => (
                  <span
                    key={tool}
                    className="border-border-subtle text-ink-muted rounded border px-1.5 py-0.5 font-mono text-[10px]"
                  >
                    {tool}
                  </span>
                ))
              ) : (
                <span className="text-ink-faint text-[11px]">none — direct execution</span>
              )}
            </div>
          </div>

          {detail.isPending && <p className="text-ink-faint text-xs">Loading tool calls…</p>}
          {detail.data?.tool_calls?.length === 0 && (
            <p className="text-ink-faint text-xs">No tool calls in this run.</p>
          )}
          <div className="space-y-2">
            {detail.data?.tool_calls?.map((call) => <ToolCall key={call.sequence} call={call} />)}
          </div>
        </div>
      )}
    </div>
  )
}

function ToolCall({ call }: { call: ToolCallView }) {
  return (
    <div className="border-border-subtle bg-surface-raised rounded border p-2.5">
      <div className="flex items-baseline gap-2 text-[11px]">
        <span className="text-ink-faint tabular">#{call.sequence}</span>
        <span className="text-ink font-mono">{call.tool_name}</span>
        <Badge variant={call.error ? 'down' : 'ok'}>{call.error ? 'failed' : 'ok'}</Badge>
        <span className="text-ink-faint tabular ml-auto">{call.duration_ms ?? 0} ms</span>
      </div>
      <pre className="text-ink-muted mt-1.5 overflow-x-auto font-mono text-[10px] whitespace-pre-wrap">
        {JSON.stringify(call.arguments, null, 2)}
      </pre>
      {call.error ? (
        <p className="text-status-down mt-1 font-mono text-[10px]">{call.error}</p>
      ) : (
        <pre className="text-ink-faint mt-1 max-h-40 overflow-auto font-mono text-[10px] whitespace-pre-wrap">
          {JSON.stringify(call.result, null, 2)}
        </pre>
      )}
    </div>
  )
}
