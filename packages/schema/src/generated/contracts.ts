// AUTO-GENERATED — do not edit.
// Source: apps/api/src/batanat_api/contracts/*.py
// Regenerate: make types

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
