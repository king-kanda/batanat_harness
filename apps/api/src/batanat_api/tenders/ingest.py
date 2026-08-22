"""Turning source reports into rows, without ever creating a duplicate.

The twice-daily cron re-sees every open tender. A retried run re-sees them
again. Dedupe is therefore not a nice-to-have and — per the architecture
invariants — it is not application logic either: it is `ON CONFLICT` against
the partial unique indexes defined in phase 1.

Two identities, matching the two indexes:

* `(source, reference_no)` when the site publishes a reference number.
* `(source, content_hash)` when it does not.

A second sighting updates `last_seen_at` and leaves `first_seen_at` alone, so
"new since the last run" stays answerable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Tender, TenderSourceRow
from batanat_api.tenders.base import RawTender, SourceReport, content_hash
from batanat_api.tenders.normalize import parse_date, parse_money

log = get_logger(__name__)


@dataclass
class IngestResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    tender_ids: list[uuid.UUID] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.tender_ids is None:
            self.tender_ids = []


def to_row_values(
    raw: RawTender, *, source_key: str, run_id: uuid.UUID | None, now: datetime
) -> dict | None:
    """Normalise one raw tender into column values, or None if it is unusable."""
    title = " ".join(raw.title.split())
    if not title:
        return None

    closing = parse_date(raw.closing_text)
    amount, currency = parse_money(raw.value_text)

    reference = raw.reference_no
    digest = None if reference else content_hash(source_key, title, raw.closing_text)

    return {
        "id": uuid.uuid4(),
        "source": source_key,
        "reference_no": reference,
        "content_hash": digest,
        "title": title[:2000],
        "entity": raw.entity,
        "category": raw.category,
        "closing_date": closing,
        "estimated_value": amount,
        "currency": currency,
        "source_url": raw.source_url,
        "county": raw.county,
        "fetched_at": now,
        "first_seen_at": now,
        "first_seen_run_id": run_id,
        "last_seen_at": now,
        "created_at": now,
        "updated_at": now,
    }


async def ingest_report(
    session: AsyncSession,
    report: SourceReport,
    *,
    run_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Persist one source's findings. Idempotent by construction."""
    now = now or datetime.now(UTC)
    result = IngestResult()

    for raw in report.tenders:
        values = to_row_values(raw, source_key=report.source_key, run_id=run_id, now=now)
        if values is None:
            result.skipped += 1
            continue

        # Update-on-conflict against whichever index applies to this row.
        if values["reference_no"]:
            conflict = dict(
                index_elements=["source", "reference_no"],
                index_where=Tender.reference_no.isnot(None),
            )
        else:
            conflict = dict(
                index_elements=["source", "content_hash"],
                index_where=Tender.reference_no.is_(None),
            )

        statement = (
            insert(Tender)
            .values(**values)
            .on_conflict_do_update(
                **conflict,
                set_={
                    "last_seen_at": now,
                    "fetched_at": now,
                    "updated_at": now,
                    # Keep the newest title and closing date: sites amend both.
                    "title": values["title"],
                    "closing_date": values["closing_date"],
                    "source_url": values["source_url"],
                },
            )
            .returning(Tender.id, Tender.first_seen_at)
        )

        row = (await session.execute(statement)).one()
        result.tender_ids.append(row.id)
        if row.first_seen_at == now:
            result.created += 1
        else:
            result.updated += 1

    log.info(
        "tenders.ingested",
        source=report.source_key,
        created=result.created,
        updated=result.updated,
        skipped=result.skipped,
    )
    return result


async def record_source_health(
    session: AsyncSession, report: SourceReport, *, now: datetime | None = None
) -> None:
    """Keep `tender_sources` honest, so the UI can show which sites are working."""
    now = now or datetime.now(UTC)
    source = (
        (
            await session.execute(
                select(TenderSourceRow).where(TenderSourceRow.key == report.source_key)
            )
        )
        .scalars()
        .first()
    )
    if source is None:
        return

    if report.ok and not report.degraded:
        source.health = enums.SourceHealth.ok
        source.last_ok_at = now
        source.last_error = None
        source.consecutive_failures = 0
    elif report.ok and report.degraded:
        source.health = enums.SourceHealth.degraded
        source.last_ok_at = now
        source.last_error = report.error
    else:
        source.consecutive_failures += 1
        source.last_error = report.error
        source.health = (
            enums.SourceHealth.failing
            if source.consecutive_failures >= 3
            else enums.SourceHealth.degraded
        )

    await session.flush()
