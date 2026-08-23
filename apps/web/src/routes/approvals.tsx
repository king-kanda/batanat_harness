import type { ApprovalView } from '@batanat/schema'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { Check, Loader2, Pencil, X } from 'lucide-react'
import { useState } from 'react'

import { StatusBadge } from '#/components/status-badge'
import { Button } from '#/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Empty } from '#/components/ui/empty'
import { api } from '#/lib/api'

export const Route = createFileRoute('/approvals')({ component: Approvals })

function Approvals() {
  const approvals = useQuery({ queryKey: ['approvals'], queryFn: api.approvals.list })
  const [error, setError] = useState<string | null>(null)

  const pending = approvals.data?.filter((a) => a.status === 'pending') ?? []
  const decided = approvals.data?.filter((a) => a.status !== 'pending') ?? []

  return (
    <div className="space-y-4">
      {error && (
        <div className="border-status-down/30 bg-status-down/10 text-status-down rounded-lg border px-3 py-2 text-xs">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <div>
            <CardTitle>Pending approvals</CardTitle>
            <CardDescription>
              Nothing reaches Zoho until you approve it here. Execution is direct — no model is
              involved once you decide.
            </CardDescription>
          </div>
          {pending.length > 0 && <StatusBadge tone="degraded">{pending.length} waiting</StatusBadge>}
        </CardHeader>

        {approvals.isPending && (
          <CardContent className="text-muted-foreground/80 text-xs">Loading…</CardContent>
        )}
        {approvals.data && pending.length === 0 && (
          <Empty title="Nothing waiting">
            When the agent finds something worth recording in the CRM, the proposed write appears
            here with a field-level diff. It expires after 48 hours if you do not decide.
          </Empty>
        )}
        <div>
          {pending.map((approval) => (
            <ApprovalRow key={approval.id} approval={approval} onError={setError} />
          ))}
        </div>
      </Card>

      {decided.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Decided</CardTitle>
          </CardHeader>
          <div>
            {decided.map((approval) => (
              <div
                key={approval.id}
                className="border-border flex items-baseline gap-2 border-b px-4 py-2 text-xs last:border-b-0"
              >
                <span className="text-foreground w-20 shrink-0 font-mono">{approval.module}</span>
                <StatusBadge
                  tone={
                    approval.status === 'executed'
                      ? 'ok'
                      : approval.status === 'rejected' || approval.status === 'expired'
                        ? 'neutral'
                        : 'down'
                  }
                >
                  {approval.status}
                </StatusBadge>
                <span className="text-muted-foreground/80 truncate">{approval.rationale}</span>
                <span className="text-muted-foreground/80 tabular ml-auto shrink-0">
                  {new Date(approval.created_at).toLocaleDateString()}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}

function ApprovalRow({
  approval,
  onError,
}: {
  approval: ApprovalView
  onError: (message: string | null) => void
}) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [payload, setPayload] = useState(() => JSON.stringify(approval.proposed_payload, null, 2))

  const settle = () => {
    onError(null)
    queryClient.invalidateQueries()
  }
  const fail = (e: Error) => onError(e.message)

  const approve = useMutation({
    mutationFn: (edited?: Record<string, unknown>) => api.approvals.approve(approval.id, edited),
    onSuccess: settle,
    onError: fail,
  })
  const reject = useMutation({
    mutationFn: () => api.approvals.reject(approval.id),
    onSuccess: settle,
    onError: fail,
  })

  const busy = approve.isPending || reject.isPending
  const urgent = approval.hours_remaining < 6

  return (
    <div className="border-border border-b p-4 last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-foreground text-sm font-medium">
          {approval.operation} {approval.module}
        </span>
        <StatusBadge tone={urgent ? 'down' : 'neutral'}>
          {approval.hours_remaining > 0
            ? `${Math.round(approval.hours_remaining)}h left`
            : 'expiring'}
        </StatusBadge>
      </div>

      {approval.rationale && (
        <p className="text-muted-foreground mt-1 text-xs">{approval.rationale}</p>
      )}

      <table className="mt-3 w-full text-xs">
        <thead>
          <tr className="text-muted-foreground/80 text-left text-[11px]">
            <th className="w-40 pb-1 font-normal">Field</th>
            <th className="w-1/3 pb-1 font-normal">Current</th>
            <th className="pb-1 font-normal">Proposed</th>
          </tr>
        </thead>
        <tbody>
          {approval.diff.map((entry) => (
            <tr key={entry.field} className="border-border border-t align-top">
              <td className="text-muted-foreground py-1.5 font-mono">{entry.field}</td>
              <td className="text-muted-foreground/80 py-1.5">
                {entry.current == null ? <span className="italic">empty</span> : String(entry.current)}
              </td>
              <td className="text-status-ok py-1.5">{String(entry.proposed ?? '')}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {editing && (
        <textarea
          value={payload}
          onChange={(e) => setPayload(e.target.value)}
          rows={8}
          spellCheck={false}
          className="bg-muted border-border text-foreground mt-3 w-full rounded border p-2 font-mono text-[11px]"
        />
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          variant="default"
          disabled={busy}
          onClick={() => {
            if (!editing) return approve.mutate(undefined)
            try {
              approve.mutate(JSON.parse(payload))
            } catch {
              onError('The edited payload is not valid JSON.')
            }
          }}
        >
          {busy ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Check className="size-3" aria-hidden />}
          {editing ? 'Approve with edits' : 'Approve'}
        </Button>
        <Button onClick={() => setEditing((v) => !v)} disabled={busy}>
          <Pencil className="size-3" aria-hidden />
          {editing ? 'Cancel edit' : 'Edit'}
        </Button>
        <Button variant="destructive" onClick={() => reject.mutate()} disabled={busy}>
          <X className="size-3" aria-hidden />
          Reject
        </Button>
      </div>
    </div>
  )
}
