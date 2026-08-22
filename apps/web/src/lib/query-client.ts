import { QueryClient } from '@tanstack/react-query'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        retry: 1,
        refetchOnWindowFocus: true,
      },
    },
  })
}

let browserQueryClient: QueryClient | undefined

/**
 * A fresh client per request on the server (so one user's data can never leak
 * into another's), a singleton in the browser (so the cache survives renders).
 */
export function getQueryClient(): QueryClient {
  if (typeof window === 'undefined') return makeQueryClient()
  browserQueryClient ??= makeQueryClient()
  return browserQueryClient
}
