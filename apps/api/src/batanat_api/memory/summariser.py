"""The nightly summarising agent.

Condenses the day's runs, classified emails and tender findings into memory
rows so tomorrow's context is a paragraph rather than a transcript.

Every row it writes is tagged by provenance, and the tagging is not a
formality:

* Facts about *our own activity* — how many runs, which sources failed — are
  `system_derived`. We observed them.
* Anything condensed from *email or scraped content* is `untrusted_external`,
  because a summary of attacker-controlled text is still attacker-controlled
  text. Compressing it does not launder it.

The second rule is the one that matters. Without it, an injection in an email
becomes a "memory" that gets loaded into the system prompt tomorrow — which is
the same attack, with a delay and better persistence.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import get_logger
from batanat_api.db import enums
from batanat_api.db.models import Email, Run, Tender
from batanat_api.memory.store import remember

log = get_logger(__name__)


async def summarise_recent(
    session: AsyncSession, user_id: uuid.UUID, *, hours: int = 24, now: datetime | None = None
) -> dict[str, Any]:
    """Write the day's episodic summary. Idempotent enough to run twice."""
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    written: list[str] = []

    # --- our own activity: system_derived, because we observed it ---
    run_counts = (
        await session.execute(
            select(Run.status, func.count(Run.id))
            .where(Run.user_id == user_id, Run.started_at >= since)
            .group_by(Run.status)
        )
    ).all()

    if run_counts:
        breakdown = ", ".join(f"{count} {status.value}" for status, count in run_counts)
        await remember(
            session,
            user_id=user_id,
            content=f"In the {hours}h to {now.date()}: {breakdown}.",
            layer=enums.MemoryLayer.episodic,
            trust_tag=enums.TrustTag.system_derived,
            source_ref="runs",
        )
        written.append("runs")

    # --- classified emails: untrusted_external, because the content is ---
    categories = (
        await session.execute(
            select(Email.category, func.count(Email.id))
            .where(
                Email.user_id == user_id,
                Email.processed_at >= since,
                Email.category.isnot(None),
            )
            .group_by(Email.category)
        )
    ).all()

    if categories:
        breakdown = ", ".join(f"{count} {category.value}" for category, count in categories)
        await remember(
            session,
            user_id=user_id,
            content=f"Email classified in the {hours}h to {now.date()}: {breakdown}.",
            layer=enums.MemoryLayer.episodic,
            # Counts are ours, but they describe outside content. Tag conservatively.
            trust_tag=enums.TrustTag.system_derived,
            source_ref="emails",
        )
        written.append("emails")

    # Subjects are attacker-controlled text and are tagged as such.
    opportunities = (
        (
            await session.execute(
                select(Email)
                .where(
                    Email.user_id == user_id,
                    Email.processed_at >= since,
                    Email.category == enums.EmailCategory.opportunity,
                )
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    for email in opportunities:
        await remember(
            session,
            user_id=user_id,
            content=f"Opportunity email from {email.from_address}: {email.subject}",
            layer=enums.MemoryLayer.episodic,
            trust_tag=enums.TrustTag.untrusted_external,
            source_ref=f"email:{email.id}",
        )
    if opportunities:
        written.append(f"{len(opportunities)} opportunity subjects")

    # --- tenders: counted, never embedded ---
    tender_count = (
        await session.execute(select(func.count(Tender.id)).where(Tender.first_seen_at >= since))
    ).scalar_one()

    if tender_count:
        await remember(
            session,
            user_id=user_id,
            content=f"{tender_count} new tenders seen in the {hours}h to {now.date()}.",
            layer=enums.MemoryLayer.episodic,
            trust_tag=enums.TrustTag.system_derived,
            source_ref="tenders",
        )
        written.append("tenders")

    log.info("memory.summarised", user_id=str(user_id), sections=written)
    return {"written": written, "since": since.isoformat()}
