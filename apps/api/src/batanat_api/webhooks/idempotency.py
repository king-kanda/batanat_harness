"""Webhook idempotency.

Every provider we take deliveries from retries, and a retry is not a new event.
`claim` inserts a row for the delivery and reports whether this caller is the
one that got it — so the guard is a unique constraint, not a read followed by a
write, and two deliveries racing each other cannot both proceed.

Deliberately not Redis: a lost lock here means a duplicate CRM approval, and the
rest of the system dedupes at the database level for exactly that reason.
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db.models import ProcessedWebhook

log = get_logger(__name__)


async def claim(session: AsyncSession, provider: str, external_id: str) -> bool:
    """True if this delivery is new and the caller should handle it.

    False means someone already has, so do nothing. Runs in a savepoint: the
    conflict is expected traffic, not an error, and it must not disturb whatever
    transaction the caller is in the middle of.
    """
    if not external_id:
        # No id to dedupe on. Handle it rather than drop it, and say so.
        log.warning("webhook.no_external_id", provider=provider)
        return True

    async with session.begin_nested():
        claimed = (
            await session.execute(
                insert(ProcessedWebhook)
                .values(provider=provider, external_id=external_id)
                .on_conflict_do_nothing(index_elements=["provider", "external_id"])
                .returning(ProcessedWebhook.id)
            )
        ).scalar_one_or_none()

    if claimed is None:
        log.info("webhook.duplicate_ignored", provider=provider)
        return False
    return True


async def prune(session: AsyncSession, *, older_than_days: int = 7) -> int:
    """Drop old claims. Called by the nightly maintenance job."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import delete

    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    result = await session.execute(
        delete(ProcessedWebhook).where(ProcessedWebhook.created_at < cutoff)
    )
    return result.rowcount or 0
