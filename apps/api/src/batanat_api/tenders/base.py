"""Tender sources: the interface, and how we fetch politely.

These are public-sector sites run on small budgets. The scraper is a guest:
it identifies itself honestly, checks robots.txt, rate-limits itself, caches
within a run, and never retries in a tight loop.

**A judgement call worth naming.** KPLC's robots.txt allows `User-agent: *`
with `Content-Signal: search=yes, ai-train=no, use=reference`, while explicitly
disallowing named AI crawlers (ClaudeBot, GPTBot, CCBot and others). This
scraper is not any of those: it is the client's own operational tool, fetching
public procurement notices for reference, and it declares itself as such. It
does not train on the content. If Batanat would rather not fetch KPLC at all,
set `is_enabled = false` on that source row and the search fallback covers it.

Every fetch is snapshotted to Mongo before parsing. When a parser turns out to
be wrong — and on sites like these it will — we reparse history instead of
re-scraping it, and the snapshot is the evidence behind any tender we report.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from batanat_api.core.logging import get_logger
from batanat_api.db.mongo import RAW_SCRAPES, archive

log = get_logger(__name__)

USER_AGENT = "BatanatHarness/0.1 (+tender monitoring for Batanat Energy; contact ops@batanat.co.ke)"

#: Minimum gap between requests to the same host.
POLITE_DELAY_SECONDS = 1.5
#: A source that cannot answer in this long is not worth holding a run open for.
FETCH_TIMEOUT_SECONDS = 25.0


class SourceUnavailableError(RuntimeError):
    """The site did not answer usefully. Caller should degrade, not crash."""


class RobotsDisallowedError(RuntimeError):
    """robots.txt forbids this path for our user agent. Not something to work around."""


@dataclass(slots=True)
class RawTender:
    """One row as the site published it, before normalisation."""

    title: str
    source_url: str
    reference_no: str | None = None
    entity: str | None = None
    category: str | None = None
    closing_text: str | None = None
    published_text: str | None = None
    value_text: str | None = None
    county: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class FetchResult:
    source_key: str
    url: str
    html: str
    fetched_at: datetime
    status_code: int
    snapshot_id: uuid.UUID


@dataclass(slots=True)
class SourceReport:
    """What one source produced in one run, including how it failed."""

    source_key: str
    ok: bool
    tenders: list[RawTender] = field(default_factory=list)
    error: str | None = None
    degraded: bool = False
    duration_ms: int = 0
    url: str | None = None


class PoliteClient:
    """Shared HTTP client: one per run, so caching and rate limiting mean something."""

    def __init__(self, *, delay: float = POLITE_DELAY_SECONDS):
        self.delay = delay
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser] = {}
        self._cache: dict[str, str] = {}

    async def _wait_turn(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < self.delay:
                await asyncio.sleep(self.delay - elapsed)
        self._last_request[host] = time.monotonic()

    async def _robots_for(self, client: httpx.AsyncClient, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]

        parser = RobotFileParser()
        parser.set_url(urljoin(origin, "/robots.txt"))
        try:
            response = await client.get(urljoin(origin, "/robots.txt"))
            parser.parse(response.text.splitlines() if response.is_success else [])
        except Exception:  # noqa: BLE001 — no robots.txt means no restriction
            parser.parse([])

        self._robots[origin] = parser
        return parser

    async def fetch(self, source_key: str, url: str) -> FetchResult:
        """Fetch a page, honouring robots.txt, and snapshot it before anyone parses it."""
        if url in self._cache:
            log.debug("scrape.cache_hit", source=source_key, url=url)
            return FetchResult(
                source_key=source_key,
                url=url,
                html=self._cache[url],
                fetched_at=datetime.now(UTC),
                status_code=200,
                snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, url),
            )

        headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True, headers=headers
        ) as client:
            robots = await self._robots_for(client, url)
            if not robots.can_fetch(USER_AGENT, url):
                log.warning("scrape.robots_disallowed", source=source_key, url=url)
                raise RobotsDisallowedError(
                    f"robots.txt at {urlsplit(url).netloc} disallows {url} for our user agent."
                )

            await self._wait_turn(urlsplit(url).netloc)

            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                raise SourceUnavailableError(f"{type(exc).__name__}: {exc}") from exc

        if not response.is_success:
            raise SourceUnavailableError(f"HTTP {response.status_code} from {url}")

        html = response.text
        self._cache[url] = html

        snapshot_id = uuid.uuid4()
        await archive(
            RAW_SCRAPES,
            snapshot_id,
            {"html": html},
            source=source_key,
            url=url,
            status_code=response.status_code,
            content_length=len(html),
        )

        log.info(
            "scrape.fetched",
            source=source_key,
            url=url,
            status_code=response.status_code,
            bytes=len(html),
        )
        return FetchResult(
            source_key=source_key,
            url=url,
            html=html,
            fetched_at=datetime.now(UTC),
            status_code=response.status_code,
            snapshot_id=snapshot_id,
        )


class TenderSource(ABC):
    """One procuring entity's tender listing."""

    key: str
    name: str
    entity: str
    listing_url: str

    @abstractmethod
    async def fetch(self, client: PoliteClient) -> FetchResult: ...

    @abstractmethod
    def parse(self, result: FetchResult) -> list[RawTender]: ...

    async def collect(self, client: PoliteClient) -> SourceReport:
        """Fetch and parse, converting every failure into a report rather than an exception.

        One dead site must not take the run down with it — the report names the
        sources that failed, which is more useful than silence.
        """
        started = time.perf_counter()
        try:
            result = await self.fetch(client)
            tenders = self.parse(result)
        except RobotsDisallowedError as exc:
            return SourceReport(
                source_key=self.key,
                ok=False,
                error=str(exc),
                degraded=True,
                duration_ms=int((time.perf_counter() - started) * 1000),
                url=self.listing_url,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("scrape.source_failed", source=self.key, error_type=type(exc).__name__)
            return SourceReport(
                source_key=self.key,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                degraded=True,
                duration_ms=int((time.perf_counter() - started) * 1000),
                url=self.listing_url,
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        log.info("scrape.parsed", source=self.key, count=len(tenders), duration_ms=duration_ms)
        return SourceReport(
            source_key=self.key,
            ok=True,
            tenders=tenders,
            duration_ms=duration_ms,
            url=result.url,
        )

    async def health_check(self, client: PoliteClient) -> bool:
        """Can we still fetch and parse anything at all from this source?"""
        report = await self.collect(client)
        return report.ok and bool(report.tenders)


def content_hash(source: str, title: str, closing: str | None) -> str:
    """Fallback identity for sources that publish no reference number."""
    normalised = "|".join(
        part.strip().lower() for part in (source, " ".join(title.split()), closing or "")
    )
    return hashlib.sha256(normalised.encode()).hexdigest()
