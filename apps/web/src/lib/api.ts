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
  ApprovalView,
  AuthorizationUrl,
  ChatResponse,
  ConnectionsPage,
  DashboardView,
  DiffLine,
  DisconnectResult,
  EmailView,
  HealthResponse,
  MemoryView,
  PairingCodeView,
  Provider,
  ReportView,
  RunView,
  SkillValidationView,
  SkillVersionView,
  TenderView,
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
    throw new ApiError(`Cannot reach the API at ${API_BASE_URL}`, undefined, runId)
  }

  if (!response.ok && response.status !== 503) {
    // The API returns a readable `detail` on refusals — surface it verbatim,
    // since these are usually actionable ("Zoho is not configured").
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

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined })

export const api = {
  health: () => request<HealthResponse>('/api/health'),
  dashboard: () => request<DashboardView>('/api/dashboard'),
  policy: () => request<Record<string, { trust: string; tools: string[] }>>('/api/policy'),

  connections: {
    list: () => request<ConnectionsPage>('/api/connections'),
    authorize: (provider: Provider) =>
      post<AuthorizationUrl>(`/api/connections/${provider}/authorize`),
    disconnect: (id: string) =>
      request<DisconnectResult>(`/api/connections/${id}`, { method: 'DELETE' }),
    pairingCode: (phone: string) =>
      post<PairingCodeView>('/api/connections/whatsapp/pairing-code', { phone }),
    unlinkNumber: (id: string) =>
      request<void>(`/api/connections/whatsapp/links/${id}`, { method: 'DELETE' }),
  },

  runs: {
    list: () => request<RunView[]>('/api/runs'),
    get: (id: string) => request<RunView>(`/api/runs/${id}`),
  },

  results: {
    emails: () => request<EmailView[]>('/api/emails'),
    tenders: (includeClosed = false) =>
      request<TenderView[]>(`/api/tenders?include_closed=${includeClosed}`),
    feedback: (body: {
      subject_type: string
      subject_id: string
      rating: string
      reason?: string
    }) => request<void>('/api/feedback', { method: 'POST', body: JSON.stringify(body) }),
  },

  approvals: {
    list: () => request<ApprovalView[]>('/api/approvals'),
    approve: (id: string, editedPayload?: Record<string, unknown>) =>
      post<Record<string, unknown>>(`/api/approvals/${id}/approve`, editedPayload),
    reject: (id: string, reason?: string) =>
      post<Record<string, unknown>>(
        `/api/approvals/${id}/reject${reason ? `?reason=${encodeURIComponent(reason)}` : ''}`,
      ),
  },

  skill: {
    versions: () => request<SkillVersionView[]>('/api/skill'),
    validate: (content: string) => post<SkillValidationView>('/api/skill/validate', { content }),
    publish: (content: string, notes?: string) =>
      post<SkillVersionView>('/api/skill', { content, notes }),
    rollback: (version: number) => post<SkillVersionView>(`/api/skill/${version}/rollback`),
    diff: (oldVersion: number, newVersion: number) =>
      request<DiffLine[]>(`/api/skill/diff?old=${oldVersion}&new=${newVersion}`),
  },

  memories: {
    list: (search?: string) =>
      request<MemoryView[]>(`/api/memories${search ? `?search=${encodeURIComponent(search)}` : ''}`),
    remove: (id: string) => request<void>(`/api/memories/${id}`, { method: 'DELETE' }),
  },

  reports: {
    tenders: (label: string) => request<ReportView>(`/api/reports/tenders/${label}`),
  },

  chat: (message: string) => post<ChatResponse>('/api/chat', { message }),

  sync: {
    gmail: () => post<Record<string, unknown>>('/api/sync/gmail'),
    tenders: () => post<Record<string, unknown>>('/api/sync/tenders'),
  },
}
