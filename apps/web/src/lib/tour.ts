/**
 * A guided tour of the app.
 *
 * Hand-rolled rather than pulling a tour library: the whole job is "go to a
 * page, highlight an element, put a card near it, advance", and a dependency
 * for that would be larger than the code.
 *
 * Each step names the route it belongs to and the tour navigates there, so the
 * user is looking at the real screen being described rather than a sidebar link
 * to it. Steps target `data-tour` attributes rather than CSS classes, so
 * restyling a component cannot silently break the tour.
 */

export type TourStep = {
  /** Route to visit before showing this step. Omit to stay where we are. */
  route?: string
  /** `data-tour` value to spotlight. Omit for an unanchored card. */
  target?: string
  title: string
  body: string
}

export const TOUR: TourStep[] = [
  {
    route: '/',
    target: 'chat-input',
    title: 'This is the front door',
    body: 'Ask about tenders, email or the CRM in plain language. The summary above the box shows what is waiting; it gets out of the way once you start typing.',
  },
  {
    route: '/opportunities',
    target: 'opportunities-panel',
    title: 'Opportunities',
    body: 'Everything worth your attention, from email and from tender sites. The thumbs are not decoration — each one becomes a labelled test case that measures how well your criteria are working.',
  },
  {
    route: '/approvals',
    target: 'approvals-panel',
    title: 'Nothing reaches your CRM unreviewed',
    body: 'Every write queues here first. You get a field-by-field diff, you can edit before approving, and rejecting one teaches the assistant what you did not want.',
  },
  {
    route: '/audit',
    target: 'audit-panel',
    title: 'Every run, on the record',
    body: 'Expandable down to each tool call: what went in, what came back, how long it took, what it cost, and which version of your rules was live at the time.',
  },
  {
    route: '/rules',
    target: 'rules-editor',
    title: 'Your rules',
    body: 'What counts as an opportunity, what is urgent, what to ignore. This is the highest-leverage screen in the app — it is what makes the assistant yours rather than generic.',
  },
  {
    route: '/rules',
    target: 'rules-assistant',
    title: 'Not sure what to write?',
    body: 'This opens a conversation that drafts the rules for you, straight into the editor behind it. It has no tools and can only write text — you still read it and press Publish.',
  },
  {
    route: '/settings/knowledge',
    target: 'knowledge-upload',
    title: 'Knowledge base',
    body: 'Capability statements, past tenders, won-deal summaries. This is what lets the assistant judge whether a tender is a fit for you specifically, not just whether it mentions energy.',
  },
  {
    route: '/settings/sources',
    target: 'sources-panel',
    title: 'Where tenders come from',
    body: 'The sites swept twice a day, each with its own health. You can add your own, and turn off any you do not want touched.',
  },
  {
    route: '/settings/connections',
    target: 'connections-panel',
    title: 'Connections',
    body: 'Gmail, Zoho and WhatsApp. Gmail is read-only by design — the assistant can read the inbox and can never send from it.',
  },
  {
    target: 'theme-toggle',
    title: 'That is the tour',
    body: 'Light and dark live here. You can restart this tour any time from the Get started page.',
  },
]

const STORAGE_KEY = 'batanat-tour-seen'

export function hasSeenTour(): boolean {
  if (typeof localStorage === 'undefined') return true
  return localStorage.getItem(STORAGE_KEY) === '1'
}

export function markTourSeen(): void {
  if (typeof localStorage !== 'undefined') localStorage.setItem(STORAGE_KEY, '1')
}

/** Broadcast so the mounted <Tour /> picks it up from anywhere. */
export function startTour(): void {
  window.dispatchEvent(new CustomEvent('batanat:tour'))
}
