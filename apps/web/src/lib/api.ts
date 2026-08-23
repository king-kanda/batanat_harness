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
  DemoDataView,
  DiffLine,
  DisconnectResult,
  DocumentView,
  EmailView,
  HealthResponse,
  MemoryView,
  PairingCodeView,
  Provider,
  ReportView,
  RunView,
  SkillDraftResponse,
  SkillValidationView,
  SkillVersionView,
  TenderSourceView,
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

/**
 * Statuses to treat as a normal response rather than an error.
 *
 * Only `/api/health` needs this: it answers 503 *with a full report* when a
 * dependency is down, and that report is the thing we want to render. Every
 * other endpoint uses 503 to refuse — "Zoho is not configured", "no model API
 * key is set" — and those carry a `detail` the user needs to see, so they must
 * travel the error path.
 */
type Options = RequestInit & { tolerate?: readonly number[] }

async function request<T>(path: string, init?: Options): Promise<T> {
  const runId = newRunId()
  let response: Response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      // The session lives in an HttpOnly cookie, and the API is a different
      // origin in development, so it is only sent when asked for explicitly.
      credentials: 'include',
      headers: {
        'x-run-id': runId,
        ...(init?.body && !(init.body instanceof FormData)
          ? { 'content-type': 'application/json' }
          : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError(`Cannot reach the API at ${API_BASE_URL}`, undefined, runId)
  }

  if (!response.ok && !init?.tolerate?.includes(response.status)) {
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

export type CurrentUser = {
  id: string
  email: string
  name: string | null
  timezone: string
  using_default_password: boolean
}

export const api = {
  auth: {
    me: () => request<CurrentUser>('/api/auth/me'),
    login: (email: string, password: string) =>
      post<CurrentUser>('/api/auth/login', { email, password }),
    logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  },

  health: () => request<HealthResponse>('/api/health', { tolerate: [503] }),
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
    draft: (messages: Array<{ role: string; content: string }>, currentContent?: string) =>
      post<SkillDraftResponse>('/api/skill/draft', {
        messages,
        current_content: currentContent,
      }),
    diff: (oldVersion: number, newVersion: number) =>
      request<DiffLine[]>(`/api/skill/diff?old=${oldVersion}&new=${newVersion}`),
  },

  memories: {
    list: (search?: string) =>
      request<MemoryView[]>(`/api/memories${search ? `?search=${encodeURIComponent(search)}` : ''}`),
    remove: (id: string) => request<void>(`/api/memories/${id}`, { method: 'DELETE' }),
  },

  sources: {
    list: () => request<TenderSourceView[]>('/api/sources'),
    create: (body: { name: string; listing_url: string; entity?: string }) =>
      post<TenderSourceView>('/api/sources', body),
    update: (key: string, body: Record<string, unknown>) =>
      request<TenderSourceView>(`/api/sources/${key}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    remove: (key: string) => request<void>(`/api/sources/${key}`, { method: 'DELETE' }),
  },

  knowledge: {
    list: () => request<DocumentView[]>('/api/knowledge'),
    upload: (file: File, trustTag: string) => {
      // multipart: no content-type header — the browser sets the boundary.
      const body = new FormData()
      body.append('file', file)
      body.append('trust_tag', trustTag)
      return request<DocumentView>('/api/knowledge', { method: 'POST', body })
    },
    remove: (documentId: string) =>
      request<void>(`/api/knowledge/${documentId}`, { method: 'DELETE' }),
  },

  reports: {
    tenders: (label: string) => request<ReportView>(`/api/reports/tenders/${label}`),
  },

  demo: {
    status: () => request<DemoDataView>('/api/demo'),
    seed: () => post<DemoDataView>('/api/demo/seed'),
    clear: () => post<DemoDataView>('/api/demo/clear'),
  },

  chat: (message: string) => post<ChatResponse>('/api/chat', { message }),

  sync: {
    gmail: () => post<Record<string, unknown>>('/api/sync/gmail'),
    tenders: () => post<Record<string, unknown>>('/api/sync/tenders'),
  },
}
