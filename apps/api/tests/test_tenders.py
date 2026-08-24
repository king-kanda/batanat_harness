"""Tender normalisation, parsing and dedupe.

Normalisation gets the most attention here because a misparsed closing date is
the worst failure this system can have: it does not look like a bug, it looks
like a tender that closed early.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from batanat_api.db.models import Tender
from batanat_api.tenders.base import (
    FetchResult,
    RawTender,
    SourceReport,
    SourceUnavailableError,
    content_hash,
)
from batanat_api.tenders.ingest import ingest_report, to_row_values
from batanat_api.tenders.normalize import (
    NAIROBI,
    clean_text,
    is_closed,
    looks_like_reference,
    parse_date,
    parse_money,
)
from batanat_api.tenders.sources import TableTenderSource, extract_reference

NOW = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)


# --- dates -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("22 July 2026", (2026, 7, 22)),
        ("22 Jul 2026", (2026, 7, 22)),
        ("2026-07-22", (2026, 7, 22)),
        ("22/07/2026", (2026, 7, 22)),
        ("22-07-2026", (2026, 7, 22)),
        ("July 22, 2026", (2026, 7, 22)),
        ("22nd July 2026", (2026, 7, 22)),
        ("22nd July 2026 at 11.00 am", (2026, 7, 22)),
        ("Monday, 22 July 2026", (2026, 7, 22)),
        ("22 July 2026, 10:00 EAT", (2026, 7, 22)),
    ],
)
def test_dates_parse_in_the_formats_these_sites_actually_use(text, expected) -> None:
    parsed = parse_date(text)
    assert parsed is not None, f"failed to parse {text!r}"
    local = parsed.astimezone(NAIROBI)
    assert (local.year, local.month, local.day) == expected


def test_ambiguous_dates_are_read_day_first() -> None:
    """07/08/2026 means 7 August in Kenya. Reading it as 8 July loses a month."""
    parsed = parse_date("07/08/2026")
    assert parsed is not None
    local = parsed.astimezone(NAIROBI)
    assert (local.month, local.day) == (8, 7)


@pytest.mark.parametrize(
    "text", ["", "   ", None, "—", "N/A", "TBA", "Download", "Open", "soon", "31 Febtober 2026"]
)
def test_unparseable_dates_return_none_rather_than_guessing(text) -> None:
    assert parse_date(text) is None


def test_a_parsed_date_keeps_the_day_the_site_meant() -> None:
    """Stored as UTC, but the Nairobi calendar day must not shift."""
    parsed = parse_date("1 January 2026")
    assert parsed is not None
    assert parsed.astimezone(NAIROBI).date().isoformat() == "2026-01-01"


# --- money -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "amount", "currency"),
    [
        ("KES 1,500,000", Decimal("1500000"), "KES"),
        ("Ksh 250,000.50", Decimal("250000.50"), "KES"),
        ("KShs 2 million", Decimal("2000000"), "KES"),
        ("USD 40,000", Decimal("40000"), "USD"),
        ("$1,200", Decimal("1200"), "USD"),
        ("EUR 3.5 million", Decimal("3500000"), "EUR"),
    ],
)
def test_money_parses_with_its_currency(text, amount, currency) -> None:
    assert parse_money(text) == (amount, currency)


@pytest.mark.parametrize("text", ["1,500,000", "2 million", "", None, "see document", "N/A"])
def test_an_amount_without_a_currency_is_discarded(text) -> None:
    """A number with no currency is misleading, not merely incomplete."""
    assert parse_money(text) == (None, None)


# --- small helpers -----------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("KP1/9A.2/PT/1/24", True),
        ("RFX 1465", True),
        ("Download", False),
        ("Open", False),
        ("", False),
        (None, False),
        ("—", False),
    ],
)
def test_reference_detection_ignores_table_furniture(value, expected) -> None:
    assert looks_like_reference(value) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tender KP1/9A.2/PT/1/24 for switchgear", "KP1/9A.2/PT/1/24"),
        ("RFX 1465 termination notice", "RFX 1465"),
        ("Invitation to tender for solar panels", None),
    ],
)
def test_reference_extraction_from_free_text(text, expected) -> None:
    assert extract_reference(text) == expected


def test_clean_text_collapses_whitespace_and_drops_placeholders() -> None:
    assert clean_text("  Supply   of\n switchgear ") == "Supply of switchgear"
    assert clean_text("—") is None


def test_a_missing_closing_date_is_not_treated_as_closed() -> None:
    """Unknown is not the same as expired; treating it so would hide live tenders."""
    assert is_closed(None) is False
    assert is_closed(NOW - timedelta(days=1), now=NOW) is True
    assert is_closed(NOW + timedelta(days=1), now=NOW) is False


def test_the_content_hash_is_stable_and_whitespace_insensitive() -> None:
    a = content_hash("kplc", "Supply of  switchgear", "22 July 2026")
    b = content_hash("kplc", "supply of switchgear", "22 July 2026")
    assert a == b
    assert a != content_hash("kengen", "Supply of switchgear", "22 July 2026")


# --- table parsing -----------------------------------------------------------


def _fetch_result(html: str) -> FetchResult:
    import uuid

    return FetchResult(
        source_key="test",
        url="https://example.co.ke/tenders",
        html=html,
        fetched_at=NOW,
        status_code=200,
        snapshot_id=uuid.uuid4(),
    )


REREC_SHAPED_HTML = """
<table>
  <tr><th>Reference</th><th>Title</th><th>Date</th><th>Closing Date</th><th>Status</th></tr>
  <tr>
    <td>RFX 1465</td>
    <td><a href="/docs/1465.pdf">Supply of 33kV switchgear</a></td>
    <td>5 August 2026</td><td>22 September 2026</td><td>Open</td>
  </tr>
  <tr>
    <td>—</td><td>Consultancy for grid study</td>
    <td>1 August 2026</td><td>—</td><td>Open</td>
  </tr>
