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


async def run_classification(
    session: AsyncSession, user_id: uuid.UUID, email_ids: list[uuid.UUID]
) -> None:
    """One agent run over the batch of new messages."""
    from batanat_api.agent.providers import get_model
    from batanat_api.agent.runner import AgentRunner

    model = get_model()
    if not model.is_configured():
        log.warning(
            "gmail.trigger.no_model",
            detail="No model API key for LLM_PROVIDER; messages stored, not classified.",
        )
        return

    client = GmailClient(session, user_id)
    payload = []
    for email_id in email_ids[:20]:
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

    skill = await active_skill(session, user_id)

    await AgentRunner(model=model).run(
        session,
        user_id=user_id,
        trigger=enums.TriggerType.gmail_push,
        payload=payload,
        instruction=(
            "Classify each email using classify_email. Where an email is a genuine "
            "business opportunity worth recording, propose a CRM entry. Do not propose "
            "anything for routine correspondence."
        ),
        skill_content=skill.content if skill else None,
        skill_version_id=skill.id if skill else None,
        trigger_ref=f"history:{email_ids[0]}",
    )


async def sync_now(session: AsyncSession, user_id: uuid.UUID) -> dict:
    """The manual 'Sync now' button."""
    result = await sync.sync_incremental(session, user_id)
    if result.email_ids:
        await run_classification(session, user_id, result.email_ids)
    return {
        "new_messages": result.new_messages,
        "already_seen": result.already_seen,
        "resynced": result.resynced,
    }


async def first_user(session: AsyncSession) -> User | None:
    return (await session.execute(select(User).order_by(User.created_at))).scalars().first()
