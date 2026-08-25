"""Dedupe is a database guarantee, not application logic.

Gmail Pub/Sub delivers at least once and out of order; a re-sync after an
expired historyId re-walks messages we already have; the tender cron re-sees
every open tender twice a day. Each of these is a duplicate the schema must
refuse. These tests are the proof, and they run against real Postgres because
partial unique indexes are the mechanism.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from batanat_api.db import enums
from batanat_api.db.models import (
    Approval,
    Email,
    Feedback,
    Notification,
    Run,
    SkillVersion,
    Tender,
    ToolCall,
    WhatsAppLink,
)

NOW = datetime.now(UTC)


def _email(user_id, message_id: str = "msg-1", **kw) -> Email:
    return Email(user_id=user_id, gmail_message_id=message_id, subject="Tender invitation", **kw)


def _tender(**kw) -> Tender:
    defaults = dict(
        source="kplc",
        title="Supply of 33kV switchgear",
        source_url="https://kplc.co.ke/tender/1",
        fetched_at=NOW,
        first_seen_at=NOW,
    )
    return Tender(**{**defaults, **kw})


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# --- emails ------------------------------------------------------------------


async def test_the_same_gmail_message_cannot_be_stored_twice(session, user) -> None:
    session.add(_email(user.id, "msg-abc"))
    await session.commit()

    session.add(_email(user.id, "msg-abc"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_the_same_message_id_for_a_different_user_is_fine(session, user) -> None:
    from batanat_api.db.models import User

    other = User(email=f"other-{uuid.uuid4().hex[:6]}@batanat.test")
    session.add(other)
    await session.flush()

    session.add(_email(user.id, "shared-id"))
    session.add(_email(other.id, "shared-id"))
    await session.commit()  # must not raise


async def test_at_least_once_delivery_is_absorbed_by_upsert(session, user) -> None:
    """The real ingestion path: ON CONFLICT DO NOTHING, driven by the constraint."""
    statement = (
        insert(Email)
        .values(
            id=uuid.uuid4(),
            user_id=user.id,
            gmail_message_id="dup-me",
            subject="first",
            created_at=NOW,
            updated_at=NOW,
        )
        .on_conflict_do_nothing(index_elements=["user_id", "gmail_message_id"])
    )
    await session.execute(statement)
    await session.execute(statement)
    await session.commit()

    rows = (
        (await session.execute(select(Email).where(Email.gmail_message_id == "dup-me")))
        .scalars()
        .all()
    )
    assert len(rows) == 1


# --- tenders -----------------------------------------------------------------


async def test_same_source_and_reference_number_collides(session) -> None:
    session.add(_tender(reference_no="KP1/9A.2/PT/1/24"))
    await session.commit()

    session.add(_tender(reference_no="KP1/9A.2/PT/1/24", title="Re-advertised"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_the_same_reference_from_a_different_source_is_a_different_tender(session) -> None:
    session.add(_tender(source="kplc", reference_no="REF-1"))
    session.add(_tender(source="kengen", reference_no="REF-1"))
    await session.commit()  # must not raise


async def test_sources_without_a_reference_number_fall_back_to_a_content_hash(session) -> None:
    digest = _hash("kplc", "Supply of 33kV switchgear", "2026-09-01")
    session.add(_tender(reference_no=None, content_hash=digest))
    await session.commit()

    session.add(_tender(reference_no=None, content_hash=digest, title="same thing, restyled"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_two_referenceless_tenders_with_different_content_coexist(session) -> None:
    session.add(_tender(reference_no=None, content_hash=_hash("a")))
    session.add(_tender(reference_no=None, content_hash=_hash("b")))
    await session.commit()  # must not raise


async def test_null_reference_numbers_do_not_collide_with_each_other(session) -> None:
    """A plain UNIQUE(source, reference_no) would allow unlimited NULL rows.

    The partial index is what makes the fallback hash meaningful, so this is
    the test that would catch someone 'simplifying' it later.
    """
    session.add(_tender(reference_no=None, content_hash=_hash("x")))
    session.add(_tender(reference_no=None, content_hash=_hash("y")))
    session.add(_tender(reference_no=None, content_hash=_hash("z")))
    await session.commit()

    count = len((await session.execute(select(Tender))).scalars().all())
    assert count == 3


async def test_a_tender_must_have_a_reference_or_a_hash(session) -> None:
    session.add(_tender(reference_no=None, content_hash=None))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_rescraping_an_unchanged_tender_updates_rather_than_duplicates(session) -> None:
    """Twice-daily cron: second sighting bumps last_seen_at, creates nothing."""
    values = dict(
        id=uuid.uuid4(),
        source="kplc",
        reference_no="KP1/RE/2",
        title="Solar mini-grid EPC",
        source_url="https://kplc.co.ke/t/2",
        fetched_at=NOW,
        first_seen_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    await session.execute(insert(Tender).values(**values))

    later = NOW + timedelta(hours=6)
    await session.execute(
        insert(Tender)
        .values({**values, "id": uuid.uuid4(), "fetched_at": later, "first_seen_at": later})
        .on_conflict_do_update(
            index_elements=["source", "reference_no"],
            index_where=Tender.reference_no.isnot(None),
            set_={"last_seen_at": later, "fetched_at": later},
        )
    )
    await session.commit()

    rows = (await session.execute(select(Tender))).scalars().all()
    assert len(rows) == 1
    assert rows[0].first_seen_at == NOW  # the original sighting is preserved
    assert rows[0].last_seen_at == later


# --- everything else that must not duplicate ---------------------------------


async def test_a_phone_number_cannot_be_linked_to_two_users(session, user) -> None:
    """Otherwise pairing someone else's number would capture their alerts."""
    from batanat_api.db.models import User

    other = User(email=f"other-{uuid.uuid4().hex[:6]}@batanat.test")
    session.add(other)
    await session.flush()

    session.add(WhatsAppLink(user_id=user.id, phone_e164="+254700000001", linked_at=NOW))
    await session.commit()

    session.add(WhatsAppLink(user_id=other.id, phone_e164="+254700000001", linked_at=NOW))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_only_one_skill_version_can_be_active_per_user(session, user) -> None:
    session.add(SkillVersion(user_id=user.id, version=1, content="a", checksum="x", is_active=True))
    await session.commit()

    session.add(SkillVersion(user_id=user.id, version=2, content="b", checksum="y", is_active=True))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_inactive_skill_versions_accumulate_freely(session, user) -> None:
    for version in range(1, 4):
        session.add(
            SkillVersion(
                user_id=user.id, version=version, content="v", checksum="c", is_active=False
            )
        )
    await session.commit()  # must not raise


