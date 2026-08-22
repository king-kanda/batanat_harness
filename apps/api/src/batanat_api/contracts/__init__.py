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
