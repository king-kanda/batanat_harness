"""OAuth `state` — CSRF protection for the authorization round trip.

The state is a random opaque token held in Redis for ten minutes alongside the
user and provider it belongs to. It is single-use: consuming it deletes it, so a
replayed callback finds nothing and is rejected.

An HMAC-signed self-describing token would avoid the Redis round trip, but it
cannot be revoked or made single-use without server state anyway, so we keep the
state where it can be deleted.
"""

from __future__ import annotations

import json
import secrets
import uuid
from dataclasses import dataclass

from redis.asyncio import Redis, from_url

from batanat_api.config import get_settings
from batanat_api.db import enums

STATE_TTL_SECONDS = 600
KEY_PREFIX = "oauth:state:"


class InvalidStateError(RuntimeError):
    """The callback's state is unknown, expired, or already used."""


@dataclass(frozen=True, slots=True)
class OAuthState:
    user_id: uuid.UUID
    provider: enums.Provider
    return_to: str


def _client() -> Redis:
    return from_url(get_settings().redis_url)


async def issue(user_id: uuid.UUID, provider: enums.Provider, return_to: str) -> str:
    token = secrets.token_urlsafe(32)
    payload = json.dumps(
        {"user_id": str(user_id), "provider": provider.value, "return_to": return_to}
    )
    client = _client()
    try:
        await client.set(f"{KEY_PREFIX}{token}", payload, ex=STATE_TTL_SECONDS)
    finally:
        await client.aclose()
    return token


async def consume(token: str) -> OAuthState:
    """Validate and destroy a state token. Raises if it is not usable."""
    if not token:
        raise InvalidStateError("No state parameter was returned by the provider.")

    client = _client()
    try:
        # GETDEL makes this single-use without a race between read and delete.
        raw = await client.getdel(f"{KEY_PREFIX}{token}")
    finally:
        await client.aclose()

    if raw is None:
        raise InvalidStateError(
            "This authorization link has expired or was already used. Start again."
        )

    data = json.loads(raw)
    return OAuthState(
        user_id=uuid.UUID(data["user_id"]),
        provider=enums.Provider(data["provider"]),
        return_to=data["return_to"],
    )