async def test_skill_version_numbers_are_unique_per_user(session, user) -> None:
    session.add(SkillVersion(user_id=user.id, version=1, content="a", checksum="x"))
    await session.commit()
    session.add(SkillVersion(user_id=user.id, version=1, content="b", checksum="y"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_a_notification_dedupe_key_is_used_once(session, user) -> None:
    """Stops a retried run from sending the same WhatsApp alert twice."""
    for _ in range(2):
        session.add(
            Notification(
                user_id=user.id,
                channel=enums.NotificationChannel.whatsapp,
                kind="tender_report_ready",
                dedupe_key="report:2026-08-23-1100",
            )
        )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_feedback_is_one_vote_per_subject(session, user) -> None:
    subject = uuid.uuid4()
    session.add(
        Feedback(
            user_id=user.id,
            subject_type="tender",
            subject_id=subject,
            rating=enums.FeedbackRating.up,
        )
    )
    await session.commit()

    session.add(
        Feedback(
            user_id=user.id,
            subject_type="tender",
            subject_id=subject,
            rating=enums.FeedbackRating.down,
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_tool_call_sequence_is_unique_within_a_run(session, user) -> None:
    run = Run(
        user_id=user.id,
        trigger_type=enums.TriggerType.cron_tender,
        trust_level=enums.TrustLevel.untrusted,
        bound_tools=["scrape_tenders"],
        started_at=NOW,
    )
    session.add(run)
    await session.flush()

    for _ in range(2):
        session.add(ToolCall(run_id=run.id, sequence=1, tool_name="scrape_tenders", started_at=NOW))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleting_a_run_takes_its_audit_trail_with_it(session, user) -> None:
    run = Run(
        user_id=user.id,
        trigger_type=enums.TriggerType.web_chat,
        trust_level=enums.TrustLevel.trusted,
        bound_tools=[],
        started_at=NOW,
    )
    session.add(run)
    await session.flush()
    session.add(ToolCall(run_id=run.id, sequence=1, tool_name="crm_read", started_at=NOW))
    await session.commit()

    await session.delete(run)
    await session.commit()

    assert (await session.execute(select(ToolCall))).scalars().all() == []


async def test_an_approval_keeps_the_payload_exactly_as_proposed(session, user) -> None:
    """What gets executed must be what was reviewed — including odd types."""
    payload = {
        "Company": "Kenya Power",
        "Amount": 1234567.89,
        "Tags": ["solar", "epc"],
        "Nested": {"County": "Nakuru", "Confirmed": False},
    }
    approval = Approval(
        user_id=user.id,
        module="Leads",
        operation="create",
        proposed_payload=payload,
        diff={"Company": {"current": None, "proposed": "Kenya Power"}},
        expires_at=NOW + timedelta(hours=48),
    )
    session.add(approval)
    await session.commit()
    await session.refresh(approval)

    assert approval.proposed_payload == payload
    assert approval.status is enums.ApprovalStatus.pending


# --- clearing the email list ---------------------------------------------------


async def test_clearing_emails_removes_their_votes_too(session, user) -> None:
    """Feedback references emails by id with no foreign key.

    Left behind, the rows point at nothing and quietly skew `make eval` — a
    precision figure computed against labels whose subjects no longer exist.
    """
    import uuid as _uuid
    from datetime import UTC, datetime

    from sqlalchemy import delete, func, select

    from batanat_api.db.models import Email, Feedback

    email = Email(
        user_id=user.id,
        gmail_message_id=f"msg-{_uuid.uuid4().hex[:8]}",
        gmail_thread_id="thread-1",
        subject="Invitation to tender",
        received_at=datetime.now(UTC),
    )
    session.add(email)
    await session.flush()

    session.add(
        Feedback(
            user_id=user.id,
            subject_type="email",
            subject_id=email.id,
            rating=enums.FeedbackRating.up,
        )
    )
    await session.commit()

    # What the endpoint does.
    ids = (await session.execute(select(Email.id).where(Email.user_id == user.id))).scalars().all()
    await session.execute(
        delete(Feedback).where(
            Feedback.user_id == user.id,
            Feedback.subject_type == "email",
            Feedback.subject_id.in_(ids),
        )
    )
    await session.execute(delete(Email).where(Email.user_id == user.id))
    await session.commit()

    assert (
        await session.execute(
            select(func.count()).select_from(Email).where(Email.user_id == user.id)
        )
    ).scalar() == 0
    assert (
        await session.execute(
            select(func.count()).select_from(Feedback).where(Feedback.user_id == user.id)
        )
    ).scalar() == 0


async def test_clearing_leaves_tender_votes_alone(session, user) -> None:
    """Only email feedback goes. A tender vote is a different subject type."""
    import uuid as _uuid

    from sqlalchemy import delete, func, select

    from batanat_api.db.models import Email, Feedback

    tender_vote = Feedback(
        user_id=user.id,
        subject_type="tender",
        subject_id=_uuid.uuid4(),
        rating=enums.FeedbackRating.down,
    )
    session.add(tender_vote)
    await session.commit()

    ids = (await session.execute(select(Email.id).where(Email.user_id == user.id))).scalars().all()
    await session.execute(
        delete(Feedback).where(
            Feedback.user_id == user.id,
            Feedback.subject_type == "email",
            Feedback.subject_id.in_(ids),
        )
    )
    await session.commit()

    assert (
        await session.execute(
            select(func.count()).select_from(Feedback).where(Feedback.user_id == user.id)
        )
    ).scalar() == 1
