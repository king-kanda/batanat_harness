/**
 * Typed API client.
 *
 * Response types come from `@batanat/schema`, which is generated from the
 * Pydantic models — if the backend contract changes and the frontend is not
 * updated, this fails at typecheck rather than at runtime.
 *
 * Every request carries an `x-run-id` so a click in the UI can be traced to a
 * line in the API log.
 */

import type {
  AuthorizationUrl,
  ConnectionsPage,
  DisconnectResult,
  HealthResponse,
  PairingCodeView,
  Provider,
} from '@batanat/schema'

export const API_BASE_URL: string =
  import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly runId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function newRunId(): string {
  return crypto.randomUUID().replaceAll('-', '')
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const runId = newRunId()
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        'x-run-id': runId,
        ...(init?.body ? { 'content-type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch {
    // Network-level failure: the API is not running or CORS blocked it.
    throw new ApiError(`Cannot reach the API at ${API_BASE_URL}`, undefined, runId)
  }

  if (!response.ok && response.status !== 503) {
    // The API returns a readable `detail` on refusals — surface it verbatim
    // rather than a generic failure, since these are usually actionable
    // ("Zoho is not configured", "rate limit reached").
    let detail = `${init?.method ?? 'GET'} ${path} failed`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body; keep the generic message */
    }
    throw new ApiError(detail, response.status, response.headers.get('x-run-id') ?? runId)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export const api = {
  /** Aggregate health. Returns a body on 503 too — a down service is data, not an error. */
  health: () => request<HealthResponse>('/api/health'),

  connections: {
    list: () => request<ConnectionsPage>('/api/connections'),

    authorize: (provider: Provider) =>
      request<AuthorizationUrl>(`/api/connections/${provider}/authorize`, { method: 'POST' }),

    disconnect: (connectionId: string) =>
      request<DisconnectResult>(`/api/connections/${connectionId}`, { method: 'DELETE' }),

    pairingCode: () =>
      request<PairingCodeView>('/api/connections/whatsapp/pairing-code', { method: 'POST' }),

    unlinkNumber: (linkId: string) =>
      request<void>(`/api/connections/whatsapp/links/${linkId}`, { method: 'DELETE' }),
  },
}
