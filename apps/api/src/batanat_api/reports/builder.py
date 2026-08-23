"""Report rendering.

Grouped by procuring entity, ordered by deadline within each group, because the
question being answered is "what do I need to act on this week". Every item
carries its reference number, deadline, value and a link to the source
document — the report has to be checkable without trusting it.

Failed sources are named at the top. A report that quietly omits KPLC looks
identical to a week when KPLC published nothing.
"""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from batanat_api.config import get_settings


def report_permalink(label: str) -> str:
    return f"{get_settings().web_public_url.rstrip('/')}/reports/tenders/{label}"


def _fmt_date(value: str | None) -> str:
    if not value:
        return "not stated"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return html.escape(value)
    days = (parsed - datetime.now(UTC)).days
    urgency = f" ({days}d)" if 0 <= days <= 14 else ""
    return f"{parsed.strftime('%d %b %Y')}{urgency}"


def _fmt_value(tender: dict[str, Any]) -> str:
    amount, currency = tender.get("estimated_value"), tender.get("currency")
    if amount is None or not currency:
        return "—"
    try:
        return f"{currency} {float(amount):,.0f}"
    except (TypeError, ValueError):
        return "—"


def group_by_entity(tenders: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for tender in tenders:
        grouped[tender.get("entity") or "Other"].append(tender)

    for items in grouped.values():
        # Soonest deadline first; undated last, since they are least actionable.
        items.sort(key=lambda t: (t.get("closing_date") is None, t.get("closing_date") or ""))
    return dict(sorted(grouped.items()))


def build_report_email(report: dict[str, Any], *, permalink: str) -> str:
    tenders = report.get("tenders", [])
    failed = report.get("failed_sources", [])
    rejections = report.get("rejections", [])

    parts = [
        '<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
        'color:#111;max-width:720px;margin:0 auto;padding:16px">',
        f"<h2 style='margin:0 0 4px'>Tender report — {html.escape(report['label'])}</h2>",
        f"<p style='color:#666;margin:0 0 16px;font-size:13px'>"
        f"{len(tenders)} tender(s) in the last {report.get('lookback_hours', 24)} hours. "
        f"<a href='{html.escape(permalink)}'>Open the full report</a></p>",
    ]

    if failed:
        parts.append(
            "<p style='background:#fff4e5;border:1px solid #f0c896;padding:8px 12px;"
            "border-radius:6px;font-size:13px'><b>Sources unavailable:</b> "
            + html.escape(", ".join(failed))
            + ". Those sites may have published tenders this system could not see.</p>"
        )

    if not tenders:
        parts.append(
            "<p style='font-size:14px'>No new tenders matched in this window. "
            "This report is sent even when empty, so that silence always means "
            "something is broken.</p>"
        )

    for entity, items in group_by_entity(tenders).items():
        parts.append(f"<h3 style='margin:20px 0 6px;font-size:15px'>{html.escape(entity)}</h3>")
        parts.append(
            "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            "<tr style='text-align:left;color:#666'>"
            "<th style='padding:4px 6px'>Reference</th><th>Title</th>"
            "<th>Closing</th><th>Value</th></tr>"
        )
        for tender in items:
            parts.append(
                "<tr style='border-top:1px solid #eee'>"
                f"<td style='padding:6px;white-space:nowrap'>"
                f"{html.escape(tender.get('reference_no') or '—')}</td>"
                f"<td style='padding:6px'><a href='{html.escape(tender['source_url'])}'>"
                f"{html.escape(tender['title'][:140])}</a></td>"
                f"<td style='padding:6px;white-space:nowrap'>"
                f"{_fmt_date(tender.get('closing_date'))}</td>"
                f"<td style='padding:6px;white-space:nowrap'>{_fmt_value(tender)}</td></tr>"
            )
        parts.append("</table>")

    if rejections:
        parts.append(
            f"<p style='color:#888;font-size:12px;margin-top:20px'>"
            f"{len(rejections)} item(s) were rejected by the validator and are not shown. "
            f"They are listed on the report page.</p>"
        )

    parts.append(
        "<p style='color:#999;font-size:11px;margin-top:24px'>Batanat Harness. "
        f"Generated {html.escape(report.get('generated_at', ''))}.</p></body></html>"
    )
    return "".join(parts)
