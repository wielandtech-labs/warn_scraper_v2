"""Tests for backfill_historical — per-state fetch helpers and ingest loop."""
from __future__ import annotations

import io
import json
import logging
from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import openpyxl
import pytest
import respx

from warn_v2.db.models import Notice
from warn_v2.scrapers.base import NoticeRow
from warn_v2.scripts.backfill_historical import backfill_historical

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_ca_xlsx(employer: str = "Acme Corp", notice_date=date(2022, 3, 1)) -> bytes:
    """Build a minimal CA-format XLSX (matches CAScraper.parse expectations)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["State of California EDD WARN"])
    ws.append([""])
    ws.append([
        "Company", "County/Parish", "Notice Date", "Effective Date",
        "Layoff/Closure", "No. Of Employees", "Address",
    ])
    ws.append([employer, "Los Angeles", notice_date, date(2022, 5, 1),
               "Layoff", 100, "100 Main St, Los Angeles, CA 90001"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _minimal_dc_html(employer: str = "DC Agency", notice_date: str = "January 15, 2020") -> bytes:
    return (
        b"<table>"
        b"<tr><th>Notice Date</th><th>Organization Name</th>"
        b"<th>Number toEmployees Affected</th><th>Effective Layoff Date</th>"
        b"<th>Code Type</th></tr>"
        b"<tr><td>" + notice_date.encode() + b"</td>"
        b"<td>" + employer.encode() + b"</td>"
        b"<td>50</td><td>March 15, 2020</td><td>1</td></tr>"
        b"</table>"
    )


def _minimal_joblink_bundle(employer: str = "AZ Corp", city: str = "Phoenix") -> bytes:
    search_html = (
        f"<table><tbody>"
        f"<tr><td><a href='/warn_lookups/1'>{employer}</a></td>"
        f"<td>{city}</td><td>85001</td><td>Area</td>"
        f"<td>2022-03-01</td><td>Layoff</td></tr>"
        f"</tbody></table>"
    )
    return json.dumps({"search_html": search_html, "details": {}}).encode()


# ---------------------------------------------------------------------------
# CA — _discover_archive_xlsx_urls
# ---------------------------------------------------------------------------

@respx.mock
def test_ca_discover_urls_finds_pdf_and_xlsx_hrefs():
    """Archive page with PDF and XLSX historical links; current-year XLSX excluded."""
    from warn_v2.scrapers.states.ca import _ARCHIVE_PAGE, _discover_archive_urls

    html = (
        b"<html><body>"
        b"<a href='/Jobs_and_Training/warn/WARN_Report_FY23-24.pdf'>FY23-24 (PDF)</a>"
        b"<a href='/Jobs_and_Training/warn/WARN_Report_FY22-23.pdf'>FY22-23 (PDF)</a>"
        b"<a href='/Jobs_and_Training/warn/WARN_Report_FY21-22.xlsx'>FY21-22</a>"
        b"<a href='/Jobs_and_Training/warn/WARN_Report.xlsx'>Current</a>"
        b"<a href='/some/other-doc.pdf'>unrelated</a>"
        b"</body></html>"
    )
    respx.get(_ARCHIVE_PAGE).mock(return_value=httpx.Response(200, content=html))

    urls = _discover_archive_urls()
    assert len(urls) == 3
    assert all("warn" in u.lower() for u in urls)
    assert not any(u.endswith("WARN_Report.xlsx") for u in urls)


@respx.mock
def test_ca_discover_urls_empty_when_no_files():
    from warn_v2.scrapers.states.ca import _ARCHIVE_PAGE, _discover_archive_urls

    respx.get(_ARCHIVE_PAGE).mock(return_value=httpx.Response(200, content=b"<html></html>"))
    assert _discover_archive_urls() == []


# ---------------------------------------------------------------------------
# DC — _fetch_dc_year
# ---------------------------------------------------------------------------

@respx.mock
def test_dc_fetch_year_returns_bytes_when_table_present():
    from warn_v2.scrapers.states.dc import _fetch_dc_year

    url = "https://does.dc.gov/page/industry-closings-and-layoffs-warn-notifications-2020"
    respx.get(url).mock(return_value=httpx.Response(200, content=_minimal_dc_html()))

    result = _fetch_dc_year(2020)
    assert result is not None
    assert b"Organization Name" in result


@respx.mock
def test_dc_fetch_year_returns_none_when_no_table():
    from warn_v2.scrapers.states.dc import _fetch_dc_year

    url = "https://does.dc.gov/page/industry-closings-and-layoffs-warn-notifications-2050"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"<html>No data</html>"))

    assert _fetch_dc_year(2050) is None


@respx.mock
def test_dc_fetch_year_returns_none_on_http_error():
    from warn_v2.scrapers.states.dc import _fetch_dc_year

    url = "https://does.dc.gov/page/industry-closings-and-layoffs-warn-notifications-2099"
    respx.get(url).mock(return_value=httpx.Response(404))

    assert _fetch_dc_year(2099) is None


# ---------------------------------------------------------------------------
# JobLink — fetch(year=Y)
# ---------------------------------------------------------------------------

@respx.mock
def test_joblink_fetch_uses_year_param():
    """Calling fetch(year=2020) must request the 2020 date range."""
    from warn_v2.scrapers.states.az import AZScraper

    scraper = AZScraper()
    search_url = (
        "https://www.azjobconnection.gov/search/warn_lookups"
        "?utf8=%E2%9C%93&q%5Bnotice_eq%5D=true"
        "&q%5Bnotice_on_gteq%5D=2020-01-01"
        "&q%5Bnotice_on_lteq%5D=2020-12-31"
        "&q%5Bs%5D=notice_on+desc&commit=Search"
    )
    respx.get(search_url).mock(
        return_value=httpx.Response(200, content=b"<html><table></table></html>")
    )

    raw = scraper.fetch(year=2020)
    bundle = json.loads(raw)
    assert "search_html" in bundle
    assert "details" in bundle


# ---------------------------------------------------------------------------
# backfill_historical — DC end-to-end (mocked fetch)
# ---------------------------------------------------------------------------

def test_backfill_historical_dc_loops_years_and_upserts(db) -> None:
    html_2020 = _minimal_dc_html("Agency Alpha", "January 15, 2020")
    html_2021 = _minimal_dc_html("Agency Beta", "March 10, 2021")

    with patch("warn_v2.scripts.backfill_historical._fetch_dc_year") as mock_fetch:
        mock_fetch.side_effect = lambda y: {2020: html_2020, 2021: html_2021}.get(y)

        with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
            # Wire the mock session_scope to use the test DB
            mock_scope.return_value.__enter__ = lambda _: db
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)

            stats = backfill_historical("DC", year_start=2020, year_end=2021)

    assert stats["years_attempted"] == 2
    assert stats["years_ok"] == 2
    assert stats["rows_seen"] == 2


def test_backfill_historical_dc_dry_run_no_writes(db) -> None:
    html = _minimal_dc_html()

    with patch("warn_v2.scripts.backfill_historical._fetch_dc_year", return_value=html):
        stats = backfill_historical("DC", year_start=2020, year_end=2020, dry_run=True)

    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 1
    assert db.query(Notice).count() == 0


def test_backfill_historical_dc_skips_missing_year() -> None:
    with patch("warn_v2.scripts.backfill_historical._fetch_dc_year", return_value=None):
        stats = backfill_historical("DC", year_start=2050, year_end=2050, dry_run=True)

    assert stats["years_attempted"] == 1
    assert stats["years_ok"] == 0


def test_backfill_historical_unsupported_state() -> None:
    with pytest.raises(ValueError, match="does not support"):
        backfill_historical("WY")


# ---------------------------------------------------------------------------
# backfill_historical — CA end-to-end (mocked discovery + fetch)
# ---------------------------------------------------------------------------

@respx.mock
def test_backfill_historical_ca_upserts_rows_xlsx(db) -> None:
    archive_url = "https://edd.ca.gov/Jobs_and_Training/warn/WARN_Report_FY22-23.xlsx"
    xlsx_bytes = _minimal_ca_xlsx()

    respx.get(archive_url).mock(return_value=httpx.Response(200, content=xlsx_bytes))

    with patch("warn_v2.scripts.backfill_historical._discover_archive_urls") as mock_disc:
        mock_disc.return_value = [archive_url]

        with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
            mock_scope.return_value.__enter__ = lambda _: db
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)

            stats = backfill_historical("CA")

    assert stats["years_attempted"] == 1
    assert stats["years_ok"] == 1
    assert stats["rows_seen"] >= 1


# ---------------------------------------------------------------------------
# Registry — JobLink states (KS/ME/VT) and supported set
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "state",
    ["CA", "DC", "AZ", "DE", "KS", "ME", "VT", "TX", "FL", "HI", "KY", "NM"],
)
def test_supported_states_in_registry(state) -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL, _SUPPORTED

    assert state in _SUPPORTED
    spec = _BACKFILL[state]
    assert (spec.fetch_year is None) != (spec.discover_urls is None)


# ---------------------------------------------------------------------------
# Wave 1 fetch helpers — TX / FL / HI / KY / NM
# ---------------------------------------------------------------------------

@respx.mock
def test_tx_fetch_year_returns_bytes_and_updates_source_url():
    from warn_v2.scrapers.states.tx import TXScraper, _fetch_tx_year

    scraper = TXScraper()
    url = "https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-2021-twc.xlsx"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"xlsx-bytes"))

    assert _fetch_tx_year(scraper, 2021) == b"xlsx-bytes"
    assert scraper.source_url == url


@respx.mock
def test_tx_fetch_year_returns_none_on_404():
    from warn_v2.scrapers.states.tx import TXScraper, _fetch_tx_year

    url = "https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-2018-twc.xlsx"
    respx.get(url).mock(return_value=httpx.Response(404))

    assert _fetch_tx_year(TXScraper(), 2018) is None


@respx.mock
def test_fl_fetch_year_follows_pagination():
    from warn_v2.scrapers.states.fl import FLScraper, _fetch_fl_year

    base = "https://reactwarn.floridajobs.org/WarnList/Records?year=2020"
    page1 = (
        b"<html><table id='DataTable'><tbody><tr><td>row</td></tr></tbody></table>"
        b"<a href='/WarnList/Records?year=2020&page=2'>2</a></html>"
    )
    page2 = b"<html><table id='DataTable'><tbody></tbody></table>1 2</html>"
    respx.get(base).mock(return_value=httpx.Response(200, content=page1))
    respx.get(f"{base}&page=2").mock(return_value=httpx.Response(200, content=page2))

    chunks = _fetch_fl_year(FLScraper(), 2020)
    assert chunks == [page1, page2]


@respx.mock
def test_fl_fetch_year_single_page_does_not_confuse_page_numbers():
    """A link to page=20 of another context must not be read as page=2."""
    from warn_v2.scrapers.states.fl import FLScraper, _fetch_fl_year

    base = "https://reactwarn.floridajobs.org/WarnList/Records?year=2021"
    page1 = (
        b"<html><table></table>"
        b"<a href='/WarnList/Records?year=2021&page=20'>20</a></html>"
    )
    respx.get(base).mock(return_value=httpx.Response(200, content=page1))

    assert _fetch_fl_year(FLScraper(), 2021) == [page1]


@respx.mock
def test_fl_fetch_year_returns_none_on_404():
    from warn_v2.scrapers.states.fl import FLScraper, _fetch_fl_year

    base = "https://reactwarn.floridajobs.org/WarnList/Records?year=2010"
    respx.get(base).mock(return_value=httpx.Response(404))

    assert _fetch_fl_year(FLScraper(), 2010) is None


@respx.mock
def test_hi_fetch_year_200_and_404():
    from warn_v2.scrapers.states.hi import _fetch_hi_year

    respx.get("https://labor.hawaii.gov/wdc/2019-warn-notices/").mock(
        return_value=httpx.Response(200, content=b"<html>hi</html>")
    )
    respx.get("https://labor.hawaii.gov/wdc/2015-warn-notices/").mock(
        return_value=httpx.Response(404)
    )

    assert _fetch_hi_year(2019) == b"<html>hi</html>"
    assert _fetch_hi_year(2015) is None


@respx.mock
def test_ky_fetch_year_downloads_discovered_csv():
    from warn_v2.scrapers.states.ky import _fetch_ky_year

    api = (
        "https://kcc.ky.gov/_api/web/GetFolderByServerRelativeUrl("
        "'/WARN notices/WARN Notices 2022')/Files"
    )
    feed = (
        b"<?xml version='1.0'?><feed xmlns:d='http://schemas.microsoft.com/ado/"
        b"2007/08/dataservices'><entry><d:Name>2022-12-31 WARN.csv</d:Name>"
        b"</entry></feed>"
    )
    respx.get(api).mock(return_value=httpx.Response(200, content=feed))
    respx.get(
        "https://kcc.ky.gov/WARN%20notices/WARN%20Notices%202022/2022-12-31%20WARN.csv"
    ).mock(return_value=httpx.Response(200, content=b"csv-bytes"))

    assert _fetch_ky_year(2022) == b"csv-bytes"


@respx.mock
def test_ky_fetch_year_returns_none_for_empty_folder():
    from warn_v2.scrapers.states.ky import _fetch_ky_year

    api = (
        "https://kcc.ky.gov/_api/web/GetFolderByServerRelativeUrl("
        "'/WARN notices/WARN Notices 2015')/Files"
    )
    respx.get(api).mock(
        return_value=httpx.Response(200, content=b"<?xml version='1.0'?><feed></feed>")
    )

    assert _fetch_ky_year(2015) is None


@respx.mock
def test_nm_discover_archive_pdf_urls():
    from warn_v2.scrapers.states.nm import _PAGE_URL, _discover_archive_pdf_urls

    html = (
        b"<html>"
        b"<a href='/Portals/0/DM/Business/2023_WARN.pdf'>2023</a>"
        b"<a href='/Portals/0/DM/Business/2018_WARN10042018.pdf'>2018</a>"
        b"<a href='/Portals/0/DM/Business/other-report.pdf'>not warn</a>"
        b"<a href='/Rapid-Response'>page</a>"
        b"</html>"
    )
    respx.get(_PAGE_URL).mock(return_value=httpx.Response(200, content=html))

    urls = _discover_archive_pdf_urls()
    assert urls == [
        "https://www.dws.state.nm.us/Portals/0/DM/Business/2023_WARN.pdf",
        "https://www.dws.state.nm.us/Portals/0/DM/Business/2018_WARN10042018.pdf",
    ]


@respx.mock
def test_backfill_historical_vt_joblink_year(db) -> None:
    """VT (JobLink platform) backfills via fetch(year=Y) like AZ/DE."""
    search_url = (
        "https://www.vermontjoblink.com/search/warn_lookups"
        "?utf8=%E2%9C%93&q%5Bnotice_eq%5D=true"
        "&q%5Bnotice_on_gteq%5D=2003-01-01"
        "&q%5Bnotice_on_lteq%5D=2003-12-31"
        "&q%5Bs%5D=notice_on+desc&commit=Search"
    )
    # No anchor in the row → no detail-page fetches.
    html = (
        b"<html><table><tbody>"
        b"<tr><td>Vermont Tubbs Inc</td><td>Rutland</td><td>05701</td>"
        b"<td>Area</td><td>2003-07-31</td><td>Closure</td></tr>"
        b"</tbody></table></html>"
    )
    respx.get(search_url).mock(return_value=httpx.Response(200, content=html))

    stats = backfill_historical("VT", year_start=2003, year_end=2003, dry_run=True)

    assert stats["years_attempted"] == 1
    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 1
    assert db.query(Notice).count() == 0


# ---------------------------------------------------------------------------
# Year loop — paginated sources (list[bytes] from fetch_year)
# ---------------------------------------------------------------------------

def test_backfill_historical_paginated_year_ingests_all_chunks(db) -> None:
    html_p1 = _minimal_dc_html("Agency Alpha", "January 15, 2020")
    html_p2 = _minimal_dc_html("Agency Beta", "February 20, 2020")

    with patch(
        "warn_v2.scripts.backfill_historical._fetch_dc_year",
        return_value=[html_p1, html_p2],
    ):
        with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
            mock_scope.return_value.__enter__ = lambda _: db
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)

            stats = backfill_historical("DC", year_start=2020, year_end=2020)

    assert stats["years_attempted"] == 2  # one per chunk
    assert stats["years_ok"] == 2
    assert stats["rows_seen"] == 2


# ---------------------------------------------------------------------------
# Dry run — duplicate preview (near misses)
# ---------------------------------------------------------------------------

def test_dry_run_reports_near_miss(db, caplog) -> None:
    """A row matching an existing notice on (state, employer, date) but hashing
    differently (city drift) is flagged as a near miss, and nothing is written."""
    from warn_v2.pipeline.storage import upsert_notices

    seeded = NoticeRow(
        state="DC", employer="DC Agency", notice_date=date(2020, 1, 15),
        city="Anacostia",
    )
    upsert_notices(db, [seeded])
    db.commit()

    html = _minimal_dc_html("DC Agency", "January 15, 2020")  # no city column
    caplog.set_level(logging.INFO, logger="warn_v2.scripts.backfill_historical")

    with patch("warn_v2.scripts.backfill_historical._fetch_dc_year", return_value=html):
        stats = backfill_historical("DC", year_start=2020, year_end=2020, dry_run=True)

    assert stats["rows_seen"] == 1
    assert "near_miss=1" in caplog.text
    assert db.query(Notice).count() == 1  # only the seeded row


@respx.mock
def test_backfill_historical_ca_upserts_rows_pdf(db) -> None:
    """PDF archive URLs are dispatched to parse_ca_pdf instead of scraper.parse."""
    archive_url = "https://edd.ca.gov/Jobs_and_Training/warn/WARN_Report_FY21-22.pdf"
    fake_rows = [
        NoticeRow(state="CA", employer="PDF Corp", notice_date=date(2022, 1, 5), layoff_count=50)
    ]

    respx.get(archive_url).mock(return_value=httpx.Response(200, content=b"%PDF-1.4 fake"))

    with patch("warn_v2.scripts.backfill_historical._discover_archive_urls") as mock_disc:
        mock_disc.return_value = [archive_url]
        with patch("warn_v2.scripts.backfill_historical.parse_ca_pdf", return_value=fake_rows):
            with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
                mock_scope.return_value.__enter__ = lambda _: db
                mock_scope.return_value.__exit__ = MagicMock(return_value=False)

                stats = backfill_historical("CA")

    assert stats["years_attempted"] == 1
    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 1
