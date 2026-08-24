"""Notification dispatch.

Channel policy, straight from the PRD, because mixing them up is how a system
becomes noise:

* **WhatsApp is alerts.** Short, templated, deep-linked. Only high-priority
  things interrupt; everything else waits for the digest.
* **Email is reports.** The full HTML, grouped, with every reference number,
  deadline and source link.
* **The web UI is the source of truth.** Both of the above link to a permalink
  that is also the run's activity view.

Two rules that exist because of how this fails in practice:

**Send something even when there is nothing.** A zero-result report is
information; silence is indistinguishable from a broken scraper.

**Every attempt is recorded with a dedupe key.** A retried cycle must not send
the same alert twice, and the key makes that a database guarantee rather than
an intention.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Notification, User, WhatsAppLink
from batanat_api.reports.builder import build_report_email, report_permalink

log = get_logger(__name__)


def dedupe_key(kind: str, channel: str, label: str) -> str:
    return hashlib.sha256(f"{kind}|{channel}|{label}".encode()).hexdigest()[:40]


async def _record(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    channel: enums.NotificationChannel,
    kind: str,
    target: str | None,
    payload: dict[str, Any],
    key: str,
    run_id: uuid.UUID | None = None,
) -> Notification | None:
    """Claim the right to send. Returns None if this was already sent."""
    statement = (
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            run_id=run_id,
            channel=channel,
            kind=kind,
            target=target,
            dedupe_key=key,
            payload=payload,
            status=enums.NotificationStatus.pending,
            created_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(Notification.id)
    )
    inserted = (await session.execute(statement)).scalar_one_or_none()
    if inserted is None:
        log.info("notification.deduped", kind=kind, channel=channel.value)
        return None

    return (
        await session.execute(select(Notification).where(Notification.id == inserted))
    ).scalar_one()


async def _mark(notification: Notification, *, sent: bool, error: str | None = None) -> None:
    notification.attempts += 1
    notification.status = enums.NotificationStatus.sent if sent else enums.NotificationStatus.failed
    notification.error = error
    notification.sent_at = datetime.now(UTC) if sent else None


async def dispatch_tender_report(
    session: AsyncSession, user_id: uuid.UUID, report: dict[str, Any]
) -> dict[str, Any]:
    """Email the report, nudge on WhatsApp, and record both attempts."""
    label = report["label"]
    permalink = report_permalink(label)
    tenders = report.get("tenders", [])
    failed = report.get("failed_sources", [])

    outcome: dict[str, Any] = {"permalink": permalink, "email": None, "whatsapp": None}

    # --- email: the full report, always, even at zero ---
    email_notification = await _record(
        session,
        user_id=user_id,
        channel=enums.NotificationChannel.email,
        kind="tender_report",
        target=None,
        payload={"label": label, "count": len(tenders), "permalink": permalink},
        key=dedupe_key("tender_report", "email", label),
        run_id=uuid.UUID(report["run_id"]) if report.get("run_id") else None,
    )
    if email_notification:
        from batanat_api.notifications.email_sender import configured_recipients

        # Recorded on the notification row so the audit trail says where the
        # report went, not merely that it went.
        recipient_user = (
            await session.execute(select(User).where(User.id == user_id))
        ).scalar_one_or_none()
        recipients = configured_recipients(
            recipient_user.report_to if recipient_user else None,
            recipient_user.report_cc if recipient_user else None,
        )
        email_notification.target = recipients.describe()

        html = build_report_email(report, permalink=permalink)
        sent, error = await send_email(
            user_id=user_id,
            subject=_subject(len(tenders), failed),
            html=html,
            session=session,
        )
        await _mark(email_notification, sent=sent, error=error)
        outcome["email"] = "sent" if sent else f"failed: {error}"
        outcome["email_recipients"] = recipients.describe()

    # --- whatsapp: a nudge, only when there is something to nudge about ---
    if tenders:
        links = (
            (
                await session.execute(
                    select(WhatsAppLink).where(
                        WhatsAppLink.user_id == user_id, WhatsAppLink.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        soonest = next(
            (t["closing_date"][:10] for t in tenders if t.get("closing_date")), "not stated"
        )
        for link in links:
            notification = await _record(
                session,
                user_id=user_id,
                channel=enums.NotificationChannel.whatsapp,
                kind="tender_report_ready",
                target=link.phone_e164,
                payload={"label": label, "count": len(tenders)},
                key=dedupe_key("tender_report_ready", link.phone_e164, label),
            )
            if not notification:
                continue

            sent, error = await send_whatsapp_template(
                link.phone_e164,
                template="tender_report_ready",
                variables=[str(len(tenders)), soonest, permalink],
                fallback_text=(
                    f"{len(tenders)} new tenders. Closing soonest: {soonest}. {permalink}"
                ),
            )
            await _mark(notification, sent=sent, error=error)
            outcome["whatsapp"] = "sent" if sent else f"failed: {error}"

    await session.flush()
    return outcome


def _subject(count: int, failed: list[str]) -> str:
    if count == 0:
        base = "Tender report — nothing new"
    else:
        base = f"Tender report — {count} new"
    return f"{base} ({len(failed)} source(s) unavailable)" if failed else base


async def dispatch_approval_request(
    session: AsyncSession, user_id: uuid.UUID, *, approval_id: uuid.UUID
) -> bool:
    """Ask for a decision on a queued CRM write, on the handset.

    The number in the message is the position in `list_pending`, which is what
    `APPROVE n` resolves against — so the two must be generated from the same
    ordering or the reply approves the wrong record. Both use `list_pending`
    for exactly that reason; nothing here re-sorts.

    Only the position of *this* approval is sent. Listing the whole queue in an
    alert invites replying to a number that has since shifted, and a CRM write
    is not something to be approximately right about.
    """
    from batanat_api.approvals.service import list_pending

    settings = get_settings()
    pending = await list_pending(session, user_id)
    position = next((i for i, a in enumerate(pending, 1) if a.id == approval_id), None)
    if position is None:
        # Already decided, or expired between proposing and alerting.
        log.info("approval.alert_skipped", approval_id=str(approval_id))
        return False

    approval = pending[position - 1]
    permalink = f"{settings.web_public_url.rstrip('/')}/approvals"
    subject = _approval_subject(approval)

    links = (
        (
            await session.execute(
                select(WhatsAppLink).where(
                    WhatsAppLink.user_id == user_id, WhatsAppLink.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )

    any_sent = False
    for link in links:
        notification = await _record(
            session,
            user_id=user_id,
            channel=enums.NotificationChannel.whatsapp,
            kind="approval_request",
            target=link.phone_e164,
            payload={"approval_id": str(approval_id), "position": position},
            key=dedupe_key("approval_request", link.phone_e164, str(approval_id)),
            run_id=approval.run_id,
        )
        if not notification:
            continue

        sent, error = await send_whatsapp_template(
            link.phone_e164,
            template="approval_request",
            variables=[str(position), subject, permalink],
            fallback_text=(
                f"#{position} — {approval.operation} {approval.module}: {subject}\n\n"
                f"Reply APPROVE {position} to write it, or REJECT {position} to discard.\n"
                f"{permalink}"
            ),
        )
        await _mark(notification, sent=sent, error=error)
        any_sent = any_sent or sent

    await session.flush()
    log.info("approval.alert", approval_id=str(approval_id), position=position, sent=any_sent)
    return any_sent


def _approval_subject(approval) -> str:
    """A human-readable handle for the record, for a one-line alert."""
    payload = approval.proposed_payload or {}
    for field in ("Company", "Deal_Name", "Note_Title", "Last_Name", "Email"):
        value = payload.get(field)
        if value:
            return str(value)[:60]
    return approval.record_id or "a new record"


async def dispatch_opportunity_alert(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    email_id: uuid.UUID,
    subject: str | None,
    sender: str | None,
) -> bool:
    """Interrupt for a high-priority email opportunity. Everything else waits."""
    settings = get_settings()
    permalink = f"{settings.web_public_url.rstrip('/')}/results?email={email_id}"

    links = (
        (
            await session.execute(
                select(WhatsAppLink).where(
                    WhatsAppLink.user_id == user_id, WhatsAppLink.is_active.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )

    any_sent = False
    for link in links:
        notification = await _record(
            session,
            user_id=user_id,
            channel=enums.NotificationChannel.whatsapp,
            kind="opportunity_alert",
            target=link.phone_e164,
            payload={"email_id": str(email_id), "subject": subject},
            key=dedupe_key("opportunity_alert", link.phone_e164, str(email_id)),
        )
        if not notification:
            continue

        sent, error = await send_whatsapp_template(
            link.phone_e164,
            template="opportunity_alert",
            variables=[sender or "unknown sender", (subject or "(no subject)")[:60], permalink],
            fallback_text=f"Opportunity from {sender}: {subject}. {permalink}",
        )
        await _mark(notification, sent=sent, error=error)
        any_sent = any_sent or sent

    await session.flush()
    return any_sent


# --- channel implementations -------------------------------------------------


async def send_whatsapp_template(
    to_e164: str, *, template: str, variables: list[str], fallback_text: str
) -> tuple[bool, str | None]:
    """Send an approved utility template.

    Proactive messages outside the 24-hour window must be templates; free text
    is rejected by Meta. The templates need submitting for approval — see
    TODO.md. Until they are approved this falls back to free text, which works
    only inside the window.
    """
    settings = get_settings()
    if not (settings.whatsapp_access_token and settings.whatsapp_phone_number_id):
        return False, "WhatsApp is not configured"

    import httpx

    url = f"https://graph.facebook.com/v21.0/{settings.whatsapp_phone_number_id}/messages"
    body = {
        "messaging_product": "whatsapp",
        "to": to_e164.lstrip("+"),
        "type": "template",
        "template": {
            "name": template,
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": v} for v in variables],
                }
            ],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                json=body,
            )
            # Any 4xx here is the template being unusable — missing, unapproved,
            # or the wrong language. Meta answers 404 for "does not exist in en"
            # and 400 for most of the rest, and checking only 400 meant the
            # fallback never ran for the commonest case of all: a template that
            # has not been submitted yet.
            if 400 <= response.status_code < 500:
                log.warning(
                    "whatsapp.template_rejected",
                    template=template,
                    status_code=response.status_code,
                )
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to": to_e164.lstrip("+"),
                        "type": "text",
                        "text": {"body": fallback_text},
                    },
                )
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"

    if not response.is_success:
        return False, _meta_error(response)
    return True, None


def _meta_error(response: Any) -> str:
    """Meta's own message, not just the status code.

    A bare "HTTP 400" sent us looking for an unapproved template when the real
    answer was sitting in the body: the number needed display-name approval,
    which no amount of template work would have fixed. Graph errors are
    specific and actionable — pass them through.
    """
    try:
        error = response.json().get("error", {})
    except Exception:  # noqa: BLE001
        return f"HTTP {response.status_code}: {response.text[:200]}"

    message = error.get("message") or f"HTTP {response.status_code}"
    details = (error.get("error_data") or {}).get("details")
    return f"{message} ({details})" if details and details not in message else message


async def send_email(
    *, user_id: uuid.UUID, subject: str, html: str, session: AsyncSession
) -> tuple[bool, str | None]:
    """Send the report through SendGrid, to the user's own saved recipients.

    Not through Gmail: that connection is `gmail.readonly` by design, so the
    agent can read the inbox and never send from it.
    """
    from batanat_api.notifications import email_sender

    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        # The run outlived the account. There is no default to fall back to,
        # and inventing one would mail someone else's business elsewhere.
        return False, "No such user, so there is nobody to send the report to."

    return await email_sender.send_email(
        subject=subject, html=html, to_raw=user.report_to, cc_raw=user.report_cc
    )
