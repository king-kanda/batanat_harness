"""One Redis client for the process.

Callers used to build and tear down a pool per operation — 25ms instead of 2ms
against a local Redis, twice on every authenticated request. redis-py's async
client is designed to be shared; one per process is the intended shape.

It binds to the event loop that first uses it, hence `reset()` for tests.
"""

from __future__ import annotations

from redis.asyncio import Redis, from_url

from batanat_api.config import get_settings

_client: Redis | None = None
_url: str | None = None


def get_redis() -> Redis:
    """The shared client. Do not close it — the app closes it at shutdown."""
    global _client, _url

    url = get_settings().redis_url
    if _client is None or _url != url:
        # The URL changing mid-process only happens in tests, but rebuilding on
        # it is cheaper than a confusing connection to the wrong database.
        _client = from_url(url)
        _url = url
    return _client


async def close_redis() -> None:
    """Release the pool. Called from the app's lifespan shutdown."""
    global _client, _url

    if _client is not None:
        await _client.aclose()
        _client = None
        _url = None


def reset() -> None:
    """Forget the cached client without closing it. Tests only."""
    global _client, _url
    _client = None
    _url = None
