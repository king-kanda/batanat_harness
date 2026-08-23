// AUTO-GENERATED — do not edit.
// Source: apps/api/src/batanat_api/contracts/*.py
// Regenerate: make types

export interface ApprovalDiffEntry {
  field: string;
  current?: unknown;
  proposed?: unknown;
}

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired" | "executed" | "failed";

export interface ApprovalView {
  id: string;
  module: string;
  operation: string;
  record_id?: string | null;
  status: ApprovalStatus;
  rationale?: string | null;
  proposed_payload: Record<string, unknown>;
  diff: ApprovalDiffEntry[];
  expires_at: string;
  hours_remaining: number;
  created_at: string;
  executed_at?: string | null;
  execution_result?: Record<string, unknown> | null;
  run_id?: string | null;
}

export interface AuthorizationUrl {
  authorization_url: string;
}

export interface ChatRequest {
  message: string;
}

export interface ChatResponse {
  run_id: string;
  reply: string | null;
  bound_tools: string[];
  tool_calls?: Record<string, unknown>[];
  status: RunStatus;
}

export type ConnectionStatus = "connected" | "expired" | "error" | "revoked";

/** A connected provider, as shown on the Settings page. */
export interface ConnectionView {
  id: string;
  provider: Provider;
  /** Gmail address, Zoho org id, or WhatsApp number id. */
  external_account: string;
  display_name?: string | null;
  status: ConnectionStatus;
  scopes?: string[];
  access_expires_at?: string | null;
  /** Negative once the access token has already expired. */
  expires_in_hours?: number | null;
  /** True when only the user can restore this connection. */
  needs_reconnect?: boolean;
  /** Zoho: the data-centre API host returned at authorisation. */
  api_domain?: string | null;
  /** Zoho: human-readable data centre. */
  region?: string | null;
  last_ok_at?: string | null;
  last_error?: string | null;
  connected_at: string;
}

/** Everything the Settings → Connections screen needs, in one request. */
export interface ConnectionsPage {
  connections: ConnectionView[];
  providers: ProviderStatus[];
  whatsapp_links: WhatsAppLinkView[];
  whatsapp_business_number?: string | null;
}

/** Everything the dashboard needs, in one request. */
export interface DashboardView {
  generated_at: string;
  opportunities_today: number;
  tenders_today: number;
  pending_approvals: number;
  connections_healthy: number;
  connections_total: number;
  connections_needing_attention?: string[];
  sources?: SourceHealthView[];
  next_runs?: ScheduledRunView[];
  recent_runs?: RunView[];
  kill_switch?: boolean;
  crm_dry_run?: boolean;
}

export interface DiffLine {
  type: string;
  text: string;
}

export interface DisconnectResult {
  disconnected: boolean;
  /** False when the provider offers no revocation endpoint, or refused. */
  upstream_revoked: boolean;
}

/** An uploaded knowledge-base document. */
export interface DocumentView {
  document_id: string;
  filename: string;
  /** user_asserted may inform the agent directly; untrusted_external is only ever quoted as data. */
  trust_tag: string;
  chunk_count: number;
  characters: number;
  uploaded_at: string;
}

export type EmailCategory = "opportunity" | "client" | "supplier" | "administrative" | "spam" | "not_relevant";

export interface EmailView {
  id: string;
  from_address?: string | null;
  from_name?: string | null;
  subject?: string | null;
  snippet?: string | null;
  received_at?: string | null;
  category?: EmailCategory | null;
  priority?: Priority | null;
  confidence?: number | null;
  reasoning?: string | null;
  suggested_action?: string | null;
  feedback?: string | null;
}

/** Uniform error envelope. */
export interface ErrorResponse {
  error: string;
  detail?: string | null;
  run_id?: string | null;
}

export interface FeedbackRequest {
  /** email | tender */
  subject_type: string;
  subject_id: string;
  /** up | down */
  rating: string;
  reason?: string | null;
}

/** Aggregate health of the API and everything it depends on. */
export interface HealthResponse {
  /** Worst status across all services. */
  status: ServiceStatus;
  version: string;
  app_env: string;
  run_id?: string | null;
  checked_at: string;
  services: ServiceHealth[];
}

