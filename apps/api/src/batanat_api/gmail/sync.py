"""Gmail synchronisation.

Pub/Sub notifications carry a `historyId`, not a message. The flow is: read the
stored cursor, ask Gmail what changed since then, fetch those messages, process
them, and only then advance the cursor.

**Only then.** If the cursor advances before the batch is processed, a crash
mid-batch loses every message in it, silently and permanently. Advancing last
means a crash replays — and replaying is free, because the unique constraint on
`(user_id, gmail_message_id)` absorbs the duplicates.

Gmail expires a `historyId` after roughly a week. That surfaces as a 404 or 410,
and the answer is a windowed re-sync via `messages.list` — the same code path as
first-time backfill, which is why there is one function for both.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Connection, Email, GmailSyncState
from batanat_api.db.mongo import RAW_EMAILS, archive
from batanat_api.gmail.client import GmailClient, HistoryExpiredError

log = get_logger(__name__)

#: Backfill bounds from the PRD.
BACKFILL_DAYS = 30
BACKFILL_MAX_MESSAGES = 200


@dataclass
class SyncResult:
    new_messages: int = 0
    already_seen: int = 0
    history_id: int | None = None
    resynced: bool = False
    email_ids: list[uuid.UUID] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.email_ids is None:
            self.email_ids = []


async def get_or_create_state(session: AsyncSession, user_id: uuid.UUID) -> GmailSyncState | None:
    connection = (
        await session.execute(
            select(Connection).where(
                Connection.user_id == user_id,
                Connection.provider == enums.Provider.gmail,
                Connection.status != enums.ConnectionStatus.revoked,
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        return None

    state = (
        await session.execute(
            select(GmailSyncState).where(GmailSyncState.connection_id == connection.id)
        )
    ).scalar_one_or_none()

    if state is None:
        state = GmailSyncState(user_id=user_id, connection_id=connection.id)
        session.add(state)
        await session.flush()
    return state


async def _store_message(
    session: AsyncSession, user_id: uuid.UUID, client: GmailClient, message_id: str
) -> tuple[uuid.UUID | None, bool]:
    """Fetch and store one message. Returns (row_id, was_new)."""
    message = await client.get_message(message_id)

    row_id = uuid.uuid4()
    statement = (
        insert(Email)
        .values(
            id=row_id,
            user_id=user_id,
            gmail_message_id=message.id,
            gmail_thread_id=message.thread_id,
            history_id=message.history_id,
            from_address=message.from_address,
            from_name=message.from_name,
            subject=message.subject,
            snippet=message.snippet,
            received_at=message.received_at,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "gmail_message_id"])
        .returning(Email.id)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()

    if inserted is None:
        return None, False  # already had it; at-least-once delivery is normal

    await archive(
        RAW_EMAILS, inserted, message.raw, user_id=str(user_id), gmail_message_id=message.id
    )
    return inserted, True


async def sync_incremental(
    session: AsyncSession, user_id: uuid.UUID, *, notified_history_id: int | None = None
) -> SyncResult:
    """Process everything since the stored cursor, then advance it."""
    state = await get_or_create_state(session, user_id)
    if state is None:
        raise RuntimeError("No Gmail connection for this user.")

    client = GmailClient(session, user_id)
    result = SyncResult()

    if state.history_id is None:
        # Never synced. Backfill, which also establishes the cursor.
        return await backfill(session, user_id)

    try:
        message_ids, latest = await client.list_history(state.history_id)
    except HistoryExpiredError:
        log.warning("gmail.history_expired", stored_history_id=state.history_id)
        outcome = await backfill(session, user_id, days=7)
        outcome.resynced = True
        return outcome

    for message_id in message_ids:
        stored_id, was_new = await _store_message(session, user_id, client, message_id)
        if was_new and stored_id:
            result.new_messages += 1
            result.email_ids.append(stored_id)
        else:
            result.already_seen += 1

    # Cursor last. A crash above replays; a crash after this would skip.
    new_cursor = latest or notified_history_id or state.history_id
    state.history_id = new_cursor
    state.last_synced_at = datetime.now(UTC)
    await session.flush()

    result.history_id = new_cursor
    log.info(
        "gmail.sync.incremental",
        new=result.new_messages,
        already_seen=result.already_seen,
        history_id=new_cursor,
    )
    return result


async def backfill(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    days: int = BACKFILL_DAYS,
    max_messages: int = BACKFILL_MAX_MESSAGES,
) -> SyncResult:
    """Windowed re-sync. Used for first-time setup and for an expired cursor."""
    state = await get_or_create_state(session, user_id)
    if state is None:
        raise RuntimeError("No Gmail connection for this user.")

    client = GmailClient(session, user_id)
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y/%m/%d")

    state.backfill_status = "running"
    state.backfill_done = 0
    await session.flush()

    result = SyncResult()
    page_token: str | None = None
    collected: list[str] = []

    while len(collected) < max_messages:
        ids, page_token = await client.list_messages(
            query=f"after:{since}",
            limit=min(100, max_messages - len(collected)),
            page_token=page_token,
        )
        collected.extend(ids)
        if not page_token:
            break

    state.backfill_total = len(collected)
    await session.flush()

    for index, message_id in enumerate(collected, start=1):
        stored_id, was_new = await _store_message(session, user_id, client, message_id)
        if was_new and stored_id:
            result.new_messages += 1
            result.email_ids.append(stored_id)
        else:
            result.already_seen += 1

        # Progress is written as we go so the UI can show it.
        state.backfill_done = index
        if index % 10 == 0:
            await session.flush()

    latest_history = (
        await session.execute(
            select(Email.history_id)
            .where(Email.user_id == user_id, Email.history_id.isnot(None))
            .order_by(Email.history_id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if latest_history:
        state.history_id = latest_history
    state.backfill_status = "complete"
    state.last_synced_at = datetime.now(UTC)
    await session.flush()

    result.history_id = state.history_id
    log.info(
        "gmail.sync.backfill",
        days=days,
        found=len(collected),
        new=result.new_messages,
        history_id=state.history_id,
    )
    return result


async def renew_watch(session: AsyncSession, user_id: uuid.UUID, topic: str) -> datetime:
    """(Re)register push notifications. Gmail expires a watch after 7 days."""
    state = await get_or_create_state(session, user_id)
    if state is None:
        raise RuntimeError("No Gmail connection for this user.")

    history_id, expiration = await GmailClient(session, user_id).watch(topic)
    state.watch_expiration = expiration
    if state.history_id is None:
        state.history_id = history_id
    await session.flush()
    return expiration


def watch_needs_renewal(
    state: GmailSyncState, *, now: datetime | None = None, margin_hours: int = 48
) -> bool:
    """Renew well before expiry: a lapsed watch means silence, not an error."""
    if state.watch_expiration is None:
        return True
    return state.watch_expiration - (now or datetime.now(UTC)) <= timedelta(hours=margin_hours)
