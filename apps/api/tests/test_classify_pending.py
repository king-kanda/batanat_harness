"""Classifying email that a sync never reached.

Classification only ever happened to messages arriving through `sync_incremental`.
Anything a *backfill* imported — the whole inbox at connect time — was stored
with no verdict and never revisited: the cursor had already moved past it, and
no query anywhere looked for `category IS NULL`. The result was an Opportunities
screen of rows reading "unclassified" with no way to fix it short of
disconnecting.

The second failure was quieter. `run_classification` sliced `email_ids[:20]` and
dropped the rest without a word, so a burst of more than twenty arriving at once
left a tail that could never be classified either.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from batanat_api.db import enums
from batanat_api.db.models import Email
from batanat_api.triggers import gmail_trigger


async def _email(session, user_id, *, age_hours: int, category=None) -> Email:
    email = Email(
        user_id=user_id,
        gmail_message_id=f"msg-{uuid.uuid4().hex[:12]}",
        gmail_thread_id=f"thread-{uuid.uuid4().hex[:8]}",
        from_address="sender@example.com",
        subject="Tender for solar installation",
        snippet="We invite bids.",
        received_at=datetime.now(UTC) - timedelta(hours=age_hours),
        category=category,
    )
    session.add(email)
    await session.flush()
    return email


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[list[uuid.UUID]]:
    """Record what each model batch was asked to classify, without a model."""
    batches: list[list[uuid.UUID]] = []

    async def fake_batch(session, user_id, email_ids):
        batches.append(list(email_ids))
        return uuid.uuid4()

    async def no_alerts(*args, **kwargs):
        return 0

    monkeypatch.setattr(gmail_trigger, "_classify_batch", fake_batch)
    monkeypatch.setattr(gmail_trigger, "alert_on_opportunities", no_alerts)
    monkeypatch.setattr(gmail_trigger, "alert_on_proposals", no_alerts)
    return batches


async def test_unclassified_email_is_picked_up(session, user, captured) -> None:
    """The backfill case: stored by an import, never seen by a sync."""
    email = await _email(session, user.id, age_hours=48)

    assert await gmail_trigger.classify_pending(session, user.id) == 1
    assert captured == [[email.id]]


async def test_already_classified_email_is_left_alone(session, user, captured) -> None:
    await _email(session, user.id, age_hours=1, category=enums.EmailCategory.spam)

    assert await gmail_trigger.classify_pending(session, user.id) == 0
    assert captured == []


async def test_nothing_pending_makes_no_model_call(session, user, captured) -> None:
    assert await gmail_trigger.classify_pending(session, user.id) == 0
    assert captured == []


async def test_another_users_backlog_is_not_touched(session, user, captured) -> None:
    from batanat_api.db.models import User

    other = User(email=f"other-{uuid.uuid4().hex[:6]}@batanat.test")
    session.add(other)
    await session.flush()
    await _email(session, other.id, age_hours=5)

    assert await gmail_trigger.classify_pending(session, user.id) == 0
    assert captured == []


async def test_a_backlog_over_one_batch_is_chunked_not_truncated(session, user, captured) -> None:
    """The tail used to be dropped silently and was then unreachable forever."""
    total = gmail_trigger.BATCH_SIZE + 5
    for hours in range(total):
        await _email(session, user.id, age_hours=hours + 1)

    assert await gmail_trigger.classify_pending(session, user.id) == total

    assert len(captured) == 2
    assert [len(batch) for batch in captured] == [gmail_trigger.BATCH_SIZE, 5]
    # Every message reaches the model exactly once.
    seen = [email_id for batch in captured for email_id in batch]
    assert len(set(seen)) == total


async def test_the_sweep_is_capped_and_resumes_where_it_stopped(session, user, captured) -> None:
    """A neglected mailbox must not turn one button press into hours of calls."""
    for hours in range(5):
        await _email(session, user.id, age_hours=hours + 1)

    assert await gmail_trigger.classify_pending(session, user.id, limit=2) == 2

    # Nothing was written, so the same rows are still pending — the point is
    # that the query drives it, so no progress is lost between sweeps.
    still_pending = (
        (
            await session.execute(
                select(Email.id).where(Email.user_id == user.id, Email.category.is_(None))
            )
        )
        .scalars()
        .all()
    )
    assert len(still_pending) == 5


async def test_the_oldest_are_taken_first(session, user, captured) -> None:
    """So a mailbox over the ceiling advances in order instead of resampling."""
    oldest = await _email(session, user.id, age_hours=100)
    await _email(session, user.id, age_hours=2)
    await _email(session, user.id, age_hours=1)

    await gmail_trigger.classify_pending(session, user.id, limit=1)
    assert captured == [[oldest.id]]


async def test_alerts_run_once_over_the_whole_set(session, user, monkeypatch) -> None:
    """Batching is a detail of the model call, not something the user hears twice."""
    alerted: list[list[uuid.UUID]] = []

    async def fake_batch(session, user_id, email_ids):
        return uuid.uuid4()

    async def record_opportunities(session, user_id, email_ids):
        alerted.append(list(email_ids))
        return 0

    async def no_proposals(*args, **kwargs):
        return 0

    monkeypatch.setattr(gmail_trigger, "_classify_batch", fake_batch)
    monkeypatch.setattr(gmail_trigger, "alert_on_opportunities", record_opportunities)
    monkeypatch.setattr(gmail_trigger, "alert_on_proposals", no_proposals)

    total = gmail_trigger.BATCH_SIZE + 3
    for hours in range(total):
        await _email(session, user.id, age_hours=hours + 1)

    await gmail_trigger.classify_pending(session, user.id)

    assert len(alerted) == 1
    assert len(alerted[0]) == total
