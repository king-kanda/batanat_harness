"""Seeding and clearing demo data.

The property worth testing is not that clearing works — it is that clearing is
*bounded*. This is reachable from a button, on an installation that may hold
real work, so the test that matters is the one proving a real row survives it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from batanat_api.db import enums
from batanat_api.db.models import Approval, DemoArtifact, Email, Run, Tender
from batanat_api.demo.fixtures import clear_demo_data, demo_status, load_demo_data


async def test_seeding_is_idempotent(session, user) -> None:
    first = await load_demo_data(session, user.id)
    assert first["emails"] > 0

    second = await load_demo_data(session, user.id)
    assert second == {"emails": 0, "tenders": 0, "runs": 0, "approvals": 0}

    # And the ledger did not double either.
    tracked = (
        await session.execute(
            select(func.count(DemoArtifact.id)).where(DemoArtifact.user_id == user.id)
        )
    ).scalar_one()
    assert tracked == sum(first.values())


async def test_clearing_removes_everything_it_seeded(session, user) -> None:
    await load_demo_data(session, user.id)
    assert (await demo_status(session, user.id))["email"] > 0

    await clear_demo_data(session, user.id)

    assert await demo_status(session, user.id) == {
        "email": 0,
        "tender": 0,
        "run": 0,
        "approval": 0,
    }
    for model in (Email, Tender, Run, Approval):
        remaining = (await session.execute(select(func.count(model.id)))).scalar_one()
        assert remaining == 0, model.__name__


async def test_clearing_leaves_no_orphaned_approval(session, user) -> None:
    """`Approval.run_id` is SET NULL, so deleting the run is not enough.

    The previous pattern-matching reset dropped the run and left the demo
    approval sitting in the pending queue on every single call.
    """
    await load_demo_data(session, user.id)
    assert (await session.execute(select(func.count(Approval.id)))).scalar_one() == 1

    await clear_demo_data(session, user.id)
    assert (await session.execute(select(func.count(Approval.id)))).scalar_one() == 0


async def test_clearing_cannot_touch_real_data(session, user) -> None:
    """The point of the ledger. Real rows shaped exactly like fixtures survive."""
    await load_demo_data(session, user.id)

    # Deliberately adversarial: ids and URLs that the old `demo-%` and fixture
    # URL matching would have deleted.
    session.add(
        Email(
            user_id=user.id,
            gmail_message_id="demo-999",
            gmail_thread_id="thread-real",
            from_address="real@client.co.ke",
            subject="An actual email that happens to look seeded",
            received_at=datetime.now(UTC),
        )
    )
    session.add(
        Tender(
            source="kplc",
            reference_no="REAL-001",
            title="A real tender",
            source_url="https://example.co.ke/demo/REAL-001",
            fetched_at=datetime.now(UTC),
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
        )
    )
    real_run = Run(
        user_id=user.id,
        trigger_type=enums.TriggerType.cron_tender,
        trust_level=enums.TrustLevel.untrusted,
        bound_tools=["scrape_tenders"],
        status=enums.RunStatus.succeeded,
        trigger_ref="demo-cycle",  # the exact ref the old reset matched on
        started_at=datetime.now(UTC),
    )
    session.add(real_run)
    await session.flush()
    session.add(
        Approval(
            user_id=user.id,
            run_id=real_run.id,
            module="Leads",
            operation="create",
            proposed_payload={"Company": "A real prospect"},
            expires_at=datetime.now(UTC) + timedelta(hours=48),
        )
    )
    await session.flush()

    await clear_demo_data(session, user.id)

    surviving_emails = (await session.execute(select(Email))).scalars().all()
    assert [e.gmail_message_id for e in surviving_emails] == ["demo-999"]

    surviving_tenders = (await session.execute(select(Tender))).scalars().all()
    assert [t.reference_no for t in surviving_tenders] == ["REAL-001"]

    surviving_runs = (await session.execute(select(Run))).scalars().all()
    assert [r.id for r in surviving_runs] == [real_run.id]

    surviving_approvals = (await session.execute(select(Approval))).scalars().all()
    assert len(surviving_approvals) == 1
    assert surviving_approvals[0].proposed_payload == {"Company": "A real prospect"}


async def test_clearing_is_scoped_to_one_user(session, user) -> None:
    from batanat_api.db.models import User

    other = User(email=f"other-{uuid.uuid4().hex[:8]}@batanat.test", name="Other")
    session.add(other)
    await session.flush()

    await load_demo_data(session, user.id)
    await load_demo_data(session, other.id)

    await clear_demo_data(session, user.id)

    assert (await demo_status(session, user.id))["email"] == 0
    assert (await demo_status(session, other.id))["email"] > 0


async def test_clearing_when_nothing_is_loaded_is_a_no_op(session, user) -> None:
    assert await clear_demo_data(session, user.id) == {
        "approval": 0,
        "run": 0,
        "email": 0,
        "tender": 0,
    }
