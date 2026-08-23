"""Memory.

Three layers, deliberately stored in different places because they are asked
different questions:

* **Procedural** — the active Skill.MD. Always loaded. Postgres.
* **Semantic** — business profile, past deals, uploaded documents. Loaded when
  relevant. Qdrant, because "what do we know about transmission work" is a
  similarity question.
* **Episodic** — runs, emails, tenders. Loaded scoped to the task and the last
  N days. Postgres, queried by predicate. **Tenders are deliberately not
  embedded**: we dedupe by reference number and filter by closing date far more
  often than we search them semantically, and embedding them would add cost and
  a second source of truth for no benefit.

Never load all three wholesale. `assemble()` is the only entry point and it
takes a budget.

Embeddings come from fastembed — ONNX on CPU, ~100MB. Never a torch-backed
model; see the CPU-only constraint.

**The trust rule.** Every row carries a `trust_tag`. `assemble()` splits what it
retrieves into two buckets by that tag, and only the trusted bucket is ever
eligible for the system-prompt position; the other is rendered as quoted data in
the user position, the same as an email body. That separation is the whole of
invariant 4, and there is a test that holds it in place.

Every retrieval path goes through the same split — semantic and episodic alike.
A second path that returned bare strings would be a way to get untrusted content
into the system prompt without anyone noticing, so there isn't one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.config import get_settings
from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Memory

log = get_logger(__name__)

COLLECTION = "batanat_memory"
#: bge-small-en-v1.5 output dimension.
VECTOR_SIZE = 384

#: Memories derived from outside content may never be rendered as instruction.
UNTRUSTED_TAGS = frozenset({enums.TrustTag.untrusted_external})


@dataclass
class RetrievedMemory:
    id: uuid.UUID
    content: str
    layer: enums.MemoryLayer
    trust_tag: enums.TrustTag
    score: float | None = None
    source_ref: str | None = None

    @property
    def is_instruction_eligible(self) -> bool:
        """Only trusted provenance may occupy the system-prompt position."""
        return self.trust_tag not in UNTRUSTED_TAGS


@dataclass
class AssembledMemory:
    """What a run is given, split by how it may be used."""

    procedural: str | None = None
    trusted: list[RetrievedMemory] = field(default_factory=list)
    untrusted: list[RetrievedMemory] = field(default_factory=list)

    def add(self, memory: RetrievedMemory) -> None:
        """File a memory by provenance. The only way into either bucket."""
        target = self.trusted if memory.is_instruction_eligible else self.untrusted
        target.append(memory)

    def system_prompt_lines(self) -> list[str]:
        """Only trusted memories. Untrusted ones are quoted elsewhere, as data."""
        return [m.content for m in self.trusted]

    def quoted_blocks(self) -> list[str]:
        from batanat_api.agent.prompt import wrap_untrusted

        return [
            wrap_untrusted(f"memory from {m.source_ref or 'external content'}", m.content)
            for m in self.untrusted
        ]


@lru_cache(maxsize=1)
def _embedder():
    """Lazily construct the ONNX embedder. First call downloads ~100MB."""
    from fastembed import TextEmbedding

    settings = get_settings()
    log.info("memory.embedder.loading", model=settings.embeddings_model)
    return TextEmbedding(model_name=settings.embeddings_model)


def embed(texts: list[str]) -> list[list[float]]:
    return [vector.tolist() for vector in _embedder().embed(texts)]


def _qdrant():
    from qdrant_client import AsyncQdrantClient

    settings = get_settings()
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)


async def ensure_collection() -> None:
    """Idempotent. Called at startup."""
    from qdrant_client.models import Distance, VectorParams

    client = _qdrant()
    try:
        existing = {c.name for c in (await client.get_collections()).collections}
        if COLLECTION not in existing:
            await client.create_collection(
                collection_name=COLLECTION,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            log.info("memory.collection.created", collection=COLLECTION)
    finally:
        await client.close()


async def remember(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    content: str,
    layer: enums.MemoryLayer,
    trust_tag: enums.TrustTag,
    source_ref: str | None = None,
    attributes: dict[str, Any] | None = None,
    embed_it: bool | None = None,
) -> Memory:
    """Store a memory, and vector-index it when it is semantic.

    Episodic rows are not embedded: they are queried by predicate, not by
    similarity.
    """
    memory = Memory(
        user_id=user_id,
        layer=layer,
        trust_tag=trust_tag,
        content=content.strip(),
        source_ref=source_ref,
        attributes=attributes or {},
    )
    session.add(memory)
    await session.flush()

    should_embed = embed_it if embed_it is not None else layer is enums.MemoryLayer.semantic
    if should_embed:
        try:
            from qdrant_client.models import PointStruct

            vector = embed([memory.content])[0]
            client = _qdrant()
            try:
                await client.upsert(
                    collection_name=COLLECTION,
                    points=[
                        PointStruct(
                            id=str(memory.id),
                            vector=vector,
                            payload={
                                "user_id": str(user_id),
                                "layer": layer.value,
                                "trust_tag": trust_tag.value,
                                "content": memory.content[:2000],
                                "source_ref": source_ref,
                            },
                        )
                    ],
                )
            finally:
                await client.close()
            memory.qdrant_point_id = memory.id
            await session.flush()
        except Exception as exc:  # noqa: BLE001 — a vector index failure is not data loss
            log.warning("memory.embed_failed", error_type=type(exc).__name__)

    return memory


async def search_semantic(
    user_id: uuid.UUID, query: str, *, limit: int = 5, min_score: float = 0.3
) -> list[RetrievedMemory]:
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    try:
        vector = embed([query])[0]
    except Exception as exc:  # noqa: BLE001
        log.warning("memory.query_embed_failed", error_type=type(exc).__name__)
        return []

    client = _qdrant()
    try:
        hits = await client.search(
            collection_name=COLLECTION,
            query_vector=vector,
            query_filter=Filter(
                must=[FieldCondition(key="user_id", match=MatchValue(value=str(user_id)))]
            ),
            limit=limit,
            score_threshold=min_score,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("memory.search_failed", error_type=type(exc).__name__)
        return []
    finally:
        await client.close()

    return [
        RetrievedMemory(
            id=uuid.UUID(str(hit.id)),
            content=hit.payload.get("content", ""),
            layer=enums.MemoryLayer(hit.payload.get("layer", "semantic")),
            trust_tag=enums.TrustTag(hit.payload.get("trust_tag", "untrusted_external")),
            score=hit.score,
            source_ref=hit.payload.get("source_ref"),
        )
        for hit in hits
    ]


async def recent_episodic(
    session: AsyncSession, user_id: uuid.UUID, *, days: int = 7, limit: int = 10
) -> list[RetrievedMemory]:
    """Episodic recall by predicate — date range, not similarity.

    Returns tagged memories, not bare strings, so the caller cannot lose track
    of where each one came from.
    """
    since = datetime.now(UTC) - timedelta(days=days)
    rows = (
        (
            await session.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.layer == enums.MemoryLayer.episodic,
                    Memory.created_at >= since,
                )
                .order_by(Memory.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        RetrievedMemory(
            id=row.id,
            content=row.content,
            layer=row.layer,
            trust_tag=row.trust_tag,
            source_ref=row.source_ref,
        )
        for row in rows
    ]


async def assemble(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    query: str | None = None,
    skill_content: str | None = None,
    semantic_limit: int = 5,
    episodic_days: int = 7,
) -> AssembledMemory:
    """Selective retrieval: procedural always, semantic on relevance, episodic scoped."""
    assembled = AssembledMemory(procedural=skill_content)

    if query:
        for memory in await search_semantic(user_id, query, limit=semantic_limit):
            assembled.add(memory)

    for memory in await recent_episodic(session, user_id, days=episodic_days):
        assembled.add(memory)

    return assembled


async def forget(session: AsyncSession, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
    memory = (
        await session.execute(
            select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id)
        )
    ).scalar_one_or_none()
    if memory is None:
        return False

    if memory.qdrant_point_id:
        try:
            client = _qdrant()
            try:
                await client.delete(
                    collection_name=COLLECTION, points_selector=[str(memory.qdrant_point_id)]
                )
            finally:
                await client.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("memory.vector_delete_failed", error_type=type(exc).__name__)

    await session.delete(memory)
    await session.flush()
    return True
