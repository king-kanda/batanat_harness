"""WhatsApp Cloud API webhook.

Meta signs every delivery with HMAC-SHA256 over the raw body, keyed by the app
secret. We verify that before parsing, and compare with `compare_digest` — an
early-exit comparison here would leak the expected signature a byte at a time.

The endpoint always answers 200 once the signature checks out, even when
handling fails. Meta retries non-2xx deliveries aggressively, and a retry storm
against a message we cannot process helps nobody; the failure goes to the log
instead.

An inbound message from an unpaired number is *not* an error and is not
processed as a user instruction — it gets the generic reply. This is where
untrusted input enters the system, so the rule is simple: no phone-number
binding, no attribution, no action.

Deliveries are claimed by message id before they are handled. Meta redelivers,
and once replying APPROVE can commit a CRM write, a redelivered message must
not commit it twice.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status

from batanat_api.approvals import service as approvals
from batanat_api.config import get_settings
from batanat_api.connections import whatsapp as pairing
from batanat_api.core.deps import SessionDep
from batanat_api.core.logging import get_logger
from batanat_api.webhooks.idempotency import claim

log = get_logger(__name__)

router = APIRouter(prefix="/api/webhooks/whatsapp", tags=["webhooks"])

UNPAIRED_REPLY = (
    "This number is not linked to a Batanat account. Open Settings → Connections "
    "in the web app to get a pairing code."
)


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    """Constant-time check of Meta's `X-Hub-Signature-256` header."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.get("", include_in_schema=False, summary="Meta webhook verification handshake")
async def verify(
    mode: str | None = Query(default=None, alias="hub.mode"),
    token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    settings = get_settings()
    if mode == "subscribe" and token and settings.whatsapp_verify_token:
        if hmac.compare_digest(token, settings.whatsapp_verify_token):
            return Response(content=challenge or "", media_type="text/plain")
    log.warning("whatsapp.webhook.verification_failed")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Verification failed.")


@router.post("", include_in_schema=False, summary="Inbound WhatsApp messages")
async def inbound(
    request: Request,
    session: SessionDep,
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> Response:
    settings = get_settings()
    raw_body = await request.body()

    if not settings.whatsapp_app_secret:
        log.error("whatsapp.webhook.no_app_secret")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook is not configured.")

    if not verify_signature(raw_body, signature, settings.whatsapp_app_secret):
        log.warning("whatsapp.webhook.bad_signature")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature.")

    try:
        payload = await request.json()
        for message, sender in iter_messages(payload):
            if not await claim(session, "whatsapp", message.get("id", "")):
                continue
            await handle_message(session, sender, message)
    except Exception as exc:  # noqa: BLE001
        # Answer 200 anyway: a retry will not fix a parse error, and Meta
        # retries hard.
        log.exception("whatsapp.webhook.handling_failed", error_type=type(exc).__name__)

    return Response(status_code=200)


def iter_messages(payload: dict[str, Any]):
    """Walk Meta's nested envelope, yielding (message, sender) pairs."""
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for message in value.get("messages", []) or []:
                sender = message.get("from")
                if sender:
                    yield message, _to_e164(sender)


def _to_e164(raw: str) -> str:
    """Meta sends bare digits; the database stores E.164."""
    digits = raw.strip().lstrip("+")
    return f"+{digits}"


async def handle_message(session: SessionDep, sender: str, message: dict[str, Any]) -> None:
    body = (message.get("text") or {}).get("body", "")

    code = pairing.parse_link_message(body)
    if code:
        result = await pairing.redeem_code(session, sender, code)
        await send_text(sender, result.reply)
        return

    user_id = await pairing.resolve_user(session, sender)
    if user_id is None:
        # Untrusted, unattributable. Do not treat the text as an instruction.
        log.info("whatsapp.inbound.unpaired_sender")
        await send_text(sender, UNPAIRED_REPLY)
        return

    log.info("whatsapp.inbound.received", user_id=str(user_id), length=len(body))

    # Approvals are parsed, never reasoned about. `parse_decision_reply` accepts
    # APPROVE/REJECT plus an index and nothing else, so the only way to commit a
    # CRM write from WhatsApp is to answer a question we already asked. Routing
    # this through the model instead would make "talk it into approving" a
    # viable attack against whoever holds the handset.
    decision = approvals.parse_decision_reply(body)
    if decision is not None:
        reply = await approvals.apply_decision_reply(session, user_id, *decision)
        await send_reply(sender, reply)
        return

    await _chat(session, user_id, sender, body)


async def _chat(session: SessionDep, user_id, sender: str, body: str) -> None:
    """A conversational turn, on the same threads as the web chat.

    Bound to `whatsapp_inbound`, which does **not** carry `approve_pending` —
    see `agent/capabilities.py`. Chat and approval are deliberately different
    doors: this one can read and propose, and cannot commit.
    """
    from batanat_api.agent import conversations
    from batanat_api.agent import skill as skill_service
    from batanat_api.agent.providers import get_model
    from batanat_api.agent.runner import AgentRunner, KillSwitchEngagedError
    from batanat_api.db import enums
    from batanat_api.memory.store import assemble

    model = get_model()
    if not model.is_configured():
        await send_reply(sender, "The assistant is not configured to answer right now.")
        return

    # Continue the user's current thread if there is a recent one — including
    # a thread started in the web app. Same assistant, same conversation.
    resumed = await conversations.latest_for_user(session, user_id)
    conversation = await conversations.get_or_create(session, user_id, resumed, first=body)
    window = await conversations.replay_window(session, conversation.id)

    # Same criteria and same knowledge as the web app. This ran with neither
    # before: no Skill.MD and no semantic memory, so the identical question
    # asked from a handset went to an agent working from nothing — which reads
    # as the model being unreliable rather than as missing context.
    active = await skill_service.get_active(session, user_id)
    memory = await assemble(
        session, user_id, query=body, skill_content=active.content if active else None
    )

    try:
        result = await AgentRunner(model=model).run(
            session,
            user_id=user_id,
            trigger=enums.TriggerType.whatsapp_inbound,
            instruction=body,
            skill_content=active.content if active else None,
            skill_version_id=active.id if active else None,
            memories=memory.system_prompt_lines(),
            # Untrusted-derived memory travels as quoted data, never as
            # instruction — the same split the web app makes.
            quoted_context=memory.quoted_blocks(),
            history=window.messages,
            trigger_ref=str(conversation.id),
        )
    except KillSwitchEngagedError:
        await send_reply(sender, "The assistant is paused. Nothing was actioned.")
        return

    # A reply that drew on untrusted memory carries that provenance forward, so
    # replaying it later keeps quoting rather than asserting.
    reply_trust = (
        enums.TrustTag.untrusted_external
        if memory.quoted_blocks()
        else enums.TrustTag.system_derived
    )
    await conversations.record_turn(
        session,
        conversation,
        user_message=body,
        reply=result.output,
        run_id=result.run_id,
        reply_trust=reply_trust,
    )

    await send_reply(sender, result.output or "No answer this time.")


async def send_reply(to_e164: str, body: str) -> bool:
    """Send a reply, split into phone-sized messages.

    A wall of text is unreadable on a handset whether or not Meta accepts it,
    so long answers go out as a short sequence rather than one block.
    """
    from batanat_api.notifications.chunking import split_for_whatsapp

    parts = split_for_whatsapp(body)
    if not parts:
        return False

    ok = True
    for part in parts:
        # Sequential, not gathered: WhatsApp orders by arrival, and a reply
        # whose second half lands first is worse than a slow one.
        ok = await send_text(to_e164, part) and ok
    return ok


async def send_text(to_e164: str, body: str) -> bool:
    """Send a plain text reply through the Cloud API.

    Free-form text is only deliverable inside the 24-hour customer service
    window, which a pairing reply is always within. Proactive alerts must use an
    approved template — see TODO.md.
    """
    import httpx

    settings = get_settings()
    if not (settings.whatsapp_access_token and settings.whatsapp_phone_number_id):
        log.warning("whatsapp.send.not_configured")
        return False

    url = f"https://graph.facebook.com/v21.0/{settings.whatsapp_phone_number_id}/messages"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to_e164.lstrip("+"),
                    "type": "text",
                    "text": {"body": body},
                },
            )
    except Exception as exc:  # noqa: BLE001
        log.error("whatsapp.send.failed", error_type=type(exc).__name__)
        return False

    if not response.is_success:
        log.error("whatsapp.send.rejected", status_code=response.status_code)
        return False
    return True
