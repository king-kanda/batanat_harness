"""The knowledge base: uploaded documents as semantic memory.

A document is extracted to text, split into chunks, embedded, and stored as
`memories` rows with `layer=semantic`. There is no separate table — a document
is just the set of chunks sharing a `document_id` in `attributes`, which keeps
the retrieval path identical to every other semantic memory and avoids a second
source of truth.

The original bytes go to Mongo before anything parses them, same as scraped
HTML: extraction is a guess about a file format, and a guess we can redo is
better than one we cannot.

**Trust is chosen at upload, and the choice is real.** A capability statement
the client wrote is `user_asserted` — it can inform the agent directly. A
tender document from a third party is `untrusted_external` — it is retrievable,
but rendered as quoted data and never as instruction, because a PDF can carry
the same injection text an email can. The UI asks; it does not guess.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Memory
from batanat_api.db.mongo import RAW_TOOL_RESPONSES, archive
from batanat_api.memory.store import remember

log = get_logger(__name__)

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB
#: Chunks are sized for retrieval, not for reading: big enough to carry a whole
#: idea, small enough that a hit returns something specific.
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150
MAX_CHUNKS_PER_DOCUMENT = 200

TEXT_TYPES = {"text/plain", "text/markdown", "text/csv", "application/json", ""}
PDF_TYPES = {"application/pdf"}

SUPPORTED_EXTENSIONS = (".pdf", ".txt", ".md", ".csv", ".json")


class UnsupportedDocumentError(ValueError):
    pass


class EmptyDocumentError(ValueError):
    pass


@dataclass(slots=True)
class DocumentSummary:
    document_id: uuid.UUID
    filename: str
    trust_tag: str
    chunk_count: int
    characters: int
    uploaded_at: datetime


def extract_text(filename: str, content_type: str, data: bytes) -> str:
    """Pull text out of a file. Raises rather than returning something useless."""
    lowered = filename.lower()

    if content_type in PDF_TYPES or lowered.endswith(".pdf"):
        return _extract_pdf(data)

    if content_type in TEXT_TYPES or lowered.endswith((".txt", ".md", ".csv", ".json")):
        return data.decode("utf-8", errors="replace")

    raise UnsupportedDocumentError(
        f"{filename} is not a supported format. Supported: {', '.join(SUPPORTED_EXTENSIONS)}."
    )


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise UnsupportedDocumentError(f"Could not read the PDF: {exc}") from exc

    if reader.is_encrypted:
        # Try the empty password, which covers most "protected" published PDFs.
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            raise UnsupportedDocumentError(
                "That PDF is password-protected. Remove the password and upload it again."
            ) from None

    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 — one bad page should not lose the document
            continue

    text = "\n\n".join(pages)
    if not text.strip():
        raise EmptyDocumentError(
            "No text could be extracted. That usually means the PDF is a scan — it would "
            "need OCR, which this system does not do."
        )
    return text


def normalise(text: str) -> str:
    """Collapse the whitespace that PDF extraction leaves behind."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, *, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split on paragraph boundaries where possible, with a little overlap.

    Overlap matters: a fact that straddles a boundary is otherwise retrievable
    from neither chunk.
    """
    text = normalise(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(text) and len(chunks) < MAX_CHUNKS_PER_DOCUMENT:
        end = min(start + size, len(text))

        if end < len(text):
            # Prefer a paragraph break, then a sentence end, then a space.
            for separator in ("\n\n", ". ", " "):
                found = text.rfind(separator, start + size // 2, end)
                if found != -1:
                    end = found + len(separator)
                    break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break
        start = max(end - overlap, start + 1)

    return chunks


async def ingest_document(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    filename: str,
    content_type: str,
    data: bytes,
    trust_tag: enums.TrustTag = enums.TrustTag.user_asserted,
) -> DocumentSummary:
    """Store a document and index it for semantic retrieval."""
    if len(data) > MAX_FILE_BYTES:
        raise ValueError(
            f"{filename} is {len(data) // 1024 // 1024}MB; the limit is "
            f"{MAX_FILE_BYTES // 1024 // 1024}MB."
        )
    if not data:
        raise EmptyDocumentError(f"{filename} is empty.")

    document_id = uuid.uuid4()
    now = datetime.now(UTC)

    # Archive the original before parsing it, as with every other ingest path.
    await archive(
        RAW_TOOL_RESPONSES,
        document_id,
        {"filename": filename, "content_type": content_type, "size": len(data)},
        user_id=str(user_id),
        kind="knowledge_document",
    )

    text = normalise(extract_text(filename, content_type, data))
    chunks = chunk_text(text)
    if not chunks:
        raise EmptyDocumentError(f"No usable text was found in {filename}.")

    for index, chunk in enumerate(chunks):
        await remember(
            session,
            user_id=user_id,
            content=chunk,
            layer=enums.MemoryLayer.semantic,
            trust_tag=trust_tag,
            source_ref=f"document:{filename}",
            attributes={
                "document_id": str(document_id),
                "filename": filename,
                "content_type": content_type,
                "chunk_index": index,
                "chunk_count": len(chunks),
                "uploaded_at": now.isoformat(),
            },
        )

    log.info(
        "knowledge.ingested",
        document_id=str(document_id),
        filename=filename,
        chunks=len(chunks),
        characters=len(text),
        trust_tag=trust_tag.value,
    )
    return DocumentSummary(
        document_id=document_id,
        filename=filename,
        trust_tag=trust_tag.value,
        chunk_count=len(chunks),
        characters=len(text),
        uploaded_at=now,
    )


async def list_documents(session: AsyncSession, user_id: uuid.UUID) -> list[DocumentSummary]:
    """One row per uploaded document, assembled from its chunks.

    Grouped in Python rather than SQL: a JSONB path built with a bound parameter
    (`attributes ->> 'document_id'`) is not matched by Postgres against the same
    expression in GROUP BY, and the SQL workarounds are less legible than this.
    Only the columns needed for a summary are selected, and documents number in
    the tens.
    """
    rows = (
        await session.execute(
            select(
                Memory.attributes,
                Memory.trust_tag,
                Memory.created_at,
                func.length(Memory.content).label("length"),
            ).where(
                Memory.user_id == user_id,
                Memory.layer == enums.MemoryLayer.semantic,
            )
        )
    ).all()

    grouped: dict[str, dict[str, Any]] = {}
    for attributes, trust_tag, created_at, length in rows:
        document_id = (attributes or {}).get("document_id")
        if not document_id:
            continue  # a semantic memory that did not come from an upload

        entry = grouped.setdefault(
            document_id,
            {
                "filename": (attributes or {}).get("filename") or "(unnamed)",
                "trust_tag": getattr(trust_tag, "value", str(trust_tag)),
                "chunk_count": 0,
                "characters": 0,
                "uploaded_at": created_at,
            },
        )
        entry["chunk_count"] += 1
        entry["characters"] += length or 0
        entry["uploaded_at"] = min(entry["uploaded_at"], created_at)

    return sorted(
        (
            DocumentSummary(
                document_id=uuid.UUID(document_id),
                filename=entry["filename"],
                trust_tag=entry["trust_tag"],
                chunk_count=entry["chunk_count"],
                characters=entry["characters"],
                uploaded_at=entry["uploaded_at"],
            )
            for document_id, entry in grouped.items()
        ),
        key=lambda d: d.uploaded_at,
        reverse=True,
    )


async def delete_document(session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID) -> int:
    """Remove a document and every chunk of it, from Postgres and Qdrant."""
    chunks = (
        (
            await session.execute(
                select(Memory).where(
                    Memory.user_id == user_id,
                    Memory.attributes["document_id"].astext == str(document_id),
                )
            )
        )
        .scalars()
        .all()
    )
    if not chunks:
        return 0

    point_ids = [str(c.qdrant_point_id) for c in chunks if c.qdrant_point_id]
    if point_ids:
        try:
            from batanat_api.memory.store import COLLECTION, _qdrant

            client = _qdrant()
            try:
                await client.delete(collection_name=COLLECTION, points_selector=point_ids)
            finally:
                await client.close()
        except Exception as exc:  # noqa: BLE001 — orphan vectors beat a failed delete
            log.warning("knowledge.vector_delete_failed", error_type=type(exc).__name__)

    await session.execute(
        delete(Memory).where(
            Memory.user_id == user_id,
            Memory.attributes["document_id"].astext == str(document_id),
        )
    )
    await session.flush()

    log.info("knowledge.deleted", document_id=str(document_id), chunks=len(chunks))
    return len(chunks)


def summary_to_dict(summary: DocumentSummary) -> dict[str, Any]:
    return {
        "document_id": str(summary.document_id),
        "filename": summary.filename,
        "trust_tag": summary.trust_tag,
        "chunk_count": summary.chunk_count,
        "characters": summary.characters,
        "uploaded_at": summary.uploaded_at.isoformat(),
    }
