"""Shared API contracts.

Every model exported here is published to the frontend as a TypeScript type.
Add a model to `EXPORTED_MODELS` to include it.
"""

from __future__ import annotations

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
]

__all__ = [
    "EXPORTED_MODELS",
    "ErrorResponse",
    "HealthResponse",
    "ServiceHealth",
    "ServiceStatus",
]
