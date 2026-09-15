from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from batanat_api.db import enums
from batanat_api.db.models import Connection, Email, GmailSyncState
from batanat_api.gmail import client as gmail_client
from batanat_api.gmail import sync


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}
        self.is_success = 200 <= status_code < 300

    def json(self) -> dict:
        return self._payload


@pytest.mark.parametrize("status_code", [404, 410])
async def test_history_404_or_410_triggers_resync(monkeypatch: pytest.MonkeyPatch, session, user) -> None:
    connection = Connection(
        user_id=user.id,
        provider=enums.Provider.gmail,
        external_account=user.email,
        status=enums.ConnectionStatus.connected,
    )
    session.add(connection)
    await session.flush()

    session.add(GmailSyncState(user_id=user.id, connection_id=connection.id, history_id=5254702))
    await session.flush()

    async def no_archive(*args, **kwargs):
        return None

    called: dict[str, int | None] = {"days": None, "notified_history_id": None}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def list_history(self, start_history_id: int):
            raise gmail_client.HistoryExpiredError(f"Gmail returned {status_code} for /history")

    async def fake_backfill(
        db_session,
        user_id,
        *,
        days: int = sync.BACKFILL_DAYS,
        max_messages: int = sync.BACKFILL_MAX_MESSAGES,
        notified_history_id: int | None = None,
    ):
        called["days"] = days
        called["notified_history_id"] = notified_history_id
        return sync.SyncResult(new_messages=0, already_seen=0, history_id=6000000, resynced=False)

    monkeypatch.setattr(sync, "GmailClient", FakeClient)
    monkeypatch.setattr(sync, "backfill", fake_backfill)
    monkeypatch.setattr(sync, "archive", no_archive)

    result = await sync.sync_incremental(session, user.id, notified_history_id=5267000)

    assert result.resynced is True
    assert called["days"] == 7
    assert called["notified_history_id"] == 5267000


async def test_message_404_is_skipped_and_cursor_still_advances(
    monkeypatch: pytest.MonkeyPatch, session, user
) -> None:
    connection = Connection(
        user_id=user.id,
        provider=enums.Provider.gmail,
        external_account=user.email,
        status=enums.ConnectionStatus.connected,
    )
    session.add(connection)
    await session.flush()

    state = GmailSyncState(user_id=user.id, connection_id=connection.id, history_id=5254702)
    session.add(state)
    await session.flush()

    async def no_archive(*args, **kwargs):
        return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def list_history(self, start_history_id: int):
            return ["missing-message", "live-message"], 5268000

        async def get_message(self, message_id: str):
            if message_id == "missing-message":
                raise gmail_client.MessageNotFoundError("Gmail returned 404 for /messages/missing-message")
            return gmail_client.GmailMessage(
                id="live-message",
                thread_id="thread-1",
                history_id=5267999,
                from_address="sender@example.com",
                from_name="Sender",
                subject="Newest email",
                snippet="hello",
                received_at=datetime.now(UTC),
                body="body",
                raw={},
            )

    monkeypatch.setattr(sync, "GmailClient", FakeClient)
    monkeypatch.setattr(sync, "archive", no_archive)

    result = await sync.sync_incremental(session, user.id, notified_history_id=5268100)

    assert result.new_messages == 1
    assert result.history_id == 5268000
    await session.refresh(state)
    assert state.history_id == 5268000

    stored = (
        await session.execute(select(Email).where(Email.user_id == user.id))
    ).scalars().all()
    assert len(stored) == 1
    assert stored[0].gmail_message_id == "live-message"


async def test_message_404_is_not_treated_as_history_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_token(*, force: bool = False):
        return "token"

    async def fake_send(method: str, path: str, token: str, **kwargs):
        assert path == "/messages/m1"
        return _Response(status_code=404)

    client = gmail_client.GmailClient(None, uuid.uuid4())
    monkeypatch.setattr(client, "_token", fake_token)
    monkeypatch.setattr(client, "_send", fake_send)

    with pytest.raises(gmail_client.MessageNotFoundError):
        await client.get_message("m1")