export interface MemoryView {
  id: string;
  layer: string;
  trust_tag: string;
  content: string;
  source_ref?: string | null;
  created_at: string;
  /** False for untrusted-derived memory, which is only ever quoted as data. */
  instruction_eligible: boolean;
}

/** A freshly issued WhatsApp pairing code. */
export interface PairingCodeView {
  code: string;
  expires_at: string;
  /** The shared number the user must text. */
  business_number: string;
  /** The number this code was issued for, normalised. */
  phone_e164: string;
  /** Exactly what the user should send, e.g. 'LINK ABCD2345'. */
  message: string;
  /** Deep link that opens WhatsApp with the message prefilled. */
  wa_me_url: string;
}

export type Priority = "high" | "medium" | "low";

export type Provider = "gmail" | "zoho" | "whatsapp";

/** Whether a provider can be connected at all, given the environment. */
export interface ProviderStatus {
  provider: Provider;
  /** False when its credentials are missing from .env. */
  configured: boolean;
  scopes?: string[];
}

/** A tender report permalink page. */
export interface ReportView {
  label: string;
  run_id?: string | null;
  generated_at: string;
  lookback_hours: number;
  tenders: TenderView[];
  failed_sources?: string[];
  rejections?: Record<string, string>[];
  validation?: Record<string, unknown>;
}

export type RunStatus = "running" | "succeeded" | "failed" | "refused" | "limit_exceeded";

export interface RunView {
  id: string;
  trigger_type: TriggerType;
  trust_level: TrustLevel;
  /** Exactly the tools this run was handed, recorded before the model ran. */
  bound_tools: string[];
  status: RunStatus;
  trigger_ref?: string | null;
  started_at: string;
  ended_at?: string | null;
  duration_ms?: number | null;
  token_cost?: number;
  iterations?: number;
  error?: string | null;
  summary?: string | null;
  skill_version?: number | null;
  tool_calls?: ToolCallView[];
}

export interface ScheduledRunView {
  id: string;
  next_run_at: string;
}

/** Result of probing one backing service. */
export interface ServiceHealth {
  /** Service identifier, e.g. 'postgres'. */
  name: string;
  status: ServiceStatus;
  /** Round-trip time of the probe, null if it never returned. */
  latency_ms?: number | null;
  /** Human-readable note; the error message when not ok. */
  detail?: string | null;
  checked_at: string;
}

/** Health of a single dependency. */
export type ServiceStatus = "ok" | "degraded" | "down";

export interface SkillValidationView {
  ok: boolean;
  errors?: string[];
  warnings?: string[];
}

export interface SkillVersionView {
  id: string;
  version: number;
  is_active: boolean;
  content: string;
  checksum: string;
  created_by?: string | null;
  notes?: string | null;
  created_at: string;
}

export type SourceHealth = "ok" | "degraded" | "failing";

export interface SourceHealthView {
  key: string;
  name: string;
  health: SourceHealth;
  last_ok_at?: string | null;
  last_error?: string | null;
  consecutive_failures?: number;
}

export interface TenderView {
  id: string;
  source: string;
  reference_no?: string | null;
  title: string;
  entity?: string | null;
  category?: string | null;
  closing_date?: string | null;
  estimated_value?: number | null;
  currency?: string | null;
  source_url: string;
  county?: string | null;
  first_seen_at: string;
  is_closed?: boolean;
  feedback?: string | null;
}

/** One audited tool call, as the Activity screen shows it. */
export interface ToolCallView {
  sequence: number;
  tool_name: string;
  arguments: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  error?: string | null;
  duration_ms?: number | null;
  token_cost?: number;
  started_at: string;
}

export type TriggerType = "gmail_push" | "cron_tender" | "web_chat" | "whatsapp_inbound" | "approval_callback" | "maintenance";

/** Determines which tools a run is allowed to be handed. `untrusted` — the payload originates outside the system (an email body, a scraped page). Read tools and `propose_crm_entry` only. `trusted` — the payload originates from an authenticated human. `system` — internal machinery; usually no LLM at all. */
export type TrustLevel = "untrusted" | "trusted" | "system";

export interface WhatsAppLinkView {
  id: string;
  phone_e164: string;
  linked_at: string;
  last_seen_at?: string | null;
}
