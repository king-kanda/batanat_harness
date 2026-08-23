import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink, ThumbsDown, ThumbsUp } from 'lucide-react'
import { useState } from 'react'

import { StatusBadge } from '#/components/status-badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { Empty } from '#/components/ui/empty'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '#/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '#/components/ui/tabs'
import { api } from '#/lib/api'
import { humanise } from '#/lib/labels'
import { cn } from '#/lib/utils'

export const Route = createFileRoute('/opportunities')({ component: Opportunities })

const CATEGORY_TONE = {
  opportunity: 'ok',
  client: 'ok',
  supplier: 'neutral',
  administrative: 'neutral',
  spam: 'down',
  not_relevant: 'neutral',
} as const

function Opportunities() {
  return (
    <Tabs defaultValue="emails" className="space-y-4">
      <TabsList data-tour="opportunities-panel">
        <TabsTrigger value="emails">From email</TabsTrigger>
        <TabsTrigger value="tenders">From tenders</TabsTrigger>
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
    <div className="flex shrink-0 items-center justify-end gap-0.5">
      <button
        type="button"
        aria-label="Classification is right"
        title="Right"
        onClick={() => onVote('up')}
        className={cn(
          'rounded-md p-1 transition-colors',
          current === 'up' ? 'text-status-ok' : 'text-muted-foreground hover:text-foreground',
        )}
      >
        <ThumbsUp className="size-3.5" aria-hidden />
      </button>
      <button
        type="button"
        aria-label="Classification is wrong"
        title="Wrong"
        onClick={() => onVote('down')}
        className={cn(
          'rounded-md p-1 transition-colors',
          current === 'down' ? 'text-status-down' : 'text-muted-foreground hover:text-foreground',
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
    <Card className="gap-0 pb-0">
      <CardHeader>
        <div>
          <CardTitle>Classified email</CardTitle>
          <CardDescription>
            👍/👎 becomes a labelled test case — run <span className="font-mono">make eval</span>{' '}
            to see precision and recall.
          </CardDescription>
        </div>
      </CardHeader>

      {emails.isPending && (
        <CardContent className="text-muted-foreground pb-6 text-xs">Loading…</CardContent>
      )}
      {emails.data?.length === 0 && (
        <Empty title="No email classified yet">
          Connect Gmail on the Connections page. New mail is classified within a minute of
          arriving; you can also press Sync now.
        </Empty>
      )}

      {!!emails.data?.length && (
        <Table>
          {/* Headers exist so the badges explain themselves: without them,
              "opportunity / high / 94%" is three unlabelled values. */}
          <TableHeader>
            <TableRow>
              <TableHead className="w-[8.5rem]">Category</TableHead>
              <TableHead className="w-[6rem]">Priority</TableHead>
              <TableHead className="w-[6.5rem]">Confidence</TableHead>
              <TableHead>Subject &amp; sender</TableHead>
              <TableHead className="w-[7rem]">Received</TableHead>
              <TableHead className="w-[5.5rem] text-right">Correct?</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {emails.data.map((email) => (
              <TableRow key={email.id} className="align-top">
                <TableCell>
                  {email.category ? (
                    <StatusBadge tone={CATEGORY_TONE[email.category] ?? 'neutral'}>
                      {humanise(email.category)}
                    </StatusBadge>
                  ) : (
                    <span className="text-muted-foreground text-xs">unclassified</span>
                  )}
                </TableCell>

                <TableCell>
                  {email.priority ? (
                    <StatusBadge
                      tone={
                        email.priority === 'high'
                          ? 'down'
                          : email.priority === 'medium'
                            ? 'degraded'
                            : 'neutral'
                      }
                    >
                      {humanise(email.priority)}
                    </StatusBadge>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </TableCell>

                <TableCell className="text-muted-foreground tabular text-xs">
                  {email.confidence == null ? '—' : `${(email.confidence * 100).toFixed(0)}%`}
                </TableCell>

                <TableCell className="max-w-md">
                  <div className="text-sm font-medium">{email.subject ?? '(no subject)'}</div>
                  <div className="text-muted-foreground text-xs">
                    {email.from_name ?? email.from_address}
                  </div>
                  {email.reasoning && (
                    <p className="text-muted-foreground mt-1.5 text-xs italic">{email.reasoning}</p>
                  )}
                  {email.suggested_action && (
                    <p className="mt-1 text-xs">→ {email.suggested_action}</p>
                  )}
                </TableCell>

                <TableCell className="text-muted-foreground tabular text-xs whitespace-nowrap">
                  {email.received_at ? new Date(email.received_at).toLocaleDateString() : '—'}
                </TableCell>

                <TableCell>
                  <Vote
                    current={email.feedback}
                    onVote={(rating) => vote.mutate({ id: email.id, rating })}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
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
    <Card className="gap-0 pb-0">
      <CardHeader>
        <div>
          <CardTitle>Tenders</CardTitle>
          <CardDescription>
            Soonest deadline first. Every title links to its source document.
          </CardDescription>
        </div>
        <label className="text-muted-foreground flex items-center gap-1.5 text-xs">
          <input
            type="checkbox"
            checked={includeClosed}
            onChange={(e) => setIncludeClosed(e.target.checked)}
          />
          include closed
        </label>
      </CardHeader>

      {tenders.isPending && (
        <CardContent className="text-muted-foreground pb-6 text-xs">Loading…</CardContent>
      )}
      {tenders.data?.length === 0 && (
        <Empty title="No tenders yet">
          The tender sweep runs at 11:00 and 17:00 EAT. Press “Run sweep now” under Settings →
          Sources &amp; schedule to do it immediately.
        </Empty>
      )}

      {!!tenders.data?.length && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-[10rem]">Reference</TableHead>
              <TableHead className="w-[5.5rem]">Source</TableHead>
              <TableHead>Title &amp; procuring entity</TableHead>
              <TableHead className="w-[8.5rem]">Closing</TableHead>
              <TableHead className="w-[8rem]">Value</TableHead>
              <TableHead className="w-[5.5rem] text-right">Relevant?</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tenders.data.map((tender) => {
              const days = tender.closing_date
                ? Math.ceil((new Date(tender.closing_date).getTime() - Date.now()) / 86_400_000)
                : null

              return (
                <TableRow key={tender.id} className="align-top">
                  <TableCell className="text-muted-foreground font-mono text-xs break-all">
                    {tender.reference_no ?? '—'}
                  </TableCell>

                  <TableCell className="text-muted-foreground text-xs">{tender.source}</TableCell>

                  <TableCell className="max-w-md">
                    <a
                      href={tender.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:text-primary inline-flex items-start gap-1 text-sm font-medium"
                    >
                      {tender.title}
                      <ExternalLink className="mt-0.5 size-3 shrink-0" aria-hidden />
                    </a>
                    <div className="text-muted-foreground text-xs">{tender.entity}</div>
                  </TableCell>

                  <TableCell className="text-xs whitespace-nowrap">
                    {tender.closing_date ? (
                      <div className="space-y-1">
                        <div className="tabular text-muted-foreground">
                          {new Date(tender.closing_date).toLocaleDateString()}
                        </div>
                        {tender.is_closed ? (
                          <StatusBadge tone="neutral">closed</StatusBadge>
                        ) : days != null && days <= 14 ? (
                          <StatusBadge tone={days <= 5 ? 'down' : 'degraded'}>
                            {days}d left
                          </StatusBadge>
                        ) : null}
                      </div>
                    ) : (
                      <span className="text-muted-foreground">not stated</span>
                    )}
                  </TableCell>

                  <TableCell className="tabular text-xs whitespace-nowrap">
                    {tender.estimated_value != null && tender.currency ? (
                      `${tender.currency} ${tender.estimated_value.toLocaleString()}`
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>

                  <TableCell>
                    <Vote
                      current={tender.feedback}
                      onVote={(rating) => vote.mutate({ id: tender.id, rating })}
                    />
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </Card>
  )
}
