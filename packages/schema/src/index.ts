/**
 * Shared contracts between the API and the web app.
 *
 * Everything under `generated/` is emitted from the Pydantic models in
 * `apps/api/src/batanat_api/contracts/`. Regenerate with `make types` after
 * changing a model — never edit the generated files.
 */

export type {
  AuthorizationUrl,
  ConnectionStatus,
  ConnectionsPage,
  ConnectionView,
  DisconnectResult,
  ErrorResponse,
  HealthResponse,
  PairingCodeView,
  Provider,
  ProviderStatus,
  ServiceHealth,
  ServiceStatus,
  WhatsAppLinkView,
} from './generated/contracts'
