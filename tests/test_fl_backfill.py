"""FL historical backfill (1998-2019): warn.asp era parser + pinned captures.

Fixtures are trimmed Wayback captures from the 2026-07 backfill sweep:
- warn_asp_1999_trimmed.html — early warn.asp era (first 6 data rows of 1999)
- warn_asp_2015_trimmed.html — late warn.asp era (first 6 data rows of 2015)
- reactwarn_2019_page2_trimmed.html — reactwarn 2019 page 2 (first 5 rows)
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states import fl
from warn_v2.scrapers.states.fl import (
    _ASP_CAPTURES,
    _REACTWARN_2019_CAPTURES,
    FLScraper,
    _fetch_fl_year,
    parse_fl_warn_asp,
    parse_fl_year,
)

FIXTURES = (
    Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "fl"
)


@pytest.fixture
def asp_1999() -> bytes:
    return (FIXTURES / "warn_asp_1999_trimmed.html").read_bytes()


@pytest.fixture
def asp_2015() -> bytes:
    return (FIXTURES / "warn_asp_2015_trimmed.html").read_bytes()


@pytest.fixture
def reactwarn_2019() -> bytes:
    return (FIXTURES / "reactwarn_2019_page2_trimmed.html").read_bytes()


# ---------------------------------------------------------------------------
# warn.asp era parser (1998-2018)
# ---------------------------------------------------------------------------

def test_asp_early_era_parses_glued_name_address_cell(asp_1999: bytes) -> None:
    rows = parse_fl_warn_asp(asp_1999, 1999)
    assert len(rows) == 6

    first = rows[0]
    assert first.state == "FL"
    # The first <td> glues name + street + "City, FL  ZIP" — all split apart.
    assert first.employer == "Pallet Management Systems, Inc."
    assert first.address == "2420 New Tampa Highway, Lakeland, FL  33615"
    assert first.city == "Lakeland"
    assert first.zip == "33615"
    assert first.notice_date == date(1999, 12, 21)
    assert first.effective_date == date(2000, 2, 7)
    assert first.layoff_count == 55
    assert first.extra["industry"] == "Manufacturing"

    ts, url = _ASP_CAPTURES[1999]
    assert first.source_url == f"https://web.archive.org/web/{ts}id_/{url}"
    # City/ZIP must come out of the glued cell for every row.
    assert all(r.city and r.zip for r in rows)


def test_asp_late_era_takes_start_of_thru_range(asp_2015: bytes) -> None:
    rows = parse_fl_warn_asp(asp_2015, 2015)
    assert len(rows) == 6

    first = rows[0]
    assert first.employer == "Frederick J. Hanna & Associates, P.C."
    assert first.city == "Plantation"
    assert first.zip == "33324"
    assert first.notice_date == date(2015, 12, 22)
    assert first.effective_date == date(2016, 2, 10)

    # Row 2's layoff cell is "1/31/2016 <I>thru</I> 2/14/2016" — keep the start.
    ranged = rows[1]
    assert ranged.employer == "MV Transportation, Inc."
    assert ranged.effective_date == date(2016, 1, 31)
    assert all(r.city and r.zip for r in rows)


def test_asp_first_row_not_duplicated_by_layout_table(asp_1999: bytes) -> None:
    # The data table nests inside a layout table whose lone <tr> re-exposes
    # the first data row's cells; a naive table walk ingests row 1 twice.
    rows = parse_fl_warn_asp(asp_1999, 1999)
    assert [r.employer for r in rows[:2]] == [
        "Pallet Management Systems, Inc.",
        "AutoNation USA",
    ]


def _asp_page(first_cell: str) -> bytes:
    return (
        "<html><table border=1><tr><th>COMPANY NAME</th><th>NOTICE DATE</th>"
        "<th>LAYOFF DATE</th><th>EMPLOYEES AFFECTED</th><th>INDUSTRY</th></tr>"
        f"<tr><td>{first_cell}</td><td>12/1/2005</td>"
        "<td>1/9/2006<br><I>thru</I><br>2/1/2006</td><td>50</td>"
        "<td>Industry Not Provided</td></tr></table></html>"
    ).encode()


def test_asp_out_of_state_hq_address_still_yields_city() -> None:
    # Some notices list the out-of-state HQ as the address.
    cell = "<font>Weblink Wireless</font><br>333 Lee Parkway<br>Dallas, TX  75219"
    rows = parse_fl_warn_asp(_asp_page(cell), 2005)
    assert len(rows) == 1
    assert rows[0].city == "Dallas"
    assert rows[0].zip == "75219"
    assert rows[0].effective_date == date(2006, 1, 9)
    # "Industry Not Provided" is a placeholder, not an industry.
    assert rows[0].extra == {}


def test_asp_doubled_state_zip_suffix_is_stripped() -> None:
    # 2005 has a source row with the ", FL ZIP" suffix doubled.
    cell = (
        "<font>Titan Cruise Lines</font><br>100 First Ave. S., 2nd Floor"
        "<br>St. Petersburg, FL 33701, FL  33701"
    )
    rows = parse_fl_warn_asp(_asp_page(cell), 2005)
    assert rows[0].city == "St. Petersburg"
    assert rows[0].zip == "33701"


def test_asp_header_only_table_parses_to_zero_rows() -> None:
    # The pinned 2012 capture holds the header but no data rows — that's a
    # legitimate empty year (the site had dropped 2012), not a parse failure.
    raw = (
        b"<html><table><tr><td><table border=1><tr><th>COMPANY NAME</th>"
        b"<th>NOTICE DATE</th></tr></table></td></tr></table></html>"
    )
    assert parse_fl_warn_asp(raw, 2012) == []


def test_asp_raises_without_data_table() -> None:
    with pytest.raises(ParseFailed):
        parse_fl_warn_asp(b"<html><p>service unavailable</p></html>", 2005)


# ---------------------------------------------------------------------------
# parse_fl_year dispatch
# ---------------------------------------------------------------------------

def test_parse_fl_year_routes_2019_to_reactwarn_parser(reactwarn_2019: bytes) -> None:
    rows = parse_fl_year(reactwarn_2019, 2019)
    assert len(rows) == 5

    first = rows[0]
    assert first.employer == "Adcomm, Inc."
    assert first.city == "Merritt Island"
    assert first.zip == "32953"
    assert first.notice_date == date(2019, 5, 2)
    assert first.effective_date == date(2019, 6, 30)
    assert first.layoff_count == 71
    assert first.raw_notice_url is not None
    assert first.raw_notice_url.startswith(
        "https://reactwarn.floridajobs.org/WarnList/DownloadAzureFile?file="
    )


def test_parse_fl_year_routes_asp_years_to_asp_parser(asp_2015: bytes) -> None:
    rows = parse_fl_year(asp_2015, 2015)
    assert rows == parse_fl_warn_asp(asp_2015, 2015)


# ---------------------------------------------------------------------------
# _fetch_fl_year routing
# ---------------------------------------------------------------------------

def test_fetch_year_asp_era_uses_pinned_replay(monkeypatch) -> None:
    fetched: list[str] = []

    def fake_fetch(url: str) -> bytes:
        fetched.append(url)
        return b"raw-page"

    monkeypatch.setattr(fl.wayback, "fetch", fake_fetch)
    scraper = FLScraper()

    assert _fetch_fl_year(scraper, 2005) == [b"raw-page"]
    ts, url = _ASP_CAPTURES[2005]
    expected = f"https://web.archive.org/web/{ts}id_/{url}"
    assert fetched == [expected]
    assert scraper.source_url == expected


def test_fetch_year_asp_era_missing_capture_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        fl.wayback, "fetch", lambda url: pytest.fail("must not hit the network")
    )
    assert _fetch_fl_year(FLScraper(), 1997) is None


def test_fetch_year_2019_returns_both_pinned_pages(monkeypatch) -> None:
    monkeypatch.setattr(fl.wayback, "fetch", lambda url: url.encode())
    scraper = FLScraper()

    chunks = _fetch_fl_year(scraper, 2019)
    expected = [
        f"https://web.archive.org/web/{ts}id_/{url}".encode()
        for ts, url in _REACTWARN_2019_CAPTURES
    ]
    assert chunks == expected
    # parse() stamps rows with source_url — pinned to the year page's replay.
    assert scraper.source_url == expected[0].decode()


def test_backfill_spec_extends_fl_to_1998() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["FL"]
    assert spec.year_start == 1998
    assert spec.fetch_year is _fetch_fl_year
    assert spec.parse_year is parse_fl_year
