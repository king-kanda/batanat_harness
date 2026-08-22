"""`make sources` — what actually works today.

Scraper health is not a thing to assert in a comment; comments go stale the
first time a site is redesigned. This probes every source live and prints the
truth, and it is also what the nightly maintenance job calls.
"""

from __future__ import annotations

import asyncio

from batanat_api.core.logging import configure_logging
from batanat_api.db.session import session_scope
from batanat_api.tenders.base import PoliteClient
from batanat_api.tenders.ingest import record_source_health
from batanat_api.tenders.sources import build_sources

GREEN, YELLOW, RED, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[0m"


async def probe_all(*, persist: bool = True) -> int:
    client = PoliteClient()
    sources = build_sources()
    reports = []

    for source in sources:
        report = await source.collect(client)
        reports.append((source, report))

    if persist:
        async with session_scope() as session:
            for _, report in reports:
                await record_source_health(session, report)

    print(f"\n{'source':10} {'status':10} {'tenders':>7}  detail")
    print("-" * 78)
    working = 0
    for source, report in reports:
        if report.ok and report.tenders:
            colour, status = GREEN, "ok"
            working += 1
            detail = source.listing_url
        elif report.ok:
            colour, status = YELLOW, "empty"
            detail = "fetched, parsed nothing"
        else:
            colour, status = RED, "failing"
            detail = (report.error or "")[:60]
        print(f"{source.key:10} {colour}{status:10}{RESET} {len(report.tenders):>7}  {detail}")

    print(f"\n{working} of {len(sources)} sources returning tenders.")
    print(
        "Sources that fetch but parse nothing render their listings client-side; "
        "the search fallback covers them once TAVILY_API_KEY is set."
    )
    return 0 if working else 1


def main() -> None:
    configure_logging("warning")
    raise SystemExit(asyncio.run(probe_all()))


if __name__ == "__main__":
    main()
