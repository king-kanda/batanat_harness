import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'

import { api } from '#/lib/api'

/**
 * Surfaces the two operating modes that change what the system will actually do
 * — dry run and the kill switch — as a dismissible toast rather than a banner
 * nailed to the top of a page.
 *
 * A permanent strip gets tuned out within a day, which is the opposite of what
 * a safety notice is for. A toast is noticed, then dismissed on purpose. It is
 * raised once per browser session so it does not nag on every navigation.
 */
export function ModeNotice() {
  const shown = useRef(false)
  const dashboard = useQuery({ queryKey: ['dashboard'], queryFn: api.dashboard })

  useEffect(() => {
    const data = dashboard.data
    if (!data || shown.current) return
    if (typeof sessionStorage !== 'undefined' && sessionStorage.getItem('mode-notice')) return

    const notices: string[] = []
    if (data.kill_switch) notices.push('Kill switch engaged — no agent runs will start.')
    if (data.crm_dry_run) notices.push('CRM dry run — approved writes are logged, not sent to Zoho.')
    if (!notices.length) return

    shown.current = true
    sessionStorage.setItem('mode-notice', '1')

    toast.warning(notices.length > 1 ? 'Two modes are active' : 'Heads up', {
      description: notices.join(' '),
      duration: Number.POSITIVE_INFINITY, // stays until dismissed on purpose
      closeButton: true,
      action: {
        label: 'Got it',
        onClick: () => undefined,
      },
    })
  }, [dashboard.data])

  return null
}
