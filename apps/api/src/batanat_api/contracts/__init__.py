"""Shared API contracts.

Every model exported here is published to the frontend as a TypeScript type.
Add a model to `EXPORTED_MODELS` to include it.
"""

from __future__ import annotations

from batanat_api.contracts.connections import (
    AuthorizationUrl,
    ConnectionsPage,
    ConnectionView,
    DisconnectResult,
    PairingCodeView,
    ProviderStatus,
    WhatsAppLinkView,
)
from batanat_api.contracts.health import (
    ErrorResponse,
    HealthResponse,
    ServiceHealth,
    ServiceStatus,
)
from batanat_api.contracts.operations import (
    ApprovalDiffEntry,
    ApprovalView,
    ChatRequest,
    ChatResponse,
    DashboardView,
    DiffLine,
    DocumentView,
    EmailView,
    FeedbackRequest,
    MemoryView,
    ReportView,
    RunView,
    ScheduledRunView,
    SkillValidationView,
    SkillVersionView,
    SourceHealthView,
    TenderSourceRequest,
    TenderSourceView,
    TenderView,
    ToolCallView,
)

EXPORTED_MODELS = [
    ServiceHealth,
    HealthResponse,
    ErrorResponse,
    ConnectionView,
    ProviderStatus,
    WhatsAppLinkView,
    ConnectionsPage,
    AuthorizationUrl,
    PairingCodeView,
    DisconnectResult,
    ToolCallView,
    RunView,
    ApprovalDiffEntry,
    ApprovalView,
    EmailView,
    TenderView,
    SourceHealthView,
    TenderSourceRequest,
    TenderSourceView,
    ScheduledRunView,
    DashboardView,
    SkillVersionView,
    SkillValidationView,
    DiffLine,
    DocumentView,
    MemoryView,
    ReportView,
    FeedbackRequest,
    ChatRequest,
    ChatResponse,
]

__all__ = [
    "EXPORTED_MODELS",
    "AuthorizationUrl",
    "ConnectionView",
    "ConnectionsPage",
    "DisconnectResult",
    "ErrorResponse",
    "HealthResponse",
    "PairingCodeView",
    "ProviderStatus",
    "ServiceHealth",
    "ServiceStatus",
    "WhatsAppLinkView",
]