</table>
"""


def test_a_table_listing_is_parsed_into_tenders() -> None:
    source = TableTenderSource(
        key="test", name="Test", entity="Test Entity", listing_url="https://example.co.ke/tenders"
    )
    tenders = source.parse(_fetch_result(REREC_SHAPED_HTML))

    assert len(tenders) == 2
    first, second = tenders
    assert first.reference_no == "RFX 1465"
    assert first.closing_text == "22 September 2026"
    assert first.source_url.endswith("/docs/1465.pdf")
    # "—" is furniture, not a reference number.
    assert second.reference_no is None


def test_navigation_tables_are_ignored() -> None:
    source = TableTenderSource(
        key="test", name="T", entity="E", listing_url="https://example.co.ke/x"
    )
    with pytest.raises(SourceUnavailableError):
        source.parse(_fetch_result("<table><tr><th>Home</th><th>Contact</th></tr></table>"))


def test_a_page_with_no_listing_fails_loudly() -> None:
    """Silently returning zero tenders would look identical to 'nothing published'."""
    source = TableTenderSource(
        key="test", name="T", entity="E", listing_url="https://example.co.ke/x"
    )
    with pytest.raises(SourceUnavailableError, match="No tender rows"):
        source.parse(_fetch_result("<html><body><p>Coming soon</p></body></html>"))


def test_card_layouts_fall_back_to_document_links() -> None:
    html = """
    <div class="card"><a href="/files/tender-notice-solar.pdf">
        Invitation to Tender for Solar Mini-Grid EPC Works</a>
        <span>Closing 30 September 2026</span></div>
    <div><a href="/about">About us</a></div>
    """
    source = TableTenderSource(
        key="test", name="T", entity="KETRACO", listing_url="https://example.co.ke/x"
    )
    tenders = source.parse(_fetch_result(html))

    assert len(tenders) == 1
    assert "Solar Mini-Grid" in tenders[0].title
    assert tenders[0].closing_text == "30 September 2026"


# --- ingest and dedupe -------------------------------------------------------


def _raw(**kw) -> RawTender:
    defaults = dict(
        title="Supply of 33kV switchgear",
        source_url="https://kplc.co.ke/t/1",
        reference_no="KP1/RE/1",
        entity="Kenya Power",
        closing_text="30 September 2026",
    )
    return RawTender(**{**defaults, **kw})


def _report(*tenders: RawTender) -> SourceReport:
    return SourceReport(source_key="kplc", ok=True, tenders=list(tenders))


async def test_ingest_creates_then_updates_rather_than_duplicating(session) -> None:
    """The twice-daily cron re-sees everything; that must not create rows."""
    first = await ingest_report(session, _report(_raw()), now=NOW)
    assert (first.created, first.updated) == (1, 0)

    later = NOW + timedelta(hours=6)
    second = await ingest_report(session, _report(_raw()), now=later)
    assert (second.created, second.updated) == (0, 1)

    rows = (await session.execute(select(Tender))).scalars().all()
    assert len(rows) == 1
    assert rows[0].first_seen_at == NOW  # preserved
    assert rows[0].last_seen_at == later


async def test_referenceless_tenders_dedupe_on_content(session) -> None:
    raw = _raw(reference_no=None)
    await ingest_report(session, _report(raw), now=NOW)
    await ingest_report(session, _report(raw), now=NOW + timedelta(hours=6))

    rows = (await session.execute(select(Tender))).scalars().all()
    assert len(rows) == 1
    assert rows[0].content_hash is not None


async def test_an_amended_closing_date_updates_the_existing_row(session) -> None:
    await ingest_report(session, _report(_raw()), now=NOW)
    await ingest_report(
        session, _report(_raw(closing_text="15 October 2026")), now=NOW + timedelta(days=1)
    )

    rows = (await session.execute(select(Tender))).scalars().all()
    assert len(rows) == 1
    assert rows[0].closing_date is not None
    assert rows[0].closing_date.astimezone(NAIROBI).day == 15


async def test_different_sources_publishing_the_same_reference_are_distinct(session) -> None:
    await ingest_report(session, _report(_raw()), now=NOW)
    other = SourceReport(source_key="kengen", ok=True, tenders=[_raw()])
    await ingest_report(session, other, now=NOW)

    assert len((await session.execute(select(Tender))).scalars().all()) == 2


async def test_a_titleless_row_is_skipped_not_stored(session) -> None:
    result = await ingest_report(session, _report(_raw(title="   ")), now=NOW)
    assert result.skipped == 1
    assert (await session.execute(select(Tender))).scalars().all() == []


def test_row_values_never_invent_a_value(session=None) -> None:
    values = to_row_values(
        _raw(value_text="see tender document"), source_key="kplc", run_id=None, now=NOW
    )
    assert values is not None
    assert values["estimated_value"] is None
    assert values["currency"] is None


# --- falling back between candidate URLs ---------------------------------------


class _ScriptedClient:
    """Serves canned HTML per URL and records what was asked for."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.asked: list[str] = []

    async def fetch(self, source_key: str, url: str):
        from datetime import UTC, datetime
        from uuid import uuid4

        from batanat_api.tenders.base import FetchResult, SourceUnavailableError

        self.asked.append(url)
        if url not in self.pages:
            raise SourceUnavailableError(f"HTTP 404 from {url}")
        return FetchResult(
            source_key=source_key,
            url=url,
            html=self.pages[url],
            fetched_at=datetime.now(UTC),
            status_code=200,
            snapshot_id=uuid4(),
        )


