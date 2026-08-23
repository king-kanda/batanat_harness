import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { ExternalLink, TriangleAlert } from 'lucide-react'

import { Badge } from '#/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '#/components/ui/card'
import { api } from '#/lib/api'

export const Route = createFileRoute('/reports/tenders/$label')({ component: Report })

/**
 * The permalink every report email and WhatsApp alert links to. This page is
 * the source of truth: what the notification summarised, in full, plus what
 * the validator rejected — which the email deliberately does not carry.
 */
function Report() {
  const { label } = Route.useParams()
  const report = useQuery({
    queryKey: ['report', label],
    queryFn: () => api.reports.tenders(label),
  })

  if (report.isPending) {
    return <Card><CardContent className="text-ink-faint text-xs">Loading report…</CardContent></Card>
  }

  if (report.isError) {
    return (
      <Card>
        <CardContent className="text-status-down text-xs">{report.error.message}</CardContent>
      </Card>
    )
  }

  const data = report.data
  const failedSources = data.failed_sources ?? []
  const rejections = data.rejections ?? []
  const byEntity = new Map<string, typeof data.tenders>()
  for (const tender of data.tenders) {
    const key = tender.entity ?? 'Other'
    byEntity.set(key, [...(byEntity.get(key) ?? []), tender])
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Tender report — {data.label}</CardTitle>
            <CardDescription>
              {data.tenders.length} tender(s) over the last {data.lookback_hours}h ·{' '}
              {new Date(data.generated_at).toLocaleString()}
            </CardDescription>
          </div>
          {data.run_id && (
            <span className="text-ink-faint font-mono text-[11px]">
              run {data.run_id.slice(0, 8)}
            </span>
          )}
        </CardHeader>

        {failedSources.length > 0 && (
          <CardContent className="border-border-subtle border-b">
            <p className="text-status-degraded flex items-start gap-2 text-xs">
              <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span>
                <b>Sources unavailable:</b> {failedSources.join(', ')}. Those sites may have
                published tenders this run could not see.
              </span>
            </p>
          </CardContent>
        )}

        {data.tenders.length === 0 && (
          <CardContent className="text-ink-muted text-xs">
            No new tenders in this window. This report is produced even when empty, so that
            silence always means something is broken rather than quiet.
          </CardContent>
        )}

        {[...byEntity.entries()].map(([entity, tenders]) => (
          <div key={entity}>
            <div className="bg-surface border-border-subtle text-ink-muted border-y px-4 py-1.5 text-[11px] font-medium">
              {entity}
            </div>
            {tenders.map((tender) => (
              <div key={tender.id} className="border-border-subtle border-b px-4 py-2.5 last:border-b-0">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-ink-muted font-mono text-[11px]">
                    {tender.reference_no ?? '—'}
                  </span>
                  {tender.closing_date && (
                    <Badge variant={tender.is_closed ? 'neutral' : 'degraded'}>
                      closes {new Date(tender.closing_date).toLocaleDateString()}
                    </Badge>
                  )}
                  {tender.estimated_value != null && tender.currency && (
                    <span className="text-ink-faint tabular text-[11px]">
                      {tender.currency} {tender.estimated_value.toLocaleString()}
                    </span>
                  )}
                </div>
                <a
                  href={tender.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-ink hover:text-accent mt-0.5 inline-flex items-start gap-1 text-sm"
                >
                  {tender.title}
                  <ExternalLink className="mt-0.5 size-3 shrink-0" aria-hidden />
                </a>
              </div>
            ))}
          </div>
        ))}
      </Card>

      {rejections.length > 0 && (
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Rejected by the validator</CardTitle>
              <CardDescription>
                These were found but not reported. The validator rejects rather than patching, so
                a failure is visible here instead of silently altering a result.
              </CardDescription>
            </div>
          </CardHeader>
          <div>
            {rejections.map((rejection, index) => (
              <div
                key={index}
                className="border-border-subtle flex items-baseline gap-3 border-b px-4 py-2 text-xs last:border-b-0"
              >
                <Badge variant="down">{rejection.rule}</Badge>
                <span className="text-ink-muted truncate">{rejection.subject}</span>
                <span className="text-ink-faint truncate">{rejection.detail}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
