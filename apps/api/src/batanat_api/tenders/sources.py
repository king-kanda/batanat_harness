"""The five adapters, plus the search fallback.

These sites are all CMS-driven listings whose real structure is "a table with a
header row". So rather than five bespoke parsers that each break differently,
there is one table parser that maps header text to fields, configured per site.
Anything a site does that this cannot express gets its own subclass.

Per the PRD the scrapers are timeboxed, and this is where that bit. Verified
against the live sites on 2026-08-23:

* **REREC** — working. Server-rendered table (reference, title, dates, status,
  document link). 157 tenders on the last run.
* **KPLC, KenGen, KETRACO, PPIP** — all four render their tender listings
  client-side. The HTML we receive is page chrome plus JavaScript; the tenders
  arrive later over XHR. Scraping them needs a headless browser or each site's
  private JSON endpoint, neither of which is worth the fragility here. They are
  marked degraded and covered by the search fallback.

Both parsing strategies are tried before a source is called broken: the table
parser first, then document-link extraction for card and accordion layouts.

`make sources` prints exactly which of these is true today, rather than trusting
this comment.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from batanat_api.core.logging import get_logger
from batanat_api.tenders.base import (
    FetchResult,
    PoliteClient,
    RawTender,
    SourceUnavailableError,
    TenderSource,
)
from batanat_api.tenders.normalize import clean_text, looks_like_reference

log = get_logger(__name__)

#: Words that make a link plausibly a procurement notice rather than site chrome.
TENDER_WORDS = re.compile(
    r"\b(tender|rfx|rfp|rfq|eoi|expression of interest|prequalification|pre-qualification|"
    r"invitation to bid|itb|procurement|addendum|bid)\b",
    re.IGNORECASE,
)
#: URL shapes used by CMS download handlers that do not end in a file extension.
DOCUMENT_PATH = re.compile(r"(download|wpdmdl|attachment|/documents?/|/uploads?/)", re.IGNORECASE)
#: Reference numbers as these entities write them: KP1/9A.2/PT/1/24, RFX 1465.
REFERENCE = re.compile(r"\b((?:[A-Z]{2,6}[0-9]?[/\-][A-Z0-9./\-]{3,}[0-9])|(?:RFX\s?[0-9]{3,}))\b")


def extract_reference(text: str) -> str | None:
    match = REFERENCE.search(text)
    return match.group(1).strip() if match else None


def _nearby_date_text(link) -> str | None:
    """Look for a date beside the link — cards put the deadline next to the title."""
    for element in (link.parent, getattr(link.parent, "parent", None)):
        if element is None:
            continue
        text = clean_text(element.get_text())
        if text and DATE_HINT.search(text):
            match = DATE_HINT.search(text)
            return match.group(0) if match else None
    return None


DATE_HINT = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2})\b"
)


@dataclass(frozen=True, slots=True)
class ColumnMap:
    """Which header words identify which field. Matched case-insensitively."""

    reference: tuple[str, ...] = ("reference", "ref", "tender no", "tender number")
    title: tuple[str, ...] = ("title", "description", "subject", "tender name", "particulars")
    closing: tuple[str, ...] = ("closing", "deadline", "submission", "close date")
    published: tuple[str, ...] = ("date", "published", "posted", "opening")
    category: tuple[str, ...] = ("category", "type")
    status: tuple[str, ...] = ("status",)
    value: tuple[str, ...] = ("value", "amount", "estimate", "budget")


DEFAULT_COLUMNS = ColumnMap()


def _match_column(header: str, candidates: tuple[str, ...]) -> bool:
    lowered = header.lower()
    return any(candidate in lowered for candidate in candidates)


class TableTenderSource(TenderSource):
    """A listing published as an HTML table."""

    columns: ColumnMap = DEFAULT_COLUMNS

    def __init__(
        self,
        *,
        key: str,
        name: str,
        entity: str,
        listing_url: str,
        columns: ColumnMap | None = None,
    ):
        self.key = key
        self.name = name
        self.entity = entity
        self.listing_url = listing_url
        if columns:
            self.columns = columns

    async def fetch(self, client: PoliteClient) -> FetchResult:
        return await client.fetch(self.key, self.listing_url)

    def parse(self, result: FetchResult) -> list[RawTender]:
        soup = BeautifulSoup(result.html, "lxml")
        tenders: list[RawTender] = []

        for table in soup.find_all("table"):
            headers = [
                clean_text(cell.get_text()) or ""
                for cell in (table.find("tr").find_all(["th", "td"]) if table.find("tr") else [])
            ]
            if not headers:
                continue

            index = self._index_columns(headers)
            # A table with neither a title nor a reference column is page
            # furniture, not a tender listing.
            if index.get("title") is None and index.get("reference") is None:
                continue

            for row in table.find_all("tr")[1:]:
                tender = self._parse_row(row, index, result)
                if tender:
                    tenders.append(tender)

        if not tenders:
            # Not every listing is a table. Card and accordion layouts publish
            # the same information as a list of document links, so try that
            # before declaring the source broken.
            tenders = self._parse_document_links(soup, result)

        if not tenders:
            raise SourceUnavailableError(
                f"No tender rows found at {result.url}. The page structure has probably "
                "changed — check the snapshot in Mongo."
            )
        return tenders

    def _parse_document_links(self, soup: BeautifulSoup, result: FetchResult) -> list[RawTender]:
        """Extract tenders from a list of linked documents.

        Deliberately conservative: a link only counts if it points at a document
        *and* its text reads like a procurement notice. Sweeping up every link
        on the page would fill the report with navigation chrome, which is worse
        than reporting nothing and saying so.
        """
        tenders: list[RawTender] = []
        seen: set[str] = set()

        for link in soup.find_all("a", href=True):
            href = link["href"]
            text = clean_text(link.get_text())
            if not text or len(text) < 15:
                continue

            is_document = any(
                href.lower().split("?")[0].endswith(ext)
                for ext in (".pdf", ".doc", ".docx", ".zip")
            )
            if not (is_document or DOCUMENT_PATH.search(href)):
                continue
            if not TENDER_WORDS.search(text):
                continue

            url = urljoin(result.url, href)
            if url in seen:
                continue
            seen.add(url)

            reference = extract_reference(text)
            tenders.append(
                RawTender(
                    title=text,
                    source_url=url,
                    reference_no=reference,
                    entity=self.entity,
                    closing_text=_nearby_date_text(link),
                )
            )

        return tenders

    def _index_columns(self, headers: list[str]) -> dict[str, int]:
        index: dict[str, int] = {}
        for position, header in enumerate(headers):
            for field_name in (
                "reference",
                "title",
                "closing",
                "published",
                "category",
                "status",
                "value",
            ):
                if field_name not in index and _match_column(
                    header, getattr(self.columns, field_name)
                ):
                    index[field_name] = position
        return index

    def _parse_row(self, row, index: dict[str, int], result: FetchResult) -> RawTender | None:
        cells = row.find_all(["td", "th"])
        if not cells:
            return None

        def cell(name: str) -> str | None:
            position = index.get(name)
            if position is None or position >= len(cells):
                return None
            return clean_text(cells[position].get_text())

        title = cell("title")
        reference = cell("reference")

        if not title and not reference:
            return None
        if not title:
            title = reference or ""

        # Prefer the row's own document link; fall back to the listing page.
        link = row.find("a", href=True)
        source_url = urljoin(result.url, link["href"]) if link else result.url

        return RawTender(
            title=title,
            source_url=source_url,
            reference_no=reference if looks_like_reference(reference) else None,
            entity=self.entity,
            category=cell("category"),
            closing_text=cell("closing"),
            published_text=cell("published"),
            value_text=cell("value"),
            extra={"status": cell("status") or ""},
        )


@dataclass(frozen=True, slots=True)
class SourceConfig:
    key: str
    name: str
    entity: str
    listing_url: str
    #: Alternate paths tried in order when the primary 404s, because these sites
    #: move their tender page on every redesign.
    fallback_urls: tuple[str, ...] = field(default=())


CONFIGS: tuple[SourceConfig, ...] = (
    SourceConfig(
        key="rerec",
        name="REREC",
        entity="Rural Electrification and Renewable Energy Corporation",
        listing_url="https://www.rerec.co.ke/tenders/",
    ),
    SourceConfig(
        key="kplc",
        name="Kenya Power",
        entity="Kenya Power and Lighting Company",
        listing_url="https://www.kplc.co.ke/tender-notices",
        fallback_urls=(
            "https://www.kplc.co.ke/tender",
            "https://www.kplc.co.ke/limited-tenders",
        ),
    ),
    SourceConfig(
        key="kengen",
        name="KenGen",
        entity="Kenya Electricity Generating Company",
        listing_url="https://tenders.kengen.co.ke/",
        fallback_urls=("https://www.kengen.co.ke/tenders/",),
    ),
    SourceConfig(
        key="ketraco",
        name="KETRACO",
        entity="Kenya Electricity Transmission Company",
        listing_url="https://www.ketraco.co.ke/index.php/procurement/tenders/open-tenders",
        fallback_urls=(
            "https://www.ketraco.co.ke/procurement/tenders/open-tenders",
            "https://www.ketraco.co.ke/index.php/procurement/tenders/closed-tenders",
        ),
    ),
    SourceConfig(
        key="ppip",
        name="PPIP",
        entity="Public Procurement Information Portal",
        listing_url="https://tenders.go.ke/website/tenders/index",
        fallback_urls=("https://tenders.go.ke/api/active-tenders",),
    ),
)


class ResilientTableSource(TableTenderSource):
    """Tries the configured URL, then the known alternates, before giving up.

    These sites reorganise; a 404 on the primary path is a redesign, not an
    outage, and one of the alternates is usually right.
    """

    def __init__(self, config: SourceConfig):
        super().__init__(
            key=config.key,
            name=config.name,
            entity=config.entity,
            listing_url=config.listing_url,
        )
        self.candidate_urls = (config.listing_url, *config.fallback_urls)

    async def fetch(self, client: PoliteClient) -> FetchResult:
        errors: list[str] = []
        for url in self.candidate_urls:
            try:
                return await client.fetch(self.key, url)
            except SourceUnavailableError as exc:
                errors.append(f"{url}: {exc}")
        raise SourceUnavailableError(
            f"No reachable listing for {self.key}. Tried: " + "; ".join(errors)
        )


def build_sources(keys: list[str] | None = None) -> list[TenderSource]:
    """The shipped five, from the static table."""
    selected = [c for c in CONFIGS if not keys or c.key in keys]
    return [ResilientTableSource(config) for config in selected]


async def build_sources_from_db(session, keys: list[str] | None = None) -> list[TenderSource]:
    """Every enabled source in the database, including ones the client added.

    The static CONFIGS are the seed, not the authority — once a row exists the
    row wins, so editing a listing URL in the UI takes effect without a deploy.
    Falls back to CONFIGS if the table is empty, so a fresh clone still works
    before `make seed` has run.
    """
    from sqlalchemy import select

    from batanat_api.db.models import TenderSourceRow

    query = select(TenderSourceRow).where(TenderSourceRow.is_enabled.is_(True))
    if keys:
        query = query.where(TenderSourceRow.key.in_(keys))

    rows = (await session.execute(query.order_by(TenderSourceRow.key))).scalars().all()
    if not rows:
        return build_sources(keys)

    sources: list[TenderSource] = []
    for row in rows:
        # The search fallback is not a scraper; it is invoked separately.
        if row.adapter == "WebSearchSource":
            continue
        sources.append(
            ResilientTableSource(
                SourceConfig(
                    key=row.key,
                    name=row.name,
                    entity=row.entity or row.name,
                    listing_url=row.listing_url or row.base_url,
                    fallback_urls=tuple(row.fallback_urls or ()),
                )
            )
        )
    return sources


def source_keys() -> list[str]:
    return [config.key for config in CONFIGS]
