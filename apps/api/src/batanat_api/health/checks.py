"""Dependency health probes.

Each probe opens its own short-lived connection rather than borrowing from a
pool. A pooled connection can report green while the server behind it is gone;
for a status page we want the truth, and this endpoint is called rarely.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

# Imported at module scope on purpose. Importing a driver inside its probe made
# the first health call take ten seconds and time out a service that was fine —
# import cost was being measured as latency.
import asyncpg
import httpx
from pymongo import AsyncMongoClient
from redis.asyncio import from_url as redis_from_url

from batanat_api.config import Settings
from batanat_api.contracts.health import ServiceHealth, ServiceStatus
from batanat_api.core.logging import get_logger

log = get_logger(__name__)


async def _probe(
    name: str,
    fn: Callable[[], Awaitable[str | None]],
    timeout_s: float,
) -> ServiceHealth:
    """Run one probe, converting timeouts and exceptions into a `down` result."""
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(fn(), timeout=timeout_s)
        status = ServiceStatus.ok
    except TimeoutError:
        detail = f"probe timed out after {timeout_s}s"
        status = ServiceStatus.down
    except Exception as exc:  # noqa: BLE001 — a status page must never raise
        detail = f"{type(exc).__name__}: {exc}"
        status = ServiceStatus.down

    result = ServiceHealth(
        name=name,
        status=status,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
        detail=detail,
        checked_at=datetime.now(UTC),
    )
    if status is not ServiceStatus.ok:
        log.warning("health.probe.failed", service=name, detail=detail)
    return result


async def _postgres(settings: Settings) -> str | None:
    conn = await asyncpg.connect(settings.database_url)
    try:
        await conn.execute("SELECT 1")
        version = await conn.fetchval("SHOW server_version")
        return f"postgres {version}"
    finally:
        await conn.close()


async def _redis(settings: Settings) -> str | None:
    client = redis_from_url(settings.redis_url)
    try:
        await client.ping()
        info = await client.info("server")
        return f"redis {info.get('redis_version', 'unknown')}"
    finally:
        await client.aclose()


async def _mongo(settings: Settings) -> str | None:
    client = AsyncMongoClient(settings.mongo_url, serverSelectionTimeoutMS=1500)
    try:
        info = await client.admin.command("buildInfo")
        return f"mongodb {info.get('version', 'unknown')}"
    finally:
        await client.close()


async def _qdrant(settings: Settings) -> str | None:
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    async with httpx.AsyncClient(timeout=2.0, headers=headers) as client:
        ready = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz")
        ready.raise_for_status()
        root = await client.get(settings.qdrant_url.rstrip("/") + "/")
        version = root.json().get("version", "unknown") if root.is_success else "unknown"
        return f"qdrant {version}"


# Ordered as they are rendered in the UI.
PROBES: dict[str, Callable[[Settings], Awaitable[str | None]]] = {
    "postgres": _postgres,
    "qdrant": _qdrant,
    "mongo": _mongo,
    "redis": _redis,
}


async def check_all(settings: Settings) -> list[ServiceHealth]:
    """Probe every dependency concurrently."""
    results = await asyncio.gather(
        *(
            _probe(name, lambda fn=fn: fn(settings), settings.health_check_timeout_s)
            for name, fn in PROBES.items()
        )
    )
    return list(results)


def overall_status(services: list[ServiceHealth]) -> ServiceStatus:
    """Worst status wins."""
    if any(s.status is ServiceStatus.down for s in services):
        return ServiceStatus.down
    if any(s.status is ServiceStatus.degraded for s in services):
        return ServiceStatus.degraded
    return ServiceStatus.ok
