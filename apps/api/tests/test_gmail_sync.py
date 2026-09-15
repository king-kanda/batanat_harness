from __future__ import annotations

import uuid

import pytest

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
async def test_history_404_or_410_triggers_resync(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    class FakeSession:
        async def flush(self):
            return None

    class FakeState:
        history_id = 5254702
        last_synced_at = None

    called: dict[str, int | None] = {"days": None, "notified_history_id": None}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def list_history(self, start_history_id: int):
            raise gmail_client.HistoryExpiredError(f"Gmail returned {status_code} for /history")

    async def fake_backfill(
        session,
        user_id,
        *,
        days: int = sync.BACKFILL_DAYS,
        max_messages: int = sync.BACKFILL_MAX_MESSAGES,
        notified_history_id: int | None = None,
    ):
        called["days"] = days
        called["notified_history_id"] = notified_history_id
        return sync.SyncResult(new_messages=0, already_seen=0, history_id=6000000, resynced=False)

    async def fake_get_or_create_state(session, user_id):
        return FakeState()

    monkeypatch.setattr(sync, "GmailClient", FakeClient)
    monkeypatch.setattr(sync, "backfill", fake_backfill)
    monkeypatch.setattr(sync, "get_or_create_state", fake_get_or_create_state)

    result = await sync.sync_incremental(FakeSession(), uuid.uuid4(), notified_history_id=5267000)

    assert result.resynced is True
    assert called["days"] == 7
    assert called["notified_history_id"] == 5267000


async def test_message_404_is_skipped_and_cursor_still_advances(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSession:
        async def flush(self):
            return None

    class FakeState:
        history_id = 5254702
        last_synced_at = None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def list_history(self, start_history_id: int):
            return ["missing-message", "live-message"], 5268000

    async def fake_get_or_create_state(session, user_id):
        return state

    async def fake_store_message(session, user_id, client, message_id):
        if message_id == "missing-message":
            raise gmail_client.MessageNotFoundError(
                "Gmail returned 404 for /messages/missing-message"
            )
        return uuid.uuid4(), True

    state = FakeState()
    monkeypatch.setattr(sync, "GmailClient", FakeClient)
    monkeypatch.setattr(sync, "get_or_create_state", fake_get_or_create_state)
    monkeypatch.setattr(sync, "_store_message", fake_store_message)

    result = await sync.sync_incremental(FakeSession(), uuid.uuid4(), notified_history_id=5268100)

    assert result.new_messages == 1
    assert result.history_id == 5268000
    assert state.history_id == 5268000


async def test_message_404_is_not_treated_as_history_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
