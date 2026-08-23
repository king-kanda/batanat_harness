"""Sessions.

An opaque random token in Redis, keyed to a user id, referenced by an HttpOnly
cookie. Not a JWT: a JWT cannot be revoked without server state anyway, and once
you are keeping server state the token may as well be a random string with
nothing in it to forge or leak.

What that buys, concretely: signing out actually ends the session, and so does
deleting the key. A stolen cookie stops working the moment either happens.

Cookie flags are the usual three and each matters. **HttpOnly** so JavaScript
cannot read it, which is what limits the damage of an XSS bug. **SameSite=Lax**
so it is not sent on cross-site requests, which is CSRF protection for
everything except top-level navigation. **Secure** whenever we are not on
localhost, so it never crosses the wire in clear.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from redis.asyncio import from_url

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger

log = get_logger(__name__)

COOKIE_NAME = "batanat_session"
KEY_PREFIX = "session:"
#: Long enough not to be annoying, short enough that an abandoned laptop is not
#: a standing invitation. Refreshed on use, so an active session does not expire.
SESSION_TTL = timedelta(days=7)

#: Login attempts per email per window, and per address. Both, because limiting
#: only by email lets an attacker spray many accounts, and limiting only by
#: address lets a botnet grind one.
MAX_ATTEMPTS_PER_EMAIL = 10
MAX_ATTEMPTS_PER_ADDRESS = 30
ATTEMPT_WINDOW_SECONDS = 900


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    user_id: uuid.UUID
    expires_at: datetime


def _client():
    return from_url(get_settings().redis_url)


def _key(token: str) -> str:
    return f"{KEY_PREFIX}{token}"


async def create(user_id: uuid.UUID) -> Session:
    """Mint a session. The token is 256 bits of randomness and nothing else."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + SESSION_TTL

    client = _client()
    try:
        await client.set(_key(token), str(user_id), ex=int(SESSION_TTL.total_seconds()))
    finally:
        await client.aclose()

    log.info("session.created", user_id=str(user_id))
    return Session(token=token, user_id=user_id, expires_at=expires_at)


async def resolve(token: str | None) -> uuid.UUID | None:
    """Who is this token? None if unknown or expired.

    Sliding expiry: a session in active use is extended, so someone working all
    week is not signed out mid-task.
    """
    if not token:
        return None

    client = _client()
    try:
        raw = await client.get(_key(token))
        if raw is None:
            return None
        await client.expire(_key(token), int(SESSION_TTL.total_seconds()))
    except Exception:  # noqa: BLE001 — Redis down must not authenticate anyone
        log.error("session.store_unavailable")
        return None
    finally:
        await client.aclose()

    try:
        return uuid.UUID(raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return None


async def destroy(token: str | None) -> None:
    if not token:
        return
    client = _client()
    try:
        await client.delete(_key(token))
    finally:
        await client.aclose()
    log.info("session.destroyed")


async def destroy_all_for_user(user_id: uuid.UUID) -> int:
    """Sign a user out everywhere. Used after a password change."""
    client = _client()
    removed = 0
    try:
        async for key in client.scan_iter(match=f"{KEY_PREFIX}*"):
            value = await client.get(key)
            if value and (value.decode() if isinstance(value, bytes) else value) == str(user_id):
                await client.delete(key)
                removed += 1
    except Exception:  # noqa: BLE001
        log.warning("session.bulk_destroy_failed")
    finally:
        await client.aclose()
    return removed


# --- rate limiting -----------------------------------------------------------


async def too_many_attempts(email: str, address: str) -> bool:
    """Count a login attempt; True once either limit is passed."""
    client = _client()
    try:
        for key, limit in (
            (f"login:email:{email.lower()}", MAX_ATTEMPTS_PER_EMAIL),
            (f"login:addr:{address}", MAX_ATTEMPTS_PER_ADDRESS),
        ):
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, ATTEMPT_WINDOW_SECONDS)
            if count > limit:
                log.warning("login.rate_limited", scope=key.split(":")[1])
                return True
        return False
    except Exception:  # noqa: BLE001 — Redis down must not lock everyone out
        return False
    finally:
        await client.aclose()


async def clear_attempts(email: str, address: str) -> None:
    """A successful login resets the counters."""
    client = _client()
    try:
        await client.delete(f"login:email:{email.lower()}", f"login:addr:{address}")
    except Exception:  # noqa: BLE001
        pass
    finally:
        await client.aclose()


# --- cookie ------------------------------------------------------------------


def cookie_kwargs() -> dict[str, object]:
    """Cookie flags. Secure is on unless we are plainly on localhost."""
    settings = get_settings()
    public_url = settings.api_public_url

    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": "lax",
        "secure": not public_url.startswith("http://localhost")
        and not public_url.startswith("http://127."),
        "max_age": int(SESSION_TTL.total_seconds()),
        "path": "/",
    }
