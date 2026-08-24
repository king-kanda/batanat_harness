"""PPIP, via its JSON API rather than its HTML.

`tenders.go.ke` is the national procurement portal — every procuring entity
publishes there, which makes it the one source worth more than the other four
combined. It is also a Vue SPA: the page we fetch is a 1.3KB shell and the
tenders arrive over XHR, so the table parser had nothing to work with.

The XHR endpoint is public, unauthenticated, and allowed by robots.txt, so we
call it directly. That is strictly better than scraping: no markup to break, and
the fields arrive already separated instead of recovered from a `<td>`.

Two constraints the API imposes:

* Page size is fixed at 10. `per_page` and `limit` both return HTTP 500, so a
  full sweep is ~31 requests at 1.5s apart. Fine twice a day, and `MAX_PAGES`
  stops an unbounded walk if the shape ever changes.
* There is no server-rendered detail page. `source_url` points at the portal's
  SPA route, which is where a human clicks through; it will not parse as HTML.

Verified against the live API on 2026-08-24: 309 active tenders, 31 pages.
"""

from __future__ import annotations

import json
from typing import Any

from batanat_api.core.logging import get_logger
from batanat_api.tenders.base import (
    FetchResult,
    PoliteClient,
    RawTender,
    SourceUnavailableError,
    TenderSource,
)
from batanat_api.tenders.normalize import clean_text

log = get_logger(__name__)

API_URL = "https://tenders.go.ke/api/active-tenders"
PORTAL_URL = "https://tenders.go.ke/website/tenders"

#: A full sweep is 31 pages today. The ceiling is generous enough to absorb
#: growth and low enough that a pagination bug cannot walk forever.
MAX_PAGES = 80


class PpipApiSource(TenderSource):
    """The national portal. Reads JSON; everything else here reads HTML."""

    def __init__(
        self,
        *,
        key: str = "ppip",
        name: str = "Public Procurement Information Portal",
        entity: str = "Government of Kenya",
        listing_url: str = API_URL,
    ):
        self.key = key
        self.name = name
        self.entity = entity
        self.listing_url = listing_url

    async def fetch(self, client: PoliteClient) -> FetchResult:
        """Walk every page and hand `parse` one combined document.

        Each page goes through `PoliteClient`, so rate limiting, robots and the
        raw snapshot in Mongo all still apply — one archived response per page,
        which is what you want when reconstructing what the portal said on a
        given day.
        """
        rows: list[dict[str, Any]] = []
        first: FetchResult | None = None
        page = 1

        while page <= MAX_PAGES:
            result = await client.fetch(self.key, f"{self.listing_url}?page={page}")
            first = first or result

            try:
                payload = json.loads(result.html)
            except json.JSONDecodeError as exc:
                raise SourceUnavailableError(
                    f"{self.listing_url} returned something that is not JSON on page {page}. "
                    "The portal has probably changed — check the snapshot in Mongo."
                ) from exc

            batch = payload.get("data")
            if not isinstance(batch, list):
                raise SourceUnavailableError(
                    f"No `data` array in the response from {self.listing_url} (page {page})."
                )

            rows.extend(batch)

            last_page = payload.get("last_page")
            if not isinstance(last_page, int) or page >= last_page:
                break
            page += 1
        else:
            log.warning("scrape.page_cap_reached", source=self.key, max_pages=MAX_PAGES)

        log.info("scrape.ppip_pages", source=self.key, pages=page, rows=len(rows))

        assert first is not None  # MAX_PAGES >= 1, so the loop always runs once
        return FetchResult(
            source_key=self.key,
            url=self.listing_url,
            html=json.dumps({"data": rows}),
            fetched_at=first.fetched_at,
            status_code=first.status_code,
            snapshot_id=first.snapshot_id,
        )

    def parse(self, result: FetchResult) -> list[RawTender]:
        rows = json.loads(result.html).get("data", [])

        tenders: list[RawTender] = []
        for row in rows:
            tender = self._to_tender(row)
            if tender:
                tenders.append(tender)

        if not tenders:
            raise SourceUnavailableError(
                f"{len(rows)} rows from {self.listing_url}, none of them usable. "
                "The field names have probably changed."
            )
        return tenders

    def _to_tender(self, row: dict[str, Any]) -> RawTender | None:
        title = clean_text(row.get("title"))
        if not title:
            return None

        # `pe` is the procuring entity — the county fund, ministry or parastatal
        # actually buying. Far more specific than our own `entity`, so prefer it.
        pe = row.get("pe") or {}
        entity = clean_text(pe.get("name")) if isinstance(pe, dict) else None

        category = row.get("procurement_category") or {}
        method = row.get("procurement_method") or {}

        tender_id = row.get("id")
        extra = {
            key: value
            for key, value in {
                "ocid": clean_text(row.get("ocid")),
                "method": clean_text(method.get("title")) if isinstance(method, dict) else None,
                "pe_email": clean_text(pe.get("email")) if isinstance(pe, dict) else None,
                "venue": clean_text(row.get("venue")),
            }.items()
            if value
        }

        return RawTender(
            title=title,
            source_url=f"{PORTAL_URL}/{tender_id}" if tender_id else PORTAL_URL,
            reference_no=clean_text(row.get("tender_ref")),
            entity=entity or self.entity,
            category=clean_text(category.get("title")) if isinstance(category, dict) else None,
            # Passed through as published. `parse_date` handles the timestamp
            # format, so the closing *time* survives — it is 10:00 on the day
            # more often than not, and a bid submitted at 11:00 is not late by
            # a day, it is late by an hour.
            closing_text=clean_text(row.get("close_at")),
            published_text=clean_text(row.get("published_at")),
            extra=extra,
        )
