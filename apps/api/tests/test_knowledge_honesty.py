"""An upload must not report success it did not achieve.

Three ways this used to say "done" while delivering less:

* A document past the chunk ceiling was **truncated silently**. The response
  reported `characters` for the whole file and a capped `chunk_count`, so the
  knowledge base answered confidently about the part that fit and had no idea
  about the rest — the worst possible failure for a reference document.
* If the vector store rejected every chunk, `remember` swallowed it and the
  upload returned 200. The document appeared in the list, and was never
  retrievable by anything.
* The size limit was enforced after `.read()` had already pulled the whole
  upload into memory.
"""

from __future__ import annotations

import uuid

import pytest

from batanat_api.db import enums
from batanat_api.knowledge import documents


def test_chunking_respects_an_explicit_ceiling() -> None:
    text = "Sentence about switchgear. " * 4000
    assert len(documents.chunk_text(text, size=100, overlap=10, max_chunks=5)) == 5


async def test_a_document_past_the_ceiling_is_refused_not_truncated(
    session, user, monkeypatch
) -> None:
    """Refusing is kinder than half-indexing: the user can split it and retry."""
    monkeypatch.setattr(documents, "MAX_CHUNKS_PER_DOCUMENT", 3)

    async def no_archive(*args, **kwargs):
        return None

    monkeypatch.setattr(documents, "archive", no_archive)

    huge = ("Batanat delivers transmission work across Kenya. " * 200).encode()
    with pytest.raises(documents.DocumentTooLongError, match="Split it"):
        await documents.ingest_document(
            session,
            user_id=user.id,
            filename="handbook.txt",
            content_type="text/plain",
            data=huge,
        )


async def test_an_unindexable_document_fails_rather_than_reporting_success(
    session, user, monkeypatch
) -> None:
    """A document nothing can retrieve is not a knowledge base entry."""
    from batanat_api.db.models import Memory

    async def no_archive(*args, **kwargs):
        return None

    async def remember_without_indexing(session, **kwargs):
        # Mirrors `remember` when Qdrant refuses: the row lands, the point does
        # not, and `qdrant_point_id` stays null.
        memory = Memory(
            user_id=kwargs["user_id"],
            layer=kwargs["layer"],
            trust_tag=kwargs["trust_tag"],
            content=kwargs["content"],
            source_ref=kwargs.get("source_ref"),
            attributes=kwargs.get("attributes") or {},
        )
        session.add(memory)
        await session.flush()
        return memory

    monkeypatch.setattr(documents, "archive", no_archive)
    monkeypatch.setattr(documents, "remember", remember_without_indexing)

    with pytest.raises(documents.IndexingUnavailableError, match="none of it could be indexed"):
        await documents.ingest_document(
            session,
            user_id=user.id,
            filename="profile.txt",
            content_type="text/plain",
            data=b"Batanat Energy builds substations.",
            trust_tag=enums.TrustTag.user_asserted,
        )


async def test_a_summary_reports_how_much_is_actually_searchable(
    session, user, monkeypatch
) -> None:
    """`indexed_chunks` is the honest number; `chunk_count` is the ambition."""
    from batanat_api.db.models import Memory

    calls = {"n": 0}

    async def no_archive(*args, **kwargs):
        return None

    async def remember_half(session, **kwargs):
        memory = Memory(
            user_id=kwargs["user_id"],
            layer=kwargs["layer"],
            trust_tag=kwargs["trust_tag"],
            content=kwargs["content"],
            source_ref=kwargs.get("source_ref"),
            attributes=kwargs.get("attributes") or {},
        )
        session.add(memory)
        await session.flush()
        calls["n"] += 1
        if calls["n"] % 2 == 1:  # every other chunk makes it to Qdrant
            memory.qdrant_point_id = memory.id
            await session.flush()
        return memory

    monkeypatch.setattr(documents, "archive", no_archive)
    monkeypatch.setattr(documents, "remember", remember_half)

    text = ("Batanat delivers substations and mini-grids. " * 200).encode()
    summary = await documents.ingest_document(
        session,
        user_id=user.id,
        filename="partial.txt",
        content_type="text/plain",
        data=text,
    )

    assert summary.chunk_count > 1
    assert 0 < summary.indexed_chunks < summary.chunk_count


async def test_listing_reports_indexed_chunks(session, user) -> None:
    """So a partly indexed document is visible as such, not as a healthy one."""
    from batanat_api.db.models import Memory

    document_id = uuid.uuid4()
    for index in range(3):
        memory = Memory(
            user_id=user.id,
            layer=enums.MemoryLayer.semantic,
            trust_tag=enums.TrustTag.user_asserted,
            content=f"chunk {index}",
            source_ref="document:notes.txt",
            attributes={
                "document_id": str(document_id),
                "filename": "notes.txt",
                "chunk_index": index,
            },
        )
        session.add(memory)
        await session.flush()
        if index == 0:  # only the first reached the vector store
            memory.qdrant_point_id = memory.id
            await session.flush()

    listed = await documents.list_documents(session, user.id)
    entry = next(d for d in listed if d.document_id == document_id)
    assert entry.chunk_count == 3
    assert entry.indexed_chunks == 1
