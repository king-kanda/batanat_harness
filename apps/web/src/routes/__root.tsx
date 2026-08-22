import { QueryClientProvider } from '@tanstack/react-query'
import { TanStackDevtools } from '@tanstack/react-devtools'
import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router'
import { TanStackRouterDevtoolsPanel } from '@tanstack/react-router-devtools'
import { Activity } from 'lucide-react'
import type * as React from 'react'

import { getQueryClient } from '#/lib/query-client'
import appCss from '../styles.css?url'

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
            <header className="mb-8 flex items-center gap-2.5">
              <Activity className="text-accent size-5" aria-hidden />
              <span className="text-ink text-sm font-semibold tracking-tight">
                Batanat Harness
              </span>
              <span className="text-ink-faint text-xs">agentic operations</span>
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
