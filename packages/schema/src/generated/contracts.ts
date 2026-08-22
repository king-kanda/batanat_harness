// AUTO-GENERATED — do not edit.
// Source: apps/api/src/batanat_api/contracts/*.py
// Regenerate: make types

export interface AuthorizationUrl {
  authorization_url: string;
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

export interface DisconnectResult {
  disconnected: boolean;
  /** False when the provider offers no revocation endpoint, or refused. */
  upstream_revoked: boolean;
}

/** Uniform error envelope. */
export interface ErrorResponse {
  error: string;
  detail?: string | null;
  run_id?: string | null;
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

/** A freshly issued WhatsApp pairing code. */
export interface PairingCodeView {
  code: string;
  expires_at: string;
  business_number: string;
  /** Exactly what the user should send, e.g. 'LINK ABCD2345'. */
  message: string;
  /** Deep link that opens WhatsApp with the message prefilled. */
  wa_me_url: string;
  /** Endpoint serving the same deep link as a QR code. */
  qr_svg_url: string;
}

export type Provider = "gmail" | "zoho" | "whatsapp";

/** Whether a provider can be connected at all, given the environment. */
export interface ProviderStatus {
  provider: Provider;
  /** False when its credentials are missing from .env. */
  configured: boolean;
  scopes?: string[];
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

export interface WhatsAppLinkView {
  id: string;
  phone_e164: string;
  linked_at: string;
  last_seen_at?: string | null;
}
