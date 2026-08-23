"""The tender cycle.

Scrape → validate → report → notify, as one `cron_tender` run. Untrusted:
scraped HTML is quoted data and the run cannot write to the CRM.

The report goes out even when nothing new was found. Silence is
indistinguishable from breakage, and a client who stops hearing from the system
has no way to tell which one is happening.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Run, SkillVersion, Tender
from batanat_api.tenders.base import PoliteClient
from batanat_api.tenders.ingest import ingest_report, record_source_health
from batanat_api.tenders.sources import build_sources
from batanat_api.validation.validator import validate_tenders

log = get_logger(__name__)


async def run_tender_cycle(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    lookback_hours: int = 24,
    label: str | None = None,
    now: datetime | None = None,
) -> dict:
    """One full cycle. Returns the report payload."""
    now = now or datetime.now(UTC)
    label = label or now.strftime("%Y-%m-%d-%H%M")

    skill = (
        await session.execute(
            select(SkillVersion).where(
                SkillVersion.user_id == user_id, SkillVersion.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()

    run = Run(
        user_id=user_id,
        trigger_type=enums.TriggerType.cron_tender,
        trust_level=enums.TrustLevel.untrusted,
        bound_tools=["scrape_tenders", "web_search", "propose_crm_entry"],
        status=enums.RunStatus.running,
        skill_version_id=skill.id if skill else None,
        trigger_ref=label,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    client = PoliteClient()
    fetched_urls: list[str] = []
    source_summaries = []
    new_tender_ids: list[uuid.UUID] = []

    for source in build_sources():
        report = await source.collect(client)
        await record_source_health(session, report)

        if report.ok:
            fetched_urls.append(report.url or source.listing_url)
            fetched_urls.extend(t.source_url for t in report.tenders)
            ingested = await ingest_report(session, report, run_id=run.id, now=now)
            new_tender_ids.extend(ingested.tender_ids)

        source_summaries.append(
            {
                "source": report.source_key,
                "ok": report.ok,
                "count": len(report.tenders),
                "degraded": report.degraded,
                "error": report.error,
            }
        )

    since = now - timedelta(hours=lookback_hours)
    candidates = list(
        (
            await session.execute(
                select(Tender)
                .where(Tender.first_seen_at >= since)
                .order_by(Tender.closing_date.asc().nulls_last())
            )
        )
        .scalars()
        .all()
    )

    outcome = validate_tenders(
        [
            {
                "title": t.title,
                "source_url": t.source_url,
                "entity": t.entity,
                "reference_no": t.reference_no,
                "category": t.category,
                "closing_date": t.closing_date,
                "estimated_value": t.estimated_value,
                "currency": t.currency,
                "county": t.county,
            }
            for t in candidates
        ],
        fetched_urls=fetched_urls,
        now=now,
    )

    run.status = enums.RunStatus.succeeded
    run.ended_at = datetime.now(UTC)
    run.duration_ms = int((run.ended_at - run.started_at).total_seconds() * 1000)
    run.summary = (
        f"{len(outcome.accepted)} tenders from "
        f"{sum(1 for s in source_summaries if s['ok'])}/{len(source_summaries)} sources"
    )
    await session.flush()

    payload = {
        "label": label,
        "run_id": str(run.id),
        "generated_at": now.isoformat(),
        "lookback_hours": lookback_hours,
        "sources": source_summaries,
        "failed_sources": [s["source"] for s in source_summaries if not s["ok"]],
        "tenders": [t.model_dump(mode="json") for t in outcome.accepted],
        "validation": outcome.summary(),
        "rejections": [
            {"subject": r.subject, "rule": r.rule, "detail": r.detail} for r in outcome.rejections
        ],
    }

    log.info(
        "tender.cycle.complete",
        label=label,
        accepted=len(outcome.accepted),
        rejected=len(outcome.rejections),
        failed_sources=payload["failed_sources"],
    )
    return payload