_TABLE = """
<table>
  <tr><th>Reference</th><th>Title</th><th>Closing</th></tr>
  <tr><td>KP/1/2026</td><td>Supply of 33kV switchgear</td><td>25 August 2026</td></tr>
</table>
"""

_NO_TABLE = "<html><body><h1>Open tenders</h1><p>Nothing at the moment.</p></body></html>"


def _source(primary: str, *fallbacks: str):
    from batanat_api.tenders.sources import ResilientTableSource, SourceConfig

    return ResilientTableSource(
        SourceConfig(
            key="test",
            name="Test",
            entity="Test Entity",
            listing_url=primary,
            fallback_urls=tuple(fallbacks),
        )
    )


async def test_a_page_that_loads_but_parses_to_nothing_falls_through() -> None:
    """KETRACO's actual failure: 200 OK, no table, and the alternate never tried.

    Falling back on fetch failure alone stopped at the first URL that merely
    answered, which is why the source sat failing while a working page existed
    one entry down the list.
    """
    client = _ScriptedClient({"https://x/open": _NO_TABLE, "https://x/closed": _TABLE})
    report = await _source("https://x/open", "https://x/closed").collect(client)

    assert report.ok
    assert len(report.tenders) == 1
    assert report.url == "https://x/closed"
    assert client.asked == ["https://x/open", "https://x/closed"]


async def test_the_first_candidate_wins_when_it_parses() -> None:
    """No pointless second request when the primary is fine."""
    client = _ScriptedClient({"https://x/open": _TABLE, "https://x/closed": _TABLE})
    report = await _source("https://x/open", "https://x/closed").collect(client)

    assert report.ok
    assert client.asked == ["https://x/open"]


async def test_a_404_still_falls_through() -> None:
    client = _ScriptedClient({"https://x/new": _TABLE})
    report = await _source("https://x/dead", "https://x/new").collect(client)

    assert report.ok
    assert report.url == "https://x/new"


async def test_when_nothing_parses_the_failure_names_a_real_url() -> None:
    """The snapshot has to be worth opening, so the error must point somewhere."""
    client = _ScriptedClient({"https://x/open": _NO_TABLE, "https://x/closed": _NO_TABLE})
    report = await _source("https://x/open", "https://x/closed").collect(client)

    assert not report.ok
    assert "https://x/open" in (report.error or "")
    assert client.asked == ["https://x/open", "https://x/closed"]
