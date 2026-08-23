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

function priorityTone(priority: string): 'down' | 'degraded' | 'neutral' {
  if (priority === 'high') return 'down'
  if (priority === 'medium') return 'degraded'
  return 'neutral'
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
        <Table className="table-fixed">
          {/* `table-fixed`: under auto layout a `w-*` on a column is a
              suggestion and long content wins, which is how tender titles ended
              up rendering over the Closing column. Fixed layout makes the
              widths binding, gives the leftover to the one unsized column, and
              wraps rather than overflowing.

              Headers exist so the badges explain themselves: without them,
              "opportunity / high / 94%" is three unlabelled values.

              Below `md` the graded columns collapse into the subject cell
              rather than surviving as a table you have to drag sideways to
              read. Same data, stacked. */}
          <TableHeader>
            <TableRow>
              <TableHead className="hidden w-[8.5rem] md:table-cell">Category</TableHead>
              <TableHead className="hidden w-[6rem] md:table-cell">Priority</TableHead>
              <TableHead className="hidden w-[6.5rem] lg:table-cell">Confidence</TableHead>
              <TableHead>Subject &amp; sender</TableHead>
              <TableHead className="hidden w-[7rem] lg:table-cell">Received</TableHead>
              <TableHead className="w-[5.5rem] text-right">Correct?</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {emails.data.map((email) => (
              <TableRow key={email.id} className="align-top">
                <TableCell className="hidden md:table-cell">
                  {email.category ? (
                    <StatusBadge tone={CATEGORY_TONE[email.category] ?? 'neutral'}>
                      {humanise(email.category)}
                    </StatusBadge>
                  ) : (
                    <span className="text-muted-foreground text-xs">unclassified</span>
                  )}
                </TableCell>

                <TableCell className="hidden md:table-cell">
                  {email.priority ? (
                    <StatusBadge tone={priorityTone(email.priority)}>
                      {humanise(email.priority)}
                    </StatusBadge>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </TableCell>

                <TableCell className="text-muted-foreground tabular hidden text-xs lg:table-cell">
                  {email.confidence == null ? '—' : `${(email.confidence * 100).toFixed(0)}%`}
                </TableCell>

                <TableCell className="whitespace-normal">
                  <div className="min-w-0">
                    <div className="text-sm font-medium wrap-anywhere">
                      {email.subject ?? '(no subject)'}
                    </div>
                    <div className="text-muted-foreground text-xs wrap-anywhere">
                      {email.from_name ?? email.from_address}
                    </div>

                    {/* What the hidden columns were carrying. */}
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 md:hidden">
                      {email.category && (
                        <StatusBadge tone={CATEGORY_TONE[email.category] ?? 'neutral'}>
                          {humanise(email.category)}
                        </StatusBadge>
                      )}
                      {email.priority && (
                        <StatusBadge tone={priorityTone(email.priority)}>
                          {humanise(email.priority)}
                        </StatusBadge>
                      )}
                    </div>
                    <div className="text-muted-foreground tabular mt-1 flex flex-wrap gap-x-3 text-[11px] lg:hidden">
                      {email.confidence != null && (
                        <span>{(email.confidence * 100).toFixed(0)}% confident</span>
                      )}
                      {email.received_at && (
                        <span>{new Date(email.received_at).toLocaleDateString()}</span>
                      )}
                    </div>

                    {email.reasoning && (
                      <p className="text-muted-foreground mt-1.5 text-xs break-words italic">
                        {email.reasoning}
                      </p>
                    )}
                    {email.suggested_action && (
                      <p className="mt-1 text-xs break-words">→ {email.suggested_action}</p>
                    )}
                  </div>
                </TableCell>

                <TableCell className="text-muted-foreground tabular hidden text-xs whitespace-nowrap lg:table-cell">
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
        <Table className="table-fixed">
          <TableHeader>
            <TableRow>
              <TableHead className="hidden w-[10rem] lg:table-cell">Reference</TableHead>
              <TableHead className="hidden w-[5.5rem] md:table-cell">Source</TableHead>
              <TableHead>Title &amp; procuring entity</TableHead>
              <TableHead className="w-[8.5rem]">Closing</TableHead>
              <TableHead className="hidden w-[8rem] md:table-cell">Value</TableHead>
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
                  <TableCell className="text-muted-foreground hidden font-mono text-xs break-all whitespace-normal lg:table-cell">
                    {tender.reference_no ?? '—'}
                  </TableCell>

                  <TableCell className="text-muted-foreground hidden text-xs md:table-cell">
                    {tender.source}
                  </TableCell>

                  <TableCell className="whitespace-normal">
                    <div className="min-w-0">
                      <a
                        href={tender.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="hover:text-primary inline-flex items-start gap-1 text-sm font-medium break-words"
                      >
                        <span className="min-w-0 wrap-anywhere">{tender.title}</span>
                        <ExternalLink className="mt-0.5 size-3 shrink-0" aria-hidden />
                      </a>
                      <div className="text-muted-foreground text-xs wrap-anywhere">
                        {tender.entity}
                      </div>

                      {/* What the hidden columns were carrying. */}
                      <div className="text-muted-foreground tabular mt-1 flex flex-wrap gap-x-3 text-[11px]">
                        <span className="font-mono break-all lg:hidden">
                          {tender.reference_no ?? '—'}
                        </span>
                        <span className="md:hidden">{tender.source}</span>
                        {tender.estimated_value != null && tender.currency && (
                          <span className="md:hidden">
                            {tender.currency} {tender.estimated_value.toLocaleString()}
                          </span>
                        )}
                      </div>
                    </div>
                  </TableCell>

                  <TableCell className="text-xs whitespace-normal">
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

                  <TableCell className="tabular hidden text-xs whitespace-nowrap md:table-cell">
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
