"""Health endpoints.

`/api/health`       — always 200, body carries the real status (for the UI).
`/api/health/ready` — 503 when a dependency is down (for orchestrators).
`/api/health/live`  — process liveness only, touches nothing external.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from batanat_api.config import Settings, get_settings
from batanat_api.contracts.health import HealthResponse, ServiceStatus
from batanat_api.core.run_context import get_run_id
from batanat_api.health.checks import check_all, overall_status
from batanat_api.version import __version__

router = APIRouter(prefix="/api/health", tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


async def _build(settings: Settings) -> HealthResponse:
    services = await check_all(settings)
    return HealthResponse(
        status=overall_status(services),
        version=__version__,
        app_env=settings.app_env,
        run_id=get_run_id(),
        checked_at=datetime.now(UTC),
        services=services,
    )


@router.get("", response_model=HealthResponse, summary="Aggregate health")
async def health(settings: SettingsDep) -> HealthResponse:
    return await _build(settings)


@router.get("/ready", response_model=HealthResponse, summary="Readiness probe")
async def ready(settings: SettingsDep, response: Response) -> HealthResponse:
    result = await _build(settings)
    if result.status is ServiceStatus.down:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result


@router.get("/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
