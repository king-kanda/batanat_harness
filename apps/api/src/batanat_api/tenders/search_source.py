"""The search fallback.

Four of the five configured sites render their tender listings client-side:
the HTML we receive contains the page chrome and a pile of JavaScript, and the
tenders themselves arrive later over XHR. Scraping them properly needs either a
headless browser (heavy, fragile, and a new dependency) or each site's private
JSON endpoint (undocumented, and it changes without notice).

The PRD's instruction for exactly this situation is to ship the search fallback,
mark the adapter degraded, and move on — so that is what this is. Tavily is
asked for recent tender notices from the specific domain, and whatever it finds
is normalised through the same pipeline as a scraped row.

This is genuinely worse than scraping: search results lag publication, and
Tavily will not reliably surface a reference number or a closing date. The
report says which sources came from search, so nobody mistakes one for the
other.
"""

from __future__ import annotations

import httpx

from batanat_api.config import get_settings
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

TAVILY_ENDPOINT = "https://api.tavily.com/search"


class WebSearchSource(TenderSource):
    """Finds tender notices for one domain via Tavily."""

    key = "websearch"
    name = "Web search fallback"
    entity = "various"

    def __init__(
        self, *, domain: str | None = None, entity: str | None = None, query: str | None = None
    ):
        self.domain = domain
        self.entity = entity or "various"
        self.listing_url = f"https://{domain}" if domain else "https://tavily.com"
        self.query = query or self._default_query()
        if domain:
            self.key = f"websearch:{domain}"

    def _default_query(self) -> str:
        target = self.domain or "Kenya"
        return (
            f"open tender notice invitation to bid {target} "
            "electricity power solar transmission 2026"
        )

    async def fetch(self, client: PoliteClient) -> FetchResult:  # pragma: no cover - network
        raise NotImplementedError("WebSearchSource overrides collect(); it does not fetch HTML.")

    def parse(self, result: FetchResult) -> list[RawTender]:  # pragma: no cover
        raise NotImplementedError

    async def search(self) -> list[RawTender]:
        settings = get_settings()
        if not settings.tavily_api_key:
            raise SourceUnavailableError(
                "TAVILY_API_KEY is not set, so the search fallback is unavailable — see TODO.md."
            )

        payload = {
            "api_key": settings.tavily_api_key,
            "query": self.query,
            "search_depth": "advanced",
            "max_results": 10,
            "topic": "general",
        }
        if self.domain:
            payload["include_domains"] = [self.domain]

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(TAVILY_ENDPOINT, json=payload)

        if not response.is_success:
            raise SourceUnavailableError(f"Tavily returned HTTP {response.status_code}.")

        results = response.json().get("results", [])
        tenders: list[RawTender] = []
        for item in results:
            title = clean_text(item.get("title"))
            url = item.get("url")
            if not title or not url:
                continue
            tenders.append(
                RawTender(
                    title=title,
                    source_url=url,
                    entity=self.entity,
                    # Never fabricated: search rarely exposes either of these,
                    # and an invented deadline is a missed bid.
                    reference_no=None,
                    closing_text=None,
                    extra={"via": "search", "snippet": (item.get("content") or "")[:500]},
                )
            )

        log.info("scrape.search_fallback", domain=self.domain, count=len(tenders))
        return tenders

    async def collect(self, client: PoliteClient):
        from batanat_api.tenders.base import SourceReport

        try:
            tenders = await self.search()
        except Exception as exc:  # noqa: BLE001
            return SourceReport(
                source_key=self.key,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                degraded=True,
                url=self.listing_url,
            )
        return SourceReport(
            source_key=self.key,
            ok=True,
            tenders=tenders,
            degraded=True,  # always: search is a worse signal than scraping
            url=self.listing_url,
        )
