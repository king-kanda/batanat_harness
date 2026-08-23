"""Nightly maintenance.

Six tasks, each independent and each safe to run twice. One failing must not
stop the others — a Gmail watch that could not be renewed is a problem, but it
is not a reason to skip expiring stale approvals.

The Gmail watch renewal is the one that matters most. A watch expires after
seven days and the failure mode is silence: no error, no notification, just an
inbox that stops producing runs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Connection
from batanat_api.gmail import sync

log = get_logger(__name__)


async def renew_gmail_watch(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    settings = get_settings()
    if not settings.gmail_pubsub_topic:
        return {"skipped": "GMAIL_PUBSUB_TOPIC is not set"}

    state = await sync.get_or_create_state(session, user_id)
    if state is None:
        return {"skipped": "no Gmail connection"}

    if not sync.watch_needs_renewal(state):
        return {"renewed": False, "expires_at": state.watch_expiration.isoformat()}

    expiration = await sync.renew_watch(session, user_id, settings.gmail_pubsub_topic)
    return {"renewed": True, "expires_at": expiration.isoformat()}


async def refresh_tokens(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Touch every connection so expiry surfaces here rather than mid-run."""
    from batanat_api.security.token_vault import get_valid_access_token

    results: dict[str, str] = {}
    connections = (
        (
            await session.execute(
                select(Connection).where(
                    Connection.user_id == user_id,
                    Connection.status != enums.ConnectionStatus.revoked,
                )
            )
        )
        .scalars()
        .all()
    )

    for connection in connections:
        if connection.provider is enums.Provider.whatsapp:
            continue
        try:
            await get_valid_access_token(session, user_id, connection.provider)
            results[connection.provider.value] = "ok"
        except Exception as exc:  # noqa: BLE001
            results[connection.provider.value] = f"{type(exc).__name__}"
            log.warning(
                "maintenance.token_refresh_failed",
                provider=connection.provider.value,
                error_type=type(exc).__name__,
            )
    return results


async def check_sources(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from batanat_api.tenders.base import PoliteClient
    from batanat_api.tenders.ingest import record_source_health
    from batanat_api.tenders.sources import build_sources

    client = PoliteClient()
    healthy: list[str] = []
    failing: list[str] = []

    for source in build_sources():
        report = await source.collect(client)
        await record_source_health(session, report)
        (healthy if report.ok and report.tenders else failing).append(source.key)

    return {"healthy": healthy, "failing": failing}


async def expire_approvals(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from batanat_api.approvals.service import expire_stale

    return {"expired": await expire_stale(session)}


async def summarise(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    from batanat_api.memory.summariser import summarise_recent

    return await summarise_recent(session, user_id)


async def prune_webhook_claims(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Drop old delivery claims. Not per-user, but harmless to repeat."""
    from batanat_api.webhooks.idempotency import prune

    return {"pruned": await prune(session)}


TASKS = {
    "gmail_watch": renew_gmail_watch,
    "token_refresh": refresh_tokens,
    "source_health": check_sources,
    "expire_approvals": expire_approvals,
    "prune_webhook_claims": prune_webhook_claims,
    "summarise": summarise,
}


async def run_task(session: AsyncSession, task: str, *, user_id: uuid.UUID) -> dict[str, Any]:
    handler = TASKS.get(task)
    if handler is None:
        raise ValueError(f"Unknown maintenance task {task!r}. Known: {sorted(TASKS)}.")
    return {task: await handler(session, user_id)}


async def run_all(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Every task, each isolated from the others' failures."""
    started = datetime.now(UTC)
    results: dict[str, Any] = {}

    for name, handler in TASKS.items():
        try:
            results[name] = await handler(session, user_id)
        except Exception as exc:  # noqa: BLE001
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
            log.exception("maintenance.task_failed", task=name, error_type=type(exc).__name__)

    log.info(
        "maintenance.complete",
        duration_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
        tasks=list(results),
    )
    return results
