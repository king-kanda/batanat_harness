"""WhatsApp pairing.

One business number serves every user, so an inbound message is only
attributable if we have previously bound the sender's phone number to a user.
That binding is what the pairing code establishes: the user asks the web app for
a code, then sends it from the handset they want linked. Possession of the
handset is the proof.

Three guardrails, all of which exist because the number is shared:

* **Rate limits.** Code generation per user, and pairing attempts per phone
  number. Without the second, the eight-character space is brute-forceable.
* **Generic replies.** An unrecognised code gets the same answer as an expired
  one. Confirming that a code exists would turn the reply into an oracle.
* **No silent rebinding.** A number already linked to another user is rejected
  outright — otherwise pairing someone else's number would redirect their
  alerts.
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from redis.asyncio import from_url
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.db.models import PairingCode, WhatsAppLink

log = get_logger(__name__)

# No O/0/I/1: these are the characters people mistype when reading a code off a
# screen and typing it into a phone.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8
CODE_TTL = timedelta(minutes=10)

LINK_PATTERN = re.compile(rf"^\s*LINK\s+([A-Z2-9]{{{CODE_LENGTH}}})\s*$", re.IGNORECASE)

MAX_CODES_PER_USER_PER_HOUR = 5
MAX_ATTEMPTS_PER_PHONE_PER_HOUR = 10

GENERIC_FAILURE_REPLY = (
    "That code is not valid. Ask for a new one on the Connections page and send it "
    "again within 10 minutes."
)


class RateLimitedError(RuntimeError):
    """Too many pairing codes or attempts in the window."""


class PairingResult:
    """Outcome of an inbound LINK attempt."""

    def __init__(self, *, linked: bool, reply: str, user_id: uuid.UUID | None = None):
        self.linked = linked
        self.reply = reply
        self.user_id = user_id


@dataclass(frozen=True, slots=True)
class IssuedCode:
    code: str
    expires_at: datetime


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def wa_me_url(business_number: str, code: str) -> str:
    """Deep link that opens WhatsApp with `LINK <CODE>` already typed."""
    digits = business_number.lstrip("+").replace(" ", "")
    return f"https://wa.me/{digits}?text={quote(f'LINK {code}')}"


async def _rate_limit(key: str, limit: int, window_seconds: int = 3600) -> None:
    """Fixed-window counter in Redis. Raises once the limit is passed."""
    client = from_url(get_settings().redis_url)
    try:
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds)
        if count > limit:
            raise RateLimitedError(f"Rate limit reached for {key.split(':')[0]}.")
    finally:
        await client.aclose()


async def issue_code(session: AsyncSession, user_id: uuid.UUID) -> IssuedCode:
    """Create a single-use pairing code for this user."""
    await _rate_limit(f"pairing:issue:{user_id}", MAX_CODES_PER_USER_PER_HOUR)

    now = datetime.now(UTC)
    # Retry on the (vanishingly unlikely) collision with a live code.
    for _ in range(5):
        code = generate_code()
        existing = (
            (await session.execute(select(PairingCode).where(PairingCode.code == code)))
            .scalars()
            .first()
        )
        if existing is None:
            break
    else:  # pragma: no cover - would require five collisions in a row
        raise RuntimeError("Could not allocate a unique pairing code.")

    expires_at = now + CODE_TTL
    session.add(PairingCode(user_id=user_id, code=code, expires_at=expires_at))
    await session.flush()

    log.info("whatsapp.pairing.issued", user_id=str(user_id), expires_at=expires_at.isoformat())
    return IssuedCode(code=code, expires_at=expires_at)


def parse_link_message(body: str) -> str | None:
    """Extract the code from `LINK ABCD2345`, or None if that is not what this is."""
    match = LINK_PATTERN.match(body or "")
    return match.group(1).upper() if match else None


async def redeem_code(
    session: AsyncSession, phone_e164: str, code: str, *, now: datetime | None = None
) -> PairingResult:
    """Bind a phone number to the user who issued this code.

    Every failure returns the same generic reply. The log line records the real
    reason; the sender does not get to learn it.
    """
    now = now or datetime.now(UTC)

    try:
        await _rate_limit(f"pairing:attempt:{phone_e164}", MAX_ATTEMPTS_PER_PHONE_PER_HOUR)
    except RateLimitedError:
        log.warning("whatsapp.pairing.rate_limited", phone=_mask(phone_e164))
        return PairingResult(linked=False, reply=GENERIC_FAILURE_REPLY)

    pairing_code = (
        (await session.execute(select(PairingCode).where(PairingCode.code == code.upper())))
        .scalars()
        .first()
    )

    if pairing_code is None:
        log.info("whatsapp.pairing.unknown_code", phone=_mask(phone_e164))
        return PairingResult(linked=False, reply=GENERIC_FAILURE_REPLY)

    if pairing_code.used_at is not None:
        log.info("whatsapp.pairing.code_already_used", phone=_mask(phone_e164))
        return PairingResult(linked=False, reply=GENERIC_FAILURE_REPLY)

    if pairing_code.expires_at <= now:
        log.info("whatsapp.pairing.code_expired", phone=_mask(phone_e164))
        return PairingResult(linked=False, reply=GENERIC_FAILURE_REPLY)

    existing_link = (
        (await session.execute(select(WhatsAppLink).where(WhatsAppLink.phone_e164 == phone_e164)))
        .scalars()
        .first()
    )

    if existing_link is not None and existing_link.user_id != pairing_code.user_id:
        # Never silently rebind: this would hand another user's alerts to this handset.
        log.warning("whatsapp.pairing.number_belongs_to_another_user", phone=_mask(phone_e164))
        return PairingResult(
            linked=False,
            reply="This number is already linked to a different account. Contact your "
            "administrator if that is wrong.",
        )

    if existing_link is not None:
        existing_link.is_active = True
        existing_link.last_seen_at = now
    else:
        session.add(
            WhatsAppLink(
                user_id=pairing_code.user_id,
                phone_e164=phone_e164,
                linked_at=now,
                last_seen_at=now,
            )
        )

    pairing_code.used_at = now
    pairing_code.used_by_phone = phone_e164
    await session.flush()

    log.info(
        "whatsapp.pairing.linked",
        user_id=str(pairing_code.user_id),
        phone=_mask(phone_e164),
    )
    return PairingResult(
        linked=True,
        user_id=pairing_code.user_id,
        reply="Linked. This number will now receive Batanat alerts.",
    )


async def resolve_user(session: AsyncSession, phone_e164: str) -> uuid.UUID | None:
    """Which user does this sender belong to? None means: do not trust this message."""
    link = (
        (
            await session.execute(
                select(WhatsAppLink).where(
                    WhatsAppLink.phone_e164 == phone_e164, WhatsAppLink.is_active.is_(True)
                )
            )
        )
        .scalars()
        .first()
    )
    return link.user_id if link else None


async def unlink(session: AsyncSession, user_id: uuid.UUID, link_id: uuid.UUID) -> None:
    link = (
        (
            await session.execute(
                select(WhatsAppLink).where(
                    WhatsAppLink.id == link_id, WhatsAppLink.user_id == user_id
                )
            )
        )
        .scalars()
        .first()
    )
    if link is None:
        raise LookupError("No such linked number.")
    link.is_active = False
    await session.flush()
    log.info("whatsapp.pairing.unlinked", user_id=str(user_id), phone=_mask(link.phone_e164))


def _mask(phone: str) -> str:
    """Log the shape of a number, not the number."""
    return f"{phone[:5]}…{phone[-2:]}" if len(phone) > 7 else "…"
