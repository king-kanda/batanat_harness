/**
 * Shared contracts between the API and the web app.
 *
 * Everything under `generated/` is emitted from the Pydantic models in
 * `apps/api/src/batanat_api/contracts/`. Regenerate with `make types` after
 * changing a model — never edit the generated files.
 */

export type {
  ApprovalDiffEntry,
  ApprovalStatus,
  ApprovalView,
  AuthorizationUrl,
  ChatRequest,
  ChatResponse,
  ConnectionStatus,
  ConnectionsPage,
  ConnectionView,
  DashboardView,
  DiffLine,
  DisconnectResult,
  DocumentView,
  EmailCategory,
  EmailView,
  ErrorResponse,
  FeedbackRequest,
  HealthResponse,
  MemoryView,
  PairingCodeView,
  Priority,
  Provider,
  ProviderStatus,
  ReportView,
  RunStatus,
  RunView,
  ScheduledRunView,
  ServiceHealth,
  ServiceStatus,
  SkillDraftResponse,
  SkillValidationView,
  SkillVersionView,
  SourceHealth,
  SourceHealthView,
  TenderSourceView,
  TenderView,
  ToolCallView,
  TriggerType,
  TrustLevel,
  WhatsAppLinkView,
} from './generated/contracts'
