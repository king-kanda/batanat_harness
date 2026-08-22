"""Raw payload archive.

Mongo holds only what Postgres deliberately does not: the unparsed original of
everything we ingest. Raw Gmail message JSON, HTML snapshots taken before a
scraper touched them, raw tool responses.

Two reasons this is worth its own store. When a parser turns out to be wrong —
and it will, these are government sites — we can reparse history instead of
re-scraping it. And when the agent claims a tender exists, the snapshot is the
evidence.

Every document is keyed by `_id` = the UUID of the Postgres row it belongs to.
That is why ids are generated in the application (see `db.base.uuid_pk`): the
archive write usually happens before the relational insert.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger

log = get_logger(__name__)

RAW_EMAILS = "raw_emails"
RAW_SCRAPES = "raw_scrapes"
RAW_TOOL_RESPONSES = "raw_tool_responses"

COLLECTIONS = (RAW_EMAILS, RAW_SCRAPES, RAW_TOOL_RESPONSES)


@lru_cache(maxsize=1)
def get_mongo_client() -> AsyncMongoClient:
    settings = get_settings()
    return AsyncMongoClient(settings.mongo_url, uuidRepresentation="standard")


def get_mongo_db() -> AsyncDatabase:
    return get_mongo_client()[get_settings().mongo_db]


async def ensure_indexes() -> None:
    """Create the archive's indexes. Idempotent; safe to run at every startup."""
    db = get_mongo_db()
    await db[RAW_EMAILS].create_index([("user_id", 1), ("archived_at", -1)])
    await db[RAW_EMAILS].create_index("gmail_message_id")
    await db[RAW_SCRAPES].create_index([("source", 1), ("archived_at", -1)])
    await db[RAW_SCRAPES].create_index("run_id")
    await db[RAW_TOOL_RESPONSES].create_index([("run_id", 1), ("sequence", 1)])
    await db[RAW_TOOL_RESPONSES].create_index("tool_name")
    log.info("mongo.indexes.ready", collections=list(COLLECTIONS))


async def archive(
    collection: str,
    row_id: uuid.UUID,
    payload: dict[str, Any],
    **metadata: Any,
) -> None:
    """Store a raw payload under the id of the Postgres row it belongs to.

    Upsert rather than insert: re-processing the same Gmail message or
    re-scraping the same page must not fail, and must not duplicate.
    """
    document = {
        **metadata,
        "payload": payload,
        "archived_at": datetime.now(UTC),
    }
    await get_mongo_db()[collection].update_one({"_id": row_id}, {"$set": document}, upsert=True)


async def fetch(collection: str, row_id: uuid.UUID) -> dict[str, Any] | None:
    return await get_mongo_db()[collection].find_one({"_id": row_id})
