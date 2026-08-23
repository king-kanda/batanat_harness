import { StatusBadge } from '#/components/status-badge'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { Empty } from '#/components/ui/empty'
import { api } from '#/lib/api'
import { cn } from '#/lib/utils'

export const Route = createFileRoute('/results')({ component: Results })

const CATEGORY_TONE = {
  opportunity: 'ok',
  client: 'ok',
  supplier: 'neutral',
  administrative: 'neutral',
  spam: 'down',
  not_relevant: 'neutral',
} as const

function Results() {
  return (
    <Tabs defaultValue="emails" className="space-y-4">
      <TabsList>
        <TabsTrigger value="emails">Opportunities</TabsTrigger>
        <TabsTrigger value="tenders">Tenders</TabsTrigger>
      </TabsList>
      <TabsContent value="emails">
        <Emails />
      </TabsContent>
      <TabsContent value="tenders">
        <Tenders />
      </TabsContent>
    </Tabs>
  )
}

function useVote(subjectType: 'email' | 'tender') {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, rating }: { id: string; rating: 'up' | 'down' }) =>
      api.results.feedback({ subject_type: subjectType, subject_id: id, rating }),
    onSuccess: () => queryClient.invalidateQueries(),
  })
}

function Vote({
  current,
  onVote,
}: {
  current: string | null | undefined
  onVote: (rating: 'up' | 'down') => void
}) {
  return (
    <div className="flex shrink-0 items-center gap-1">
      <button
        type="button"
        aria-label="Correct"
        onClick={() => onVote('up')}
        className={cn(
          'rounded p-1 transition-colors',
          current === 'up' ? 'text-status-ok' : 'text-muted-foreground/80 hover:text-foreground',
        )}
      >
        <ThumbsUp className="size-3.5" aria-hidden />
      </button>
      <button
        type="button"
        aria-label="Wrong"
        onClick={() => onVote('down')}
        className={cn(
          'rounded p-1 transition-colors',
          current === 'down' ? 'text-status-down' : 'text-muted-foreground/80 hover:text-foreground',
        )}
      >
        <ThumbsDown className="size-3.5" aria-hidden />
      </button>
    </div>
  )
}

function Emails() {
  const emails = useQuery({ queryKey: ['emails'], queryFn: api.results.emails })
  const vote = useVote('email')

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Classified email</CardTitle>
          <CardDescription>
            👍/👎 becomes a labelled test case — run <span className="font-mono">make eval</span>{' '}
            to see precision and recall.
          </CardDescription>
        </div>
      </CardHeader>

      {emails.isPending && <CardContent className="text-muted-foreground/80 text-xs">Loading…</CardContent>}
      {emails.data?.length === 0 && (
        <Empty title="No email classified yet">
          Connect Gmail on the Connections page. New mail is classified within a minute of
          arriving; you can also press Sync now.
        </Empty>
      )}

      <div>
        {emails.data?.map((email) => (
          <div key={email.id} className="border-border border-b p-4 last:border-b-0">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-2">
                  {email.category && (
                    <StatusBadge tone={CATEGORY_TONE[email.category] ?? 'neutral'}>
                      {email.category}
                    </StatusBadge>
                  )}
                  {email.priority && (
                    <StatusBadge tone={email.priority === 'high' ? 'down' : 'neutral'}>
                      {email.priority}
                    </StatusBadge>
                  )}
                  {email.confidence != null && (
                    <span className="text-muted-foreground/80 tabular text-[11px]">
                      {(email.confidence * 100).toFixed(0)}% confident
                    </span>
                  )}
                </div>
                <p className="text-foreground mt-1.5 text-sm">{email.subject ?? '(no subject)'}</p>
                <p className="text-muted-foreground/80 text-[11px]">
                  {email.from_name ?? email.from_address}
                  {email.received_at && ` · ${new Date(email.received_at).toLocaleString()}`}
                </p>
                {email.reasoning && (
                  <p className="text-muted-foreground mt-2 text-xs italic">{email.reasoning}</p>
                )}
                {email.suggested_action && (
                  <p className="text-primary mt-1 text-xs">→ {email.suggested_action}</p>
                )}
              </div>
              <Vote
                current={email.feedback}
                onVote={(rating) => vote.mutate({ id: email.id, rating })}
              />
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

function Tenders() {
  const [includeClosed, setIncludeClosed] = useState(false)
  const tenders = useQuery({
    queryKey: ['tenders', includeClosed],
    queryFn: () => api.results.tenders(includeClosed),
  })
  const vote = useVote('tender')

  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Tenders</CardTitle>
          <CardDescription>Soonest deadline first. Every row links to its source.</CardDescription>
        </div>
        <label className="text-muted-foreground/80 flex items-center gap-1.5 text-[11px]">
          <input
            type="checkbox"
            checked={includeClosed}
            onChange={(e) => setIncludeClosed(e.target.checked)}
          />
          include closed
        </label>
      </CardHeader>

      {tenders.isPending && <CardContent className="text-muted-foreground/80 text-xs">Loading…</CardContent>}
      {tenders.data?.length === 0 && (
        <Empty title="No tenders yet">
          The tender sweep runs at 11:00 and 17:00 EAT. Press “Run now” on the dashboard to do it
          immediately.
        </Empty>
      )}

      <div>
        {tenders.data?.map((tender) => {
          const days = tender.closing_date
            ? Math.ceil(
                (new Date(tender.closing_date).getTime() - Date.now()) / 86_400_000,
              )
            : null

          return (
            <div
              key={tender.id}
              className="border-border flex items-start gap-3 border-b px-4 py-2.5 last:border-b-0"
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-muted-foreground font-mono text-[11px]">
                    {tender.reference_no ?? '—'}
                  </span>
                  <span className="text-muted-foreground/80 text-[11px]">{tender.source}</span>
                  {tender.is_closed ? (
                    <StatusBadge tone="neutral">closed</StatusBadge>
                  ) : days != null && days <= 14 ? (
                    <StatusBadge tone={days <= 5 ? 'down' : 'degraded'}>{days}d left</StatusBadge>
                  ) : null}
                </div>
                <a
                  href={tender.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-foreground hover:text-primary mt-0.5 inline-flex items-start gap-1 text-sm"
                >
                  {tender.title}
                  <ExternalLink className="mt-0.5 size-3 shrink-0" aria-hidden />
                </a>
                <p className="text-muted-foreground/80 text-[11px]">
                  {tender.entity}
                  {tender.closing_date &&
                    ` · closes ${new Date(tender.closing_date).toLocaleDateString()}`}
                  {tender.estimated_value != null &&
                    tender.currency &&
                    ` · ${tender.currency} ${tender.estimated_value.toLocaleString()}`}
                </p>
              </div>
              <Vote
                current={tender.feedback}
                onVote={(rating) => vote.mutate({ id: tender.id, rating })}
              />
            </div>
          )
        })}
      </div>
    </Card>
  )
}
