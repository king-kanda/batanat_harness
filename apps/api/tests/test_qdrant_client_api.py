"""The Qdrant methods we call must exist on the installed client.

`search_semantic` called `client.search`, which the client removed in favour of
`query_points`. The call raised `AttributeError`, a broad `except Exception`
caught it, and the function returned an empty list — so semantic recall answered
"nothing found" to every question. Uploads still parsed, chunked, embedded and
indexed correctly; nothing was ever read back. Retrieval had no test because
retrieving requires a live Qdrant, and the failure looked exactly like an empty
knowledge base.

This asserts the surface instead of the behaviour: no server needed, and it
fails the moment a dependency bump removes a method we depend on. `>=1.12` in
pyproject is a floor with no ceiling, so that bump arrives on its own.
"""

from __future__ import annotations

import pytest
from qdrant_client import AsyncQdrantClient

#: Every method `memory.store` and `knowledge.documents` call on the client.
REQUIRED_METHODS = (
    "query_points",
    "upsert",
    "delete",
    "get_collections",
    "create_collection",
    "close",
)


@pytest.mark.parametrize("method", REQUIRED_METHODS)
def test_the_client_still_has_the_method_we_call(method: str) -> None:
    assert hasattr(AsyncQdrantClient, method), (
        f"qdrant-client no longer exposes `{method}`. Semantic memory calls it, and the "
        "call site degrades to an empty result rather than raising — so this test is the "
        "only thing standing between a removal and a knowledge base that silently "
        "returns nothing."
    )


def test_search_is_gone_so_nothing_reaches_for_it_again() -> None:
    """Pins the reason `query_points` is used, so it is not 'simplified' back."""
    assert not hasattr(AsyncQdrantClient, "search")


def test_query_points_accepts_the_arguments_we_pass() -> None:
    """A renamed parameter fails the same way a renamed method does."""
    import inspect

    parameters = inspect.signature(AsyncQdrantClient.query_points).parameters
    for name in ("collection_name", "query", "query_filter", "limit", "score_threshold"):
        assert name in parameters, f"query_points no longer accepts `{name}`"
