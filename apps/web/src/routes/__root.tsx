import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { TanStackDevtools } from '@tanstack/react-devtools'
import {
  HeadContent,
  Scripts,
  createRootRoute,
  useNavigate,
  useRouterState,
} from '@tanstack/react-router'
import { TanStackRouterDevtoolsPanel } from '@tanstack/react-router-devtools'
import { ThemeProvider } from 'next-themes'
import { useEffect } from 'react'
import type * as React from 'react'

import { AppSidebar } from '#/components/app-sidebar'
import { ModeNotice } from '#/components/mode-notice'
import { Tour } from '#/components/tour'
import { ModeToggle } from '#/components/mode-toggle'
import { Separator } from '#/components/ui/separator'
import { SidebarInset, SidebarProvider, SidebarTrigger } from '#/components/ui/sidebar'
import { Toaster } from '#/components/ui/sonner'
import { api } from '#/lib/api'
import { getQueryClient } from '#/lib/query-client'
import appCss from '../styles.css?url'

/** Page titles, keyed by route. Keeps the header honest without prop-drilling. */
const TITLES: Record<string, string> = {
  '/': 'Chat',
  '/approvals': 'Approvals',
  '/opportunities': 'Opportunities',
  '/audit': 'Audit logs',
  '/rules': 'Rules',
  '/memory': 'Memory',
  '/settings/knowledge': 'Knowledge base',
  '/settings/sources': 'Sources & schedule',
  '/onboarding': 'Get started',
  '/settings/rules-assistant': 'Rules assistant',
  '/settings/connections': 'Connections',
  '/login': 'Sign in',
}

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: 'utf-8' },
      { name: 'viewport', content: 'width=device-width, initial-scale=1' },
      { title: 'Batanat Harness' },
    ],
    links: [
      { rel: 'stylesheet', href: appCss },
      { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
      { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossOrigin: '' },
      {
        rel: 'stylesheet',
        href: 'https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap',
      },
    ],
  }),
  shellComponent: RootDocument,
})

function RootDocument({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient()

  return (
    // suppressHydrationWarning: next-themes sets the class on <html> before
    // React hydrates, which is exactly what stops the flash of the wrong theme.
    <html lang="en" suppressHydrationWarning>
      <head>
        <HeadContent />
      </head>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          <QueryClientProvider client={queryClient}>
            {/* One dotted canvas for the whole app; cards sit on solid surfaces above it. */}
            <div
              aria-hidden
              className="dotted-grid bg-background pointer-events-none fixed inset-0 -z-10"
            />
            <AuthGate>{children}</AuthGate>
            <Tour />
            <Toaster position="bottom-right" />
          </QueryClientProvider>
        </ThemeProvider>

        {import.meta.env.DEV && (
          <TanStackDevtools
            config={{ position: 'bottom-left' }}
            plugins={[{ name: 'Tanstack Router', render: <TanStackRouterDevtoolsPanel /> }]}
          />
        )}
        <Scripts />
      </body>
    </html>
  )
}

/**
 * Routes the user to the login screen when there is no session.
 *
 * This is UX, not security. Every API endpoint refuses an unauthenticated
 * request on its own — this only saves the user from a screen full of failed
 * requests. Treating a client-side guard as the control would be a mistake.
 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const navigate = useNavigate()
  const onLoginPage = pathname === '/login'

  const auth = useQuery({
    queryKey: ['auth-me'],
    queryFn: api.auth.me,
    retry: false,
    enabled: !onLoginPage,
    staleTime: 60_000,
  })

  useEffect(() => {
    if (!onLoginPage && auth.isError) navigate({ to: '/login' })
  }, [onLoginPage, auth.isError, navigate])

  if (onLoginPage) return <>{children}</>

  if (auth.isPending || auth.isError) {
    return (
      <div className="text-muted-foreground flex min-h-svh items-center justify-center text-sm">
        {auth.isError ? 'Redirecting to sign in…' : 'Loading…'}
      </div>
    )
  }

  return <AppShell>{children}</AppShell>
}

function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const title = TITLES[pathname] ?? (pathname.startsWith('/reports/') ? 'Report' : 'Batanat')

  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-transparent">
        <header className="bg-background/80 sticky top-0 z-10 flex h-14 shrink-0 items-center gap-2 border-b px-4 backdrop-blur-xl">
          <SidebarTrigger className="-ml-1" />
          <Separator orientation="vertical" className="mr-1 !h-4" />
          <h1 className="text-sm font-semibold tracking-tight">{title}</h1>
          <div className="ml-auto" data-tour="theme-toggle">
            <ModeToggle />
          </div>
        </header>
        <ModeNotice />
        <main className="flex-1 p-4 md:p-6">
          <div className="mx-auto w-full max-w-6xl">{children}</div>
        </main>
      </SidebarInset>
    </SidebarProvider>
  )
}
