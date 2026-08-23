"""One Redis client for the process.

Every module here used to call `from_url(...)` per operation and `aclose()` it
afterwards, which builds and tears down a connection pool for a single GET.
Measured against a local Redis that is 25ms per operation instead of 2ms, and
`sessions.resolve` does two of them on *every authenticated request* — so it
dominated the cost of requests that should have been free. It also churns
sockets, which shows up as TIME_WAIT accumulation long before it shows up as
latency.

redis-py's async client is built to be shared: it holds a pool, it is safe
across concurrent tasks, and one instance per process is the intended shape.

The client is bound to the event loop that first uses it, so `reset()` exists
for tests, which run on their own loop.
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
