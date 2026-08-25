"""What has to happen when a Gmail account is first connected.

Storing the token is not connecting. Two more things have to happen or the
integration looks broken in ways that give no clue why:

**Register the watch.** Gmail only pushes to Pub/Sub for mailboxes with an
active `users.watch`. Without it Google never publishes, the topic stays
silent, and every part of the Pub/Sub configuration can be perfect while
nothing arrives. This used to be done only by the 02:00 maintenance job, so
connecting at 09:00 meant no push until the following night — and no way to
tell that from a misconfiguration.

**Backfill.** `sync_incremental` walks Gmail's history from a stored cursor. A
fresh connection has no cursor, so it walks nothing and the inbox reads empty
until the next message happens to arrive.

Both are best-effort. A failure here leaves a *connected* account with no push
or no history, which is recoverable and worth reporting — unlike refusing the
connection outright, which throws away a token exchange the user just completed
in their browser.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.gmail import sync

log = get_logger(__name__)

#: A deliberately smaller window than `sync.BACKFILL_DAYS`.
#:
#: The backfill fetches every message individually, so the default 30 days /
#: 200 messages is 200 HTTP round-trips — the better part of a minute with the
#: browser sat on a blank redirect waiting for the OAuth callback to return.
#: Seven days is enough to prove the connection works and give the screen
#: something to show; the full window still runs from the expired-cursor path,
#: where nobody is watching.
CONNECT_BACKFILL_DAYS = 7
CONNECT_BACKFILL_MAX = 50


@dataclass(slots=True)
class SetupResult:
    """What the setup managed, and what it did not."""

    watch_registered: bool = False
    watch_expires_at: str | None = None
    messages_imported: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


async def prepare_mailbox(
    session: AsyncSession, user_id: uuid.UUID, *, backfill: bool = True
) -> SetupResult:
    """Register push, then import recent history. Never raises.

    Ordered deliberately: the watch first, so a slow or partial backfill cannot
    delay the point at which new mail starts arriving. `users.watch` also
    returns the mailbox's current `historyId`, which becomes the cursor
    `sync_incremental` needs — registering it second would leave a window where
    messages arrive with nothing to anchor them to.
    """
    result = SetupResult()
    settings = get_settings()

    if not settings.gmail_pubsub_topic:
        result.problems.append(
            "GMAIL_PUBSUB_TOPIC is not set, so push notifications were not registered. "
            "Mail will only arrive when you press Sync now."
        )
    else:
        try:
            expiration = await sync.renew_watch(session, user_id, settings.gmail_pubsub_topic)
            result.watch_registered = True
            result.watch_expires_at = expiration.isoformat()
            log.info("gmail.setup.watch_registered", user_id=str(user_id))
        except Exception as exc:  # noqa: BLE001
            result.problems.append(f"Could not register push notifications: {exc}")
            log.warning("gmail.setup.watch_failed", error_type=type(exc).__name__)

    if backfill:
        try:
            imported = await sync.backfill(
                session,
                user_id,
                days=CONNECT_BACKFILL_DAYS,
                max_messages=CONNECT_BACKFILL_MAX,
            )
            result.messages_imported = imported.new_messages
            log.info("gmail.setup.backfilled", user_id=str(user_id), count=imported.new_messages)
        except Exception as exc:  # noqa: BLE001
            result.problems.append(f"Could not import recent mail: {exc}")
            log.warning("gmail.setup.backfill_failed", error_type=type(exc).__name__)

    return result
