import { QueryClientProvider } from '@tanstack/react-query'
import { TanStackDevtools } from '@tanstack/react-devtools'
import { HeadContent, Link, Scripts, createRootRoute } from '@tanstack/react-router'
import { TanStackRouterDevtoolsPanel } from '@tanstack/react-router-devtools'
import { Activity } from 'lucide-react'
import type * as React from 'react'

import { getQueryClient } from '#/lib/query-client'
import appCss from '../styles.css?url'

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/settings/connections', label: 'Connections' },
] as const

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'Batanat Harness' },
    ],
    links: [{ rel: 'stylesheet', href: appCss }],
  }),
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient()

  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        <QueryClientProvider client={queryClient}>
          <div className="mx-auto flex min-h-screen max-w-5xl flex-col px-6 py-8">
            <header className="mb-8 flex items-center gap-4">
              <div className="flex items-center gap-2.5">
                <Activity className="text-accent size-5" aria-hidden />
                <span className="text-ink text-sm font-semibold tracking-tight">
                  Batanat Harness
                </span>
              </div>
              <nav className="flex items-center gap-1 text-xs">
                {NAV.map(({ to, label }) => (
                  <Link
                    key={to}
                    to={to}
                    className="text-ink-faint hover:text-ink rounded px-2 py-1 transition-colors"
                    activeProps={{ className: 'text-ink bg-surface-raised' }}
                    activeOptions={{ exact: to === '/' }}
                  >
                    {label}
                  </Link>
                ))}
              </nav>
            </header>
            <main className="flex-1">{children}</main>
          </div>
        </QueryClientProvider>
        <TanStackDevtools
          config={{ position: 'bottom-right' }}
          plugins={[{ name: 'Tanstack Router', render: <TanStackRouterDevtoolsPanel /> }]}
        />
        <Scripts />
      </body>
    </html>
  )
}
