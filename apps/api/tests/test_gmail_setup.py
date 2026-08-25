"""What has to happen when a Gmail account is connected.

Storing the token is not connecting. Both of these were missing, and each
failed in a way that gave no clue why:

* No `users.watch` meant Google never published to the topic, so a perfectly
  configured Pub/Sub setup sat silent — and the only thing that ever
  registered one was the 02:00 maintenance job.
* No backfill meant `sync_incremental` had no cursor to walk from, so the
  inbox read empty until the next message happened to arrive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from batanat_api.config import get_settings
from batanat_api.gmail import setup


class _Recorder:
    """Stands in for the sync module, recording what setup asked it to do."""

    def __init__(self, *, watch_error=None, backfill_error=None, imported: int = 7):
        self.watch_error = watch_error
        self.backfill_error = backfill_error
        self.imported = imported
        self.calls: list[str] = []
        self.topic: str | None = None
        self.backfill_days: int | None = None
        self.backfill_max: int | None = None

    async def renew_watch(self, session, user_id, topic):
        self.calls.append("watch")
        self.topic = topic
        if self.watch_error:
            raise self.watch_error
        return datetime.now(UTC) + timedelta(days=7)

    async def backfill(self, session, user_id, *, days=None, max_messages=None):
        self.calls.append("backfill")
        self.backfill_days = days
        self.backfill_max = max_messages
        if self.backfill_error:
            raise self.backfill_error

        class _Result:
            new_messages = self.imported

        return _Result()


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "gmail_pubsub_topic", "projects/test/topics/batanat-read")


def _patch(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    monkeypatch.setattr(setup.sync, "renew_watch", recorder.renew_watch)
    monkeypatch.setattr(setup.sync, "backfill", recorder.backfill)


async def test_connecting_registers_the_watch_and_imports(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    recorder = _Recorder()
    _patch(monkeypatch, recorder)

    result = await setup.prepare_mailbox(None, uuid.uuid4())

    assert result.ok
    assert result.watch_registered
    assert result.messages_imported == 7
    assert recorder.topic == "projects/test/topics/batanat-read"


async def test_the_watch_is_registered_before_the_backfill(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    """`users.watch` returns the cursor the incremental sync needs.

    Registered second, there is a window where mail arrives with nothing to
    anchor it to — and a slow backfill delays the point at which push starts.
    """
    recorder = _Recorder()
    _patch(monkeypatch, recorder)

    await setup.prepare_mailbox(None, uuid.uuid4())

    assert recorder.calls == ["watch", "backfill"]


async def test_a_missing_topic_is_reported_not_silently_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact failure this exists to prevent: connected, but nothing arrives."""
    monkeypatch.setattr(get_settings(), "gmail_pubsub_topic", None)
    recorder = _Recorder()
    _patch(monkeypatch, recorder)

    result = await setup.prepare_mailbox(None, uuid.uuid4())

    assert not result.ok
    assert not result.watch_registered
    assert any("GMAIL_PUBSUB_TOPIC" in p for p in result.problems)
    # The backfill still runs — the mailbox is readable even without push.
    assert recorder.calls == ["backfill"]


async def test_a_failed_watch_still_lets_the_backfill_run(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    recorder = _Recorder(watch_error=RuntimeError("Error sending test message"))
    _patch(monkeypatch, recorder)

    result = await setup.prepare_mailbox(None, uuid.uuid4())

    assert not result.watch_registered
    assert result.messages_imported == 7
    assert any("Error sending test message" in p for p in result.problems)


async def test_a_failed_backfill_does_not_lose_the_watch(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    recorder = _Recorder(backfill_error=RuntimeError("Gmail rate limited"))
    _patch(monkeypatch, recorder)

    result = await setup.prepare_mailbox(None, uuid.uuid4())

    assert result.watch_registered
    assert result.messages_imported == 0
    assert not result.ok


async def test_setup_never_raises(monkeypatch: pytest.MonkeyPatch, configured) -> None:
    """A connection that completed must not be thrown away by a setup failure.

    The token exchange already happened in the user's browser; refusing here
    would discard it and make them start over.
    """
    recorder = _Recorder(watch_error=RuntimeError("boom"), backfill_error=RuntimeError("also boom"))
    _patch(monkeypatch, recorder)

    result = await setup.prepare_mailbox(None, uuid.uuid4())

    assert len(result.problems) == 2


async def test_backfill_can_be_skipped(monkeypatch: pytest.MonkeyPatch, configured) -> None:
    """Re-registering a watch should not re-import thirty days."""
    recorder = _Recorder()
    _patch(monkeypatch, recorder)

    await setup.prepare_mailbox(None, uuid.uuid4(), backfill=False)

    assert recorder.calls == ["watch"]


async def test_the_connect_backfill_is_smaller_than_the_full_one(
    monkeypatch: pytest.MonkeyPatch, configured
) -> None:
    """The OAuth callback holds the browser open while this runs.

    `backfill` fetches every message individually, so the default 30 days /
    200 messages is 200 round-trips — the better part of a minute staring at a
    blank redirect. The full window still runs from the expired-cursor path,
    where nobody is waiting on it.
    """
    from batanat_api.gmail import sync as sync_module

    recorder = _Recorder()
    _patch(monkeypatch, recorder)

    await setup.prepare_mailbox(None, uuid.uuid4())

    assert recorder.backfill_days == setup.CONNECT_BACKFILL_DAYS
    assert recorder.backfill_max == setup.CONNECT_BACKFILL_MAX
    assert setup.CONNECT_BACKFILL_DAYS < sync_module.BACKFILL_DAYS
    assert setup.CONNECT_BACKFILL_MAX < sync_module.BACKFILL_MAX_MESSAGES
