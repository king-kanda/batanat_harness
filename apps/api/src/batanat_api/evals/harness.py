"""The eval harness.

Every 👍/👎 is a labelled test case. Thumbs-up means the classification was
right; thumbs-down means it was wrong. That is a small, honest dataset that
grows as the system is used, and it is the only way to answer "did that Skill.MD
change help?" with a number instead of an impression.

Precision and recall are reported per Skill.MD version, so a regression is
visible as a trend rather than a feeling.

`make eval` prints real numbers or says plainly that there is not enough
feedback yet. It never invents a baseline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from batanat_api.core.logging import configure_logging, get_logger
from batanat_api.db import enums
from batanat_api.db.models import Email, Feedback, SkillVersion, Tender
from batanat_api.db.session import session_scope

log = get_logger(__name__)

MIN_CASES = 5


@dataclass
class Metrics:
    """Precision and recall over thumb-labelled cases."""

    true_positive: int = 0
    false_positive: int = 0
    false_negative: int = 0
    true_negative: int = 0

    @property
    def total(self) -> int:
        return self.true_positive + self.false_positive + self.false_negative + self.true_negative

    @property
    def precision(self) -> float | None:
        denominator = self.true_positive + self.false_positive
        return self.true_positive / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positive + self.false_negative
        return self.true_positive / denominator if denominator else None

    @property
    def f1(self) -> float | None:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p and r else None

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "cases": self.total,
            "precision": round(self.precision, 3) if self.precision is not None else None,
            "recall": round(self.recall, 3) if self.recall is not None else None,
            "f1": round(self.f1, 3) if self.f1 is not None else None,
            "true_positive": self.true_positive,
            "false_positive": self.false_positive,
            "false_negative": self.false_negative,
        }


@dataclass
class EvalReport:
    email: Metrics = field(default_factory=Metrics)
    tender: Metrics = field(default_factory=Metrics)
    by_skill_version: dict[int, dict] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def score_email(category: enums.EmailCategory | None, rating: enums.FeedbackRating) -> str:
    """Map a labelled email to a confusion-matrix cell.

    "Positive" means the system flagged it as an opportunity. A thumbs-down on
    an opportunity is a false positive; a thumbs-down on something we filed as
    irrelevant is a false negative — we missed it.
    """
    flagged = category is enums.EmailCategory.opportunity
    correct = rating is enums.FeedbackRating.up

    if flagged and correct:
        return "true_positive"
    if flagged and not correct:
        return "false_positive"
    if not flagged and not correct:
        return "false_negative"
    return "true_negative"


async def evaluate(session: AsyncSession) -> EvalReport:
    report = EvalReport()

    votes = (
        (await session.execute(select(Feedback).order_by(Feedback.created_at.desc())))
        .scalars()
        .all()
    )

    if not votes:
        report.notes.append(
            "No feedback yet. Use the 👍/👎 buttons on the Results screen; each vote "
            "becomes a labelled case here."
        )
        return report

    emails = {e.id: e for e in (await session.execute(select(Email))).scalars().all()}
    tenders = {t.id: t for t in (await session.execute(select(Tender))).scalars().all()}
    versions = {
        v.id: v.version for v in (await session.execute(select(SkillVersion))).scalars().all()
    }

    per_version: dict[int, Metrics] = {}

    for vote in votes:
        if vote.subject_type == "email":
            email = emails.get(vote.subject_id)
            if email is None:
                continue
            cell = score_email(email.category, vote.rating)
            setattr(report.email, cell, getattr(report.email, cell) + 1)

            version = versions.get(vote.skill_version_id)
            if version is not None:
                metrics = per_version.setdefault(version, Metrics())
                setattr(metrics, cell, getattr(metrics, cell) + 1)

        elif vote.subject_type == "tender":
            tender = tenders.get(vote.subject_id)
            if tender is None:
                continue
            # Every stored tender was judged relevant enough to report, so a
            # thumbs-down is a false positive.
            cell = "true_positive" if vote.rating is enums.FeedbackRating.up else "false_positive"
            setattr(report.tender, cell, getattr(report.tender, cell) + 1)

    report.by_skill_version = {v: m.as_dict() for v, m in sorted(per_version.items())}

    if report.email.total < MIN_CASES:
        report.notes.append(
            f"Only {report.email.total} labelled email case(s). These numbers are not yet "
            f"meaningful — {MIN_CASES} is the minimum worth reading."
        )
    return report


def render(report: EvalReport) -> str:
    lines = ["", "Batanat eval — precision and recall from 👍/👎 feedback", "=" * 58]

    for name, metrics in (
        ("Email classification", report.email),
        ("Tender relevance", report.tender),
    ):
        data = metrics.as_dict()
        lines.append(f"\n{name}")
        if not data["cases"]:
            lines.append("  no labelled cases")
            continue
        lines.append(f"  cases      {data['cases']}")
        lines.append(
            f"  precision  {data['precision'] if data['precision'] is not None else '—'}"
            f"   (of what we flagged, how much was right)"
        )
        lines.append(
            f"  recall     {data['recall'] if data['recall'] is not None else '—'}"
            f"   (of what mattered, how much we caught)"
        )
        lines.append(f"  f1         {data['f1'] if data['f1'] is not None else '—'}")
        lines.append(
            f"  tp/fp/fn   {data['true_positive']}/{data['false_positive']}/"
            f"{data['false_negative']}"
        )

    if report.by_skill_version:
        lines.append("\nBy Skill.MD version")
        for version, data in report.by_skill_version.items():
            lines.append(
                f"  v{version:<3} cases={data['cases']:<4} precision={data['precision']} "
                f"recall={data['recall']}"
            )

    for note in report.notes:
        lines.append(f"\nNote: {note}")

    return "\n".join(lines) + "\n"


async def _run() -> int:
    async with session_scope() as session:
        report = await evaluate(session)
    print(render(report))
    return 0


def main() -> None:
    configure_logging("warning")
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
