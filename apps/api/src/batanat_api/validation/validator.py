"""The validator.

Runs between agent output and anything downstream — a report, an email, a
WhatsApp alert. It **rejects; it never patches.** A patched result is one nobody
notices is wrong: the tender still appears, the number is still made up, and the
only trace is a log line nobody reads. A rejected one shows up in the UI as a
rejection with a reason.

The rule that matters most is provenance: every tender's `source_url` must trace
to a document actually fetched in this run. A model that hallucinates a
plausible KPLC URL produces something indistinguishable from a real tender until
someone clicks it and misses a deadline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from batanat_api.core.logging import get_logger

log = get_logger(__name__)


class ValidatedTender(BaseModel):
    """The shape anything downstream is allowed to receive."""

    title: str = Field(min_length=5, max_length=2000)
    source_url: str = Field(min_length=10)
    entity: str | None = None
    reference_no: str | None = None
    category: str | None = None
    closing_date: datetime | None = None
    estimated_value: Decimal | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    county: str | None = None


@dataclass(slots=True)
class Rejection:
    subject: str
    rule: str
    detail: str


@dataclass
class ValidationOutcome:
    accepted: list[ValidatedTender] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejections

    def summary(self) -> dict[str, object]:
        return {
            "accepted": len(self.accepted),
            "rejected": len(self.rejections),
            "rules_triggered": sorted({r.rule for r in self.rejections}),
        }


def _fetched_origins(fetched_urls: list[str]) -> set[tuple[str, str]]:
    """(host, first path segment) for every document fetched in this run."""
    origins: set[tuple[str, str]] = set()
    for url in fetched_urls:
        parts = urlsplit(url)
        first_segment = parts.path.strip("/").split("/")[0] if parts.path.strip("/") else ""
        origins.add((parts.netloc.lower(), first_segment.lower()))
        origins.add((parts.netloc.lower(), ""))
    return origins


def validate_tenders(
    candidates: list[dict],
    *,
    fetched_urls: list[str],
    now: datetime | None = None,
    allow_closed: bool = False,
) -> ValidationOutcome:
    """Check a batch of tenders before anything is sent anywhere.

    `allow_closed` exists for the Monday run with its 72-hour lookback: a tender
    scraped on Friday that closed on Saturday is real history, and rejecting it
    outright would make the archive lie. The report filters it; the store keeps
    it. See the decision noted in TODO.md.
    """
    now = now or datetime.now(UTC)
    outcome = ValidationOutcome()
    origins = _fetched_origins(fetched_urls)

    for index, candidate in enumerate(candidates):
        subject = str(candidate.get("reference_no") or candidate.get("title") or f"item {index}")[
            :120
        ]

        try:
            tender = ValidatedTender.model_validate(candidate)
        except ValidationError as exc:
            outcome.rejections.append(
                Rejection(subject, "schema", "; ".join(e["msg"] for e in exc.errors()[:3]))
            )
            continue

        # Provenance. The single most important rule here.
        parts = urlsplit(tender.source_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            outcome.rejections.append(
                Rejection(subject, "source_url", f"Not a usable URL: {tender.source_url!r}")
            )
            continue

        host = parts.netloc.lower()
        first_segment = parts.path.strip("/").split("/")[0].lower() if parts.path.strip("/") else ""
        if (host, first_segment) not in origins and (host, "") not in origins:
            outcome.rejections.append(
                Rejection(
                    subject,
                    "provenance",
                    f"{tender.source_url} was not fetched in this run — it cannot be cited.",
                )
            )
            continue

        # An amount without a currency is misleading, not merely incomplete.
        if tender.estimated_value is not None and not tender.currency:
            outcome.rejections.append(
                Rejection(subject, "currency", "An amount was given with no currency.")
            )
            continue
        if tender.estimated_value is not None and tender.estimated_value < 0:
            outcome.rejections.append(Rejection(subject, "amount", "Negative estimated value."))
            continue

        if not allow_closed and tender.closing_date and tender.closing_date < now:
            outcome.rejections.append(
                Rejection(
                    subject,
                    "closed",
                    f"Closing date {tender.closing_date.date()} has already passed.",
                )
            )
            continue

        outcome.accepted.append(tender)

    if outcome.rejections:
        log.warning(
            "validator.rejected",
            count=len(outcome.rejections),
            rules=sorted({r.rule for r in outcome.rejections}),
        )
    return outcome
