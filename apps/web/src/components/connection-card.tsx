import type { ConnectionView, Provider, ProviderStatus } from '@batanat/schema'
import { CircleCheck, ExternalLink, TriangleAlert, Unplug } from 'lucide-react'

import { StatusBadge } from '#/components/status-badge'
import { Button } from '#/components/ui/button'

export const PROVIDER_LABEL: Record<Provider, string> = {
  gmail: 'Gmail',
  zoho: 'Zoho CRM',
  whatsapp: 'WhatsApp',
}

const PROVIDER_BLURB: Record<Provider, string> = {
  gmail: 'Read-only access to the inbox, so opportunities can be spotted and classified.',
  zoho: 'Read leads, contacts and deals. Writes go through the approval queue.',
  whatsapp: 'Alerts and approvals on a shared business number.',
}

/**
 * What expiry means depends entirely on whether a refresh token is stored.
 *
 * Google access tokens are always one hour, so warning on "expires in under a
 * day" put a permanent amber triangle on a healthy connection — alarming about
 * the one thing the token vault handles by itself, while saying nothing about
 * the thing that actually strands it. The real risk is the *refresh* token:
 * Google expires those after ~7 days while the OAuth app is in Testing mode,
 * and that surfaces as `needs_reconnect`.
 */
function ExpiryNote({ connection }: { connection: ConnectionView }) {
  if (connection.needs_reconnect) {
    return (
      <span className="text-status-down inline-flex items-center gap-1">
        <TriangleAlert className="size-3" aria-hidden />
        Reconnect needed
      </span>
    )
  }

  const hours = connection.expires_in_hours

  if (connection.can_refresh) {
    return (
      <span className="text-muted-foreground/80">
        Renews automatically
        {hours != null && hours > 0 && ` · next in ${hours < 1 ? '<1' : Math.round(hours)}h`}
      </span>
    )
  }

  if (hours == null) return <span className="text-muted-foreground/80">No stated expiry</span>

  // No refresh token: this one really is counting down to a manual reconnect.
  return (
    <span className="text-status-degraded">
      <TriangleAlert className="mr-1 inline size-3" aria-hidden />
      Expires in {hours < 1 ? '<1' : Math.round(hours)}h — no refresh token
    </span>
  )
}

export function ConnectionCard({
  provider,
  status,
  connection,
  onConnect,
  onDisconnect,
  busy,
}: {
  provider: Provider
  status?: ProviderStatus
  connection?: ConnectionView
  onConnect: () => void
  onDisconnect: () => void
  busy: boolean
}) {
  const connected = connection && !connection.needs_reconnect
  const configured = status?.configured ?? false
  // `scopes` is optional in the generated contract (it has a server-side
  // default), so narrow it once rather than at each use.
  const scopes = status?.scopes ?? []

  return (
    <div className="border-border border-b p-4 last:border-b-0">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-foreground text-sm font-medium">{PROVIDER_LABEL[provider]}</span>
            {connected ? (
              <StatusBadge tone="ok">
                <CircleCheck className="size-3" aria-hidden />
                connected
              </StatusBadge>
            ) : connection?.needs_reconnect ? (
              <StatusBadge tone="down">{connection.status}</StatusBadge>
            ) : configured ? (
              <StatusBadge tone="neutral">not connected</StatusBadge>
            ) : (
              <StatusBadge tone="degraded">not configured</StatusBadge>
            )}
          </div>

          <p className="text-muted-foreground/80 mt-1 text-xs">{PROVIDER_BLURB[provider]}</p>

          {connection && (
            <dl className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
              <div className="text-muted-foreground font-mono">
                {connection.display_name ?? connection.external_account}
              </div>
              {connection.region && (
                <div className="text-muted-foreground/80">
                  DC <span className="text-muted-foreground">{connection.region}</span>
                </div>
              )}
              <ExpiryNote connection={connection} />
            </dl>
          )}

          {!configured && (
            <p className="text-muted-foreground/80 mt-2 text-[11px]">
              Credentials missing from <span className="font-mono">.env</span> — see{' '}
              <span className="font-mono">TODO.md</span>.
            </p>
          )}

          {connection?.last_error && (
            <p className="text-status-down mt-2 text-[11px]">{connection.last_error}</p>
          )}

          {scopes.length > 0 && (
            <details className="mt-2">
              <summary className="text-muted-foreground/80 cursor-pointer text-[11px] hover:underline">
                {scopes.length} scopes requested
              </summary>
              {/* Scope URLs are long and have nothing to break on. */}
              <ul className="text-muted-foreground/80 mt-1 space-y-0.5 font-mono text-[10px] break-all">
                {scopes.map((scope) => (
                  <li key={scope}>{scope}</li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {connection && (
            <Button variant="destructive" onClick={onDisconnect} disabled={busy}>
              <Unplug className="size-3" aria-hidden />
              Disconnect
            </Button>
          )}
          <Button
            variant="default"
            onClick={onConnect}
            disabled={busy || !configured}
            title={configured ? undefined : 'Set this provider’s credentials in .env first'}
          >
            <ExternalLink className="size-3" aria-hidden />
            {connection ? 'Reconnect' : 'Connect'}
          </Button>
        </div>
      </div>
    </div>
  )
}
