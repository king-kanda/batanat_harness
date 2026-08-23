/**
 * Human labels for machine values.
 *
 * The API speaks in enum strings — `untrusted_external`, `not_relevant`,
 * `limit_exceeded`. Those are the right thing on the wire and the wrong thing
 * on screen: an underscore in a sentence reads as a leaked internal.
 *
 * Anything not listed falls back to replacing underscores and sentence-casing,
 * so a new enum value degrades to something readable rather than something ugly.
 */

const LABELS: Record<string, string> = {
  // trust tags
  user_asserted: 'Our own information',
  system_derived: 'Observed by the system',
  untrusted_external: 'From outside the system',

  // memory layers
  procedural: 'Operating rules',
  semantic: 'Business knowledge',
  episodic: 'Recent activity',

  // email categories
  opportunity: 'Opportunity',
  client: 'Client',
  supplier: 'Supplier',
  administrative: 'Administrative',
  spam: 'Spam',
  not_relevant: 'Not relevant',

  // run status
  succeeded: 'Succeeded',
  failed: 'Failed',
  running: 'Running',
  refused: 'Refused',
  limit_exceeded: 'Stopped at limit',

  // approvals
  pending: 'Pending',
  approved: 'Approved',
  rejected: 'Rejected',
  expired: 'Expired',
  executed: 'Executed',

  // source + connection health
  ok: 'OK',
  degraded: 'Degraded',
  failing: 'Failing',
  connected: 'Connected',
  revoked: 'Revoked',
  error: 'Error',

  // trigger types
  gmail_push: 'New email',
  cron_tender: 'Scheduled tender sweep',
  web_chat: 'Chat',
  whatsapp_inbound: 'WhatsApp message',
  approval_callback: 'Approval execution',
  maintenance: 'Maintenance',

  // trust levels
  trusted: 'Trusted',
  untrusted: 'Untrusted',
  system: 'System',
}

/** A readable label for an API enum value. */
export function humanise(value: string | null | undefined): string {
  if (!value) return '—'
  const known = LABELS[value]
  if (known) return known
  const spaced = value.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Short form, for table cells and badges where the full label is too long. */
export function humaniseShort(value: string | null | undefined): string {
  if (!value) return '—'
  const SHORT: Record<string, string> = {
    user_asserted: 'Our own',
    system_derived: 'Observed',
    untrusted_external: 'External',
    not_relevant: 'Not relevant',
    limit_exceeded: 'Stopped',
  }
  return SHORT[value] ?? humanise(value)
}
