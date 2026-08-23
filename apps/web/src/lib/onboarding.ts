import { useQuery } from '@tanstack/react-query'

import { api } from '#/lib/api'

/**
 * Onboarding progress, derived from what is actually configured.
 *
 * Deliberately not a stored "completed" flag. A flag drifts: someone disconnects
 * Gmail and the checklist still claims it is done. Reading the real state means
 * the list is correct by construction, and a step that regresses shows up again.
 */
export type Step = {
  id: string
  title: string
  blurb: string
  to: string
  done: boolean
  optional?: boolean
}

export function useOnboarding() {
  const connections = useQuery({ queryKey: ['connections'], queryFn: api.connections.list })
  const knowledge = useQuery({ queryKey: ['knowledge'], queryFn: api.knowledge.list })
  const skill = useQuery({ queryKey: ['skill'], queryFn: api.skill.versions })

  const loading = connections.isPending || knowledge.isPending || skill.isPending

  const connected = (provider: string) =>
    !!connections.data?.connections.some((c) => c.provider === provider && !c.needs_reconnect)

  // Version 1 is the seeded placeholder, so "they wrote their own rules" means
  // a version beyond it exists.
  const rulesWritten = (skill.data?.length ?? 0) > 1

  const steps: Step[] = [
    {
      id: 'rules',
      title: 'Describe what matters to you',
      blurb:
        'The single highest-leverage thing here. What counts as an opportunity, what is urgent, what wastes your time. There is an assistant to talk it through with you.',
      to: '/settings/rules-assistant',
      done: rulesWritten,
    },
    {
      id: 'gmail',
      title: 'Connect Gmail',
      blurb: 'Read-only. Lets the assistant spot opportunities in the inbox and classify them.',
      to: '/settings/connections',
      done: connected('gmail'),
    },
    {
      id: 'zoho',
      title: 'Connect Zoho CRM',
      blurb: 'Read leads, contacts and deals. Every write still waits for your approval.',
      to: '/settings/connections',
      done: connected('zoho'),
    },
    {
      id: 'whatsapp',
      title: 'Link WhatsApp',
      blurb: 'Where urgent alerts land, and where you can approve a CRM write from your phone.',
      to: '/settings/connections',
      done: !!connections.data?.whatsapp_links.length,
    },
    {
      id: 'knowledge',
      title: 'Add what you know',
      blurb:
        'Capability statements, past tenders, won-deal summaries. This is what makes relevance specific to you rather than generic.',
      to: '/settings/knowledge',
      done: (knowledge.data?.length ?? 0) > 0,
    },
  ]

  const done = steps.filter((s) => s.done).length
  return { steps, done, total: steps.length, complete: done === steps.length, loading }
}
