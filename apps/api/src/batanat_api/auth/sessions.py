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

A deployment constraint follows from Lax, and it is the kind that is discovered
at the worst moment: the API and the web app must share a registrable domain.
`api.example.com` and `app.example.com` are fine. Put the API on a different
domain and the browser will not send this cookie at all — every request arrives
unauthenticated. The alternative is `SameSite=None; Secure`, which re-opens CSRF
and would mean adding token protection to every mutating endpoint. Sharing a
domain is much cheaper. See DEPLOYMENT notes in README.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.core.redis import get_redis

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
#: Generous for a household or an office behind one NAT, useless for a loop.
MAX_REGISTRATIONS_PER_ADDRESS = 5
ATTEMPT_WINDOW_SECONDS = 900


@dataclass(frozen=True, slots=True)
class Session:
    token: str
    user_id: uuid.UUID
    expires_at: datetime


def _key(token: str) -> str:
    return f"{KEY_PREFIX}{token}"


async def create(user_id: uuid.UUID) -> Session:
    """Mint a session. The token is 256 bits of randomness and nothing else."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + SESSION_TTL

    await get_redis().set(_key(token), str(user_id), ex=int(SESSION_TTL.total_seconds()))

    log.info("session.created", user_id=str(user_id))
    return Session(token=token, user_id=user_id, expires_at=expires_at)


async def resolve(token: str | None) -> uuid.UUID | None:
    """Who is this token? None if unknown or expired.

    Sliding expiry: a session in active use is extended, so someone working all
    week is not signed out mid-task.
    """
    if not token:
        return None

    client = get_redis()
    try:
        raw = await client.get(_key(token))
        if raw is None:
            return None
        await client.expire(_key(token), int(SESSION_TTL.total_seconds()))
    except Exception:  # noqa: BLE001 — Redis down must not authenticate anyone
        log.error("session.store_unavailable")
        return None

    try:
        return uuid.UUID(raw.decode() if isinstance(raw, bytes) else raw)
    except ValueError:
        return None


async def destroy(token: str | None) -> None:
    if not token:
        return
    await get_redis().delete(_key(token))
    log.info("session.destroyed")


async def destroy_all_for_user(user_id: uuid.UUID) -> int:
    """Sign a user out everywhere. Used after a password change."""
    client = get_redis()
    removed = 0
    try:
        async for key in client.scan_iter(match=f"{KEY_PREFIX}*"):
            value = await client.get(key)
            if value and (value.decode() if isinstance(value, bytes) else value) == str(user_id):
                await client.delete(key)
                removed += 1
    except Exception:  # noqa: BLE001
        log.warning("session.bulk_destroy_failed")
    return removed


# --- rate limiting -----------------------------------------------------------


async def too_many_attempts(email: str, address: str) -> bool:
    """Count a login attempt; True once either limit is passed."""
    client = get_redis()
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


async def clear_attempts(email: str, address: str) -> None:
    """A successful login resets the counters."""
    try:
        await get_redis().delete(f"login:email:{email.lower()}", f"login:addr:{address}")
    except Exception:  # noqa: BLE001
        pass


async def too_many_registrations(address: str) -> bool:
    """Count a registration attempt from one address; True once past the limit.

    Registration hashes a password with scrypt before it can do anything useful,
    which is ~0.6s of CPU and 32MB of memory *by design* — that cost is the whole
    point of a KDF. On an endpoint that needs no session, it is also a way to
    exhaust a small box with a loop, so the count has to happen before the hash.

    A separate counter from `too_many_attempts` on purpose. Sharing one would let
    a burst of failed logins block a legitimate sign-up from the same office, and
    let sign-ups mask a password-grinding attempt. Keyed only by address: there
    is no account yet, so there is no email worth counting against.
    """
    try:
        client = get_redis()
        count = await client.incr(f"register:addr:{address}")
        if count == 1:
            await client.expire(f"register:addr:{address}", ATTEMPT_WINDOW_SECONDS)
        if count > MAX_REGISTRATIONS_PER_ADDRESS:
            log.warning("register.rate_limited", address=address)
            return True
        return False
    except Exception:  # noqa: BLE001 — Redis down must not stop people signing up
        return False


# --- cookie ------------------------------------------------------------------


def cookie_kwargs() -> dict[str, object]:
    """Cookie flags. Secure is on unless we are plainly on localhost.

    `SameSite=None` forces Secure on regardless: browsers silently discard the
    cookie without it, which looks like a working API and a broken login.
    """
    settings = get_settings()
    public_url = settings.api_public_url
    samesite = settings.session_cookie_samesite

    on_localhost = public_url.startswith("http://localhost") or public_url.startswith("http://127.")

    return {
        "key": COOKIE_NAME,
        "httponly": True,
        "samesite": samesite,
        "secure": samesite == "none" or not on_localhost,
        "max_age": int(SESSION_TTL.total_seconds()),
        "path": "/",
    }
