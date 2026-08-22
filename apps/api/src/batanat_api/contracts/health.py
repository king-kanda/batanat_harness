"""Health contracts.

These models are the source of truth for the shared types in
`packages/schema` — see `scripts/export_contracts.py`. Change them here, run
`make types`, and the frontend types follow.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ServiceStatus(StrEnum):
    """Health of a single dependency."""

    ok = "ok"
    degraded = "degraded"
    down = "down"


class ServiceHealth(BaseModel):
    """Result of probing one backing service."""

    name: str = Field(description="Service identifier, e.g. 'postgres'.")
    status: ServiceStatus
    latency_ms: float | None = Field(
        default=None, description="Round-trip time of the probe, null if it never returned."
    )
    detail: str | None = Field(
        default=None, description="Human-readable note; the error message when not ok."
    )
    checked_at: datetime


class HealthResponse(BaseModel):
    """Aggregate health of the API and everything it depends on."""

    status: ServiceStatus = Field(description="Worst status across all services.")
    version: str
    app_env: str
    run_id: str | None = None
    checked_at: datetime
    services: list[ServiceHealth]


class ErrorResponse(BaseModel):
    """Uniform error envelope."""

    error: str
    detail: str | None = None
    run_id: str | None = None
