"""The PPIP JSON adapter.

Everything here runs against captured payloads, not the network: the portal is
the one source we cannot afford to have fail silently, and a test that needs
`tenders.go.ke` to be up tells you nothing on the day it is down.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from batanat_api.tenders.base import FetchResult, SourceUnavailableError
from batanat_api.tenders.normalize import parse_date
from batanat_api.tenders.ppip_api import MAX_PAGES, PpipApiSource

# Trimmed from a real response on 2026-08-24, keeping the fields we read.
ROW = {
    "id": 303654,
    "ocid": "ocds-5whusi-303654-NE/NGCDF/OT/01/2026/2027",
    "title": "Completion of 1No. Huduma Jitume Digital Centre",
    "tender_ref": "NE/NGCDF/OT/01/2026/2027",
    "venue": "Supply Chain Management Office",
    "published_at": "2026-08-18 00:00:00",
    "close_at": "2026-08-25 10:00:00",
    "description": "",
    "pe": {"id": 7822, "name": "NAROK EAST NG CDF", "email": "cdfnarokeast@cdf.go.ke"},
    "procurement_category": {"id": 2, "title": "Works", "code": "works"},
    "procurement_method": {"id": 1, "title": "Open Tender", "code": "open"},
    "county_ministry": None,
}


def _result(rows: list[dict]) -> FetchResult:
    return FetchResult(
        source_key="ppip",
        url="https://tenders.go.ke/api/active-tenders",
        html=json.dumps({"data": rows}),
        fetched_at=datetime.now(UTC),
        status_code=200,
        snapshot_id=uuid.uuid4(),
    )


class _FakeClient:
    """Stands in for PoliteClient, counting pages and serving canned payloads."""

    def __init__(self, pages: list[dict]):
        self.pages = pages
        self.urls: list[str] = []

    async def fetch(self, source_key: str, url: str) -> FetchResult:
        self.urls.append(url)
        index = int(url.rsplit("page=", 1)[1]) - 1
        payload = self.pages[index] if index < len(self.pages) else {"data": [], "last_page": 1}
        return FetchResult(
            source_key=source_key,
            url=url,
            html=json.dumps(payload),
            fetched_at=datetime.now(UTC),
            status_code=200,
            snapshot_id=uuid.uuid4(),
        )


def _page(rows: list[dict], *, current: int, last: int) -> dict:
    return {"data": rows, "current_page": current, "last_page": last}


# --- field mapping -----------------------------------------------------------


def test_a_row_becomes_a_tender_with_every_field_we_care_about() -> None:
    [tender] = PpipApiSource().parse(_result([ROW]))

    assert tender.title == "Completion of 1No. Huduma Jitume Digital Centre"
    assert tender.reference_no == "NE/NGCDF/OT/01/2026/2027"
    assert tender.category == "Works"
    assert tender.source_url == "https://tenders.go.ke/website/tenders/303654"


def test_the_procuring_entity_wins_over_the_source_default() -> None:
    """`pe` is the body actually buying — far more useful than "Government of Kenya"."""
    [tender] = PpipApiSource().parse(_result([ROW]))
    assert tender.entity == "NAROK EAST NG CDF"


def test_a_row_with_no_entity_falls_back_to_the_source() -> None:
    [tender] = PpipApiSource().parse(_result([{**ROW, "pe": None}]))
    assert tender.entity == "Government of Kenya"


def test_the_closing_time_survives_parsing() -> None:
    """10:00 on the day. A bid at 11:00 is an hour late, not a day early."""
    [tender] = PpipApiSource().parse(_result([ROW]))
    closing = parse_date(tender.closing_text)

    assert closing is not None
    # 10:00 EAT is 07:00 UTC.
    assert (closing.hour, closing.minute) == (7, 0)
    assert closing.date().isoformat() == "2026-08-25"


def test_rows_without_a_title_are_skipped_not_faked() -> None:
    tenders = PpipApiSource().parse(_result([ROW, {**ROW, "id": 9, "title": ""}]))
    assert len(tenders) == 1


def test_empty_extras_are_dropped_rather_than_stored_as_blanks() -> None:
    [tender] = PpipApiSource().parse(_result([{**ROW, "venue": None, "ocid": None}]))
    assert "venue" not in tender.extra
    assert "ocid" not in tender.extra
    assert tender.extra["method"] == "Open Tender"


# --- pagination --------------------------------------------------------------


async def test_every_page_is_walked() -> None:
    client = _FakeClient(
        [
            _page([{**ROW, "id": 1}], current=1, last=3),
            _page([{**ROW, "id": 2}], current=2, last=3),
            _page([{**ROW, "id": 3}], current=3, last=3),
        ]
    )
    result = await PpipApiSource().fetch(client)

    assert len(client.urls) == 3
    assert client.urls[0].endswith("page=1")
    assert len(json.loads(result.html)["data"]) == 3


async def test_a_single_page_response_stops_immediately() -> None:
    client = _FakeClient([_page([ROW], current=1, last=1)])
    await PpipApiSource().fetch(client)
    assert len(client.urls) == 1


async def test_pagination_is_capped() -> None:
    """A `last_page` that never arrives must not walk forever."""
    client = _FakeClient([_page([ROW], current=n, last=10_000) for n in range(1, MAX_PAGES + 50)])
    await PpipApiSource().fetch(client)
    assert len(client.urls) == MAX_PAGES


# --- failing loudly ----------------------------------------------------------


async def test_html_instead_of_json_is_a_source_failure() -> None:
    class _HtmlClient(_FakeClient):
        async def fetch(self, source_key: str, url: str) -> FetchResult:
            return FetchResult(
                source_key=source_key,
                url=url,
                html="<!DOCTYPE html><html><body>nope</body></html>",
                fetched_at=datetime.now(UTC),
                status_code=200,
                snapshot_id=uuid.uuid4(),
            )

    with pytest.raises(SourceUnavailableError, match="not JSON"):
        await PpipApiSource().fetch(_HtmlClient([]))


async def test_a_missing_data_array_is_a_source_failure() -> None:
    client = _FakeClient([{"current_page": 1, "last_page": 1}])
    with pytest.raises(SourceUnavailableError, match="`data` array"):
        await PpipApiSource().fetch(client)


def test_rows_that_all_fail_to_map_are_reported_not_swallowed() -> None:
    """Silently returning zero tenders would read as "no tenders today"."""
    with pytest.raises(SourceUnavailableError, match="none of them usable"):
        PpipApiSource().parse(_result([{"id": 1}, {"id": 2}]))


# --- wiring ------------------------------------------------------------------


def test_the_registry_builds_the_json_adapter_for_ppip() -> None:
    from batanat_api.tenders.sources import build_sources

    [source] = build_sources(["ppip"])
    assert isinstance(source, PpipApiSource)
    assert source.listing_url == "https://tenders.go.ke/api/active-tenders"


def test_the_other_sources_still_use_the_table_parser() -> None:
    from batanat_api.tenders.sources import ResilientTableSource, build_sources

    for source in build_sources(["rerec", "kplc", "kengen", "ketraco"]):
        assert isinstance(source, ResilientTableSource)


def test_the_seed_row_and_the_config_agree_on_the_adapter() -> None:
    """The seeder reads `adapter` off the config; drift here means a dead source."""
    from batanat_api.db.seed import TENDER_SOURCES

    ppip = next(row for row in TENDER_SOURCES if row["key"] == "ppip")
    assert ppip["adapter"] == "PpipApiSource"
