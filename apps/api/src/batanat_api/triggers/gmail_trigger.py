"""What happens when Gmail says something arrived.

Sync first, then run the agent once over whatever is new — not once per message.
The run is `gmail_push`, which means untrusted: read tools and
`propose_crm_entry`, and the email bodies are quoted data. That binding is made
by the trigger type alone, here, before any content is loaded.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Connection, Email, SkillVersion, User
from batanat_api.gmail import sync
from batanat_api.gmail.cleaning import clean_body
from batanat_api.gmail.client import GmailClient

log = get_logger(__name__)


async def resolve_user_by_email(session: AsyncSession, email_address: str) -> uuid.UUID | None:
    """Map the notified mailbox to a user via the connection that owns it."""
    return (
        await session.execute(
            select(Connection.user_id).where(
                Connection.provider == enums.Provider.gmail,
                Connection.external_account == email_address,
                Connection.status != enums.ConnectionStatus.revoked,
            )
        )
    ).scalar_one_or_none()


async def active_skill(session: AsyncSession, user_id: uuid.UUID) -> SkillVersion | None:
    return (
        await session.execute(
            select(SkillVersion).where(
                SkillVersion.user_id == user_id, SkillVersion.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()


async def handle_notification(
    session: AsyncSession, email_address: str, history_id: int | None
) -> dict:
    user_id = await resolve_user_by_email(session, email_address)
    if user_id is None:
        # A notification for a mailbox we do not manage. Not an error.
        log.info("gmail.trigger.unknown_mailbox")
        return {"processed": 0, "reason": "unknown mailbox"}

    result = await sync.sync_incremental(session, user_id, notified_history_id=history_id)
    if not result.email_ids:
        log.info("gmail.trigger.nothing_new")
        return {"processed": 0, "resynced": result.resynced}

    await run_classification(session, user_id, result.email_ids)
    return {"processed": len(result.email_ids), "resynced": result.resynced}


#: How many messages go to the model in one run. Bounded by context, not policy.
BATCH_SIZE = 20

#: Ceiling on a single catch-up sweep, so a long-neglected mailbox cannot turn
#: one button press into hours of model calls. What is left is picked up by the
#: next sweep — the query is "still unclassified", so progress is never lost.
MAX_PER_SWEEP = 200


async def classify_pending(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int = MAX_PER_SWEEP
) -> int:
    """Classify every email that never got a verdict. Returns how many were tried.

    Classification only ever happened to messages arriving through a sync, so
    anything imported by a backfill — the entire inbox at connect time — stayed
    blank forever: the cursor had already moved past it, and nothing anywhere
    looked for `category IS NULL`.

    Oldest first, so a mailbox over the ceiling makes forward progress in
    received order rather than re-examining the same recent slice each time.
    """
    pending = (
        (
            await session.execute(
                select(Email.id)
                .where(Email.user_id == user_id, Email.category.is_(None))
                .order_by(Email.received_at.asc().nulls_last())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if not pending:
        return 0

    log.info("gmail.classify_pending", user_id=str(user_id), count=len(pending))
    await run_classification(session, user_id, list(pending))
    return len(pending)


async def run_classification(
    session: AsyncSession, user_id: uuid.UUID, email_ids: list[uuid.UUID]
) -> None:
    """Classify these emails, in model-sized batches, then alert on the results.

    Chunked rather than truncated. This used to slice `email_ids[:20]` and drop
    the rest silently — with the cursor already advanced, those messages were
    unclassifiable forever, and nothing said so.
    """
    if not email_ids:
        return

    run_ids = []
    for start in range(0, len(email_ids), BATCH_SIZE):
        run_id = await _classify_batch(session, user_id, email_ids[start : start + BATCH_SIZE])
        if run_id is not None:
            run_ids.append(run_id)

    if not run_ids:
        return

    # Alerting runs once over the whole set: the batching is an implementation
    # detail of the model call, not something the user should hear about twice.
    await alert_on_opportunities(session, user_id, email_ids)
    for run_id in run_ids:
        await alert_on_proposals(session, user_id, run_id=run_id)


async def _classify_batch(
    session: AsyncSession, user_id: uuid.UUID, email_ids: list[uuid.UUID]
) -> uuid.UUID | None:
    """One agent run over at most `BATCH_SIZE` messages. None if it did not run."""
    from batanat_api.agent.providers import get_model
    from batanat_api.agent.runner import AgentRunner

    model = get_model()
    if not model.is_configured():
        log.warning(
            "gmail.trigger.no_model",
            detail="No model API key for LLM_PROVIDER; messages stored, not classified.",
        )
        return None

    client = GmailClient(session, user_id)
    payload = []
    for email_id in email_ids:
        email = (
            await session.execute(select(Email).where(Email.id == email_id))
        ).scalar_one_or_none()
        if email is None:
            continue
        try:
            message = await client.get_message(email.gmail_message_id)
            body, _ = clean_body(message.body)
        except Exception:  # noqa: BLE001
            body = email.snippet or ""

        payload.append(
            {
                "email_id": str(email.id),
                "from": email.from_address,
                "subject": email.subject,
                "received_at": email.received_at.isoformat() if email.received_at else None,
                "body": body,
            }
        )

    if not payload:
        # Every id in this batch has since been deleted. Nothing to run.
        return None

    skill = await active_skill(session, user_id)

    # What the business actually does, drawn from the knowledge base. Classifying
    # against Skill.MD alone means the criteria have to restate everything an
    # uploaded capability statement already says — and an upload made precisely
    # to sharpen this decision had no effect on it.
    #
    # Only trusted memory reaches the system position: `system_prompt_lines`
    # returns `user_asserted` and `system_derived` rows, which are the user's own
    # assertions. The untrusted half stays quoted, exactly as the emails do —
    # this is an untrusted trigger and nothing here changes that.
    from batanat_api.memory.store import assemble

    memory = await assemble(
        session,
        user_id,
        query=" ".join(str(item.get("subject") or "") for item in payload)[:500],
        skill_content=skill.content if skill else None,
    )

    result = await AgentRunner(model=model).run(
        session,
        user_id=user_id,
        trigger=enums.TriggerType.gmail_push,
        payload=payload,
        memories=memory.system_prompt_lines(),
        quoted_context=memory.quoted_blocks(),
        instruction=(
            "Classify each email using classify_email. Where a single message is not "
            "enough to judge — a reply with no context, a deadline mentioned earlier — "
            "call read_thread first to see the whole conversation. Where an email is a "
            "genuine business opportunity worth recording, propose a CRM entry. Do not "
            "propose anything for routine correspondence."
        ),
        skill_content=skill.content if skill else None,
        skill_version_id=skill.id if skill else None,
        trigger_ref=f"history:{email_ids[0]}",
    )
    return result.run_id


async def alert_on_proposals(session: AsyncSession, user_id: uuid.UUID, *, run_id) -> int:
    """Ask for a decision on anything this run queued for the CRM.

    This is the middle of the loop the whole system is built around: an email
    arrives, the agent proposes, the handset is asked, and only then is anything
    written. Without it the proposal sits in a queue nobody is told about, and
    `APPROVE 2` means nothing because no number was ever sent.

    Alerted per approval rather than as a digest, so the number in the message
    is the number you reply with.
    """
    from batanat_api.db.models import Approval
    from batanat_api.notifications.dispatcher import dispatch_approval_request

    approvals = (
        (
            await session.execute(
                select(Approval)
                .where(
                    Approval.run_id == run_id,
                    Approval.user_id == user_id,
                    Approval.status == enums.ApprovalStatus.pending,
                )
                .order_by(Approval.created_at.asc())
            )
        )
        .scalars()
        .all()
    )

    sent = 0
    for approval in approvals:
        try:
            if await dispatch_approval_request(session, user_id, approval_id=approval.id):
                sent += 1
        except Exception as exc:  # noqa: BLE001
            # The proposal is queued and visible in the web app either way; a
            # failed alert must not roll back the thing it was announcing.
            log.warning(
                "gmail.approval_alert_failed",
                approval_id=str(approval.id),
                error=type(exc).__name__,
            )

    if approvals:
        log.info("gmail.approval_alerts", queued=len(approvals), sent=sent)
    return sent


async def alert_on_opportunities(
    session: AsyncSession, user_id: uuid.UUID, email_ids: list[uuid.UUID]
) -> int:
    """Interrupt on WhatsApp for anything the run marked a high-priority opportunity.

    Read back from the rows rather than from the model's reply: `classify_email`
    validated the verdict and wrote it, so the database is the only place the
    classification actually exists. Parsing it out of the response would be
    trusting the model twice for one decision.

    Only `high` interrupts. Medium and low wait for the digest — a channel that
    buzzes for everything is a channel that gets muted, and then the one that
    mattered is missed too.
    """
    from batanat_api.notifications.dispatcher import dispatch_opportunity_alert

    rows = (
        (
            await session.execute(
                select(Email).where(
                    Email.id.in_(email_ids),
                    Email.user_id == user_id,
                    Email.category == enums.EmailCategory.opportunity,
                    Email.priority == enums.Priority.high,
                )
            )
        )
        .scalars()
        .all()
    )

    sent = 0
    for email in rows:
        try:
            if await dispatch_opportunity_alert(
                session,
                user_id,
                email_id=email.id,
                subject=email.subject,
                sender=email.from_name or email.from_address,
            ):
                sent += 1
        except Exception as exc:  # noqa: BLE001
            # A failed alert must not lose the classification that earned it.
            log.warning("gmail.alert_failed", email_id=str(email.id), error=type(exc).__name__)

    if rows:
        log.info("gmail.opportunity_alerts", candidates=len(rows), sent=sent)
    return sent


async def sync_now(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """The manual 'Sync now' button.

    Sweeps anything still unclassified as well as what just arrived, so this is
    the button that repairs a mailbox whose backfill never got a verdict.
    """
    result = await sync.sync_incremental(session, user_id)
    if result.email_ids:
        await run_classification(session, user_id, result.email_ids)

    classified = await classify_pending(session, user_id)
    return {
        "new_messages": result.new_messages,
        "already_seen": result.already_seen,
        "resynced": result.resynced,
        "backlog_classified": classified,
    }


async def first_user(session: AsyncSession) -> User | None:
    return (await session.execute(select(User).order_by(User.created_at))).scalars().first()
