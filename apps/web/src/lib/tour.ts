/**
 * A guided tour of the app.
 *
 * Hand-rolled rather than pulling a tour library: the whole job is "highlight an
 * element, put a card near it, advance", and a dependency for that would be
 * larger than the code.
 *
 * Steps target `data-tour` attributes rather than CSS classes, so restyling a
 * component cannot silently break the tour. A step whose target is missing is
 * skipped rather than leaving an empty spotlight pointing at nothing — screens
 * differ by route and by what is configured.
 */

export type TourStep = {
  target?: string
  route?: string
  title: string
  body: string
}

export const TOUR: TourStep[] = [
  {
    route: '/',
    title: 'This is the front door',
    body: 'Ask about tenders, email or the CRM in plain language. The summary above the box shows what is waiting; it gets out of the way once you start typing.',
    target: 'chat-input',
  },
  {
    target: 'nav-opportunities',
    title: 'Opportunities',
    body: 'Everything worth your attention, from email and from tender sites. The thumbs are not decoration — each one becomes a labelled test case that measures how well the criteria are working.',
  },
  {
    target: 'nav-approvals',
    title: 'Approvals',
    body: 'Nothing is ever written to your CRM without passing through here first. You see a field-by-field diff, and can edit before approving.',
  },
  {
    target: 'nav-audit',
    title: 'Audit logs',
    body: 'Every run the assistant has made, expandable to each tool call, what it cost, and which version of your rules was live at the time.',
  },
  {
    target: 'nav-rules',
    title: 'Your rules',
    body: 'What counts as an opportunity, what is urgent, what to ignore. This is the highest-leverage screen in the app — there is an assistant that will help you write it.',
  },
  {
    target: 'nav-knowledge',
    title: 'Knowledge base',
    body: 'Upload capability statements, past tenders, won-deal summaries. This is what makes relevance specific to your business rather than generic.',
  },
  {
    target: 'nav-connections',
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
