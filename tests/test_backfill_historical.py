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
    [
        "CA", "DC", "AZ", "DE", "KS", "ME", "VT", "TX", "FL", "HI", "KY", "NM",
        "MD", "WI", "MN", "MS", "IL", "OH",
    ],
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


# ---------------------------------------------------------------------------
# Wave 2A fetch/parse helpers — MD / WI / MN / MS / IL
# ---------------------------------------------------------------------------

_MD_ARCHIVE_HTML = (
    b"<table>"
    b"<tr><td><strong>Notice Date</strong></td><td><strong>NAICS Code</strong></td>"
    b"<td><strong>Company</strong></td><td><strong>Location</strong></td>"
    b"<td><strong>WIA Code</strong></td><td><strong>Total Employees</strong></td>"
    b"<td><strong>Effective Date</strong></td><td><strong>Type Code</strong></td></tr>"
    b"<tr><td>3/15/2010</td><td>336399</td><td>Marada Industries</td>"
    b"<td>100 Main St Westminster, MD 21157</td><td>9</td><td>84</td>"
    b"<td>5/14/2010</td><td>CL</td></tr>"
    b"</table>"
)


@respx.mock
def test_md_fetch_year_200_and_404():
    from warn_v2.scrapers.states.md import _fetch_md_year

    respx.get("https://www.dllr.state.md.us/employment/warn2010.shtml").mock(
        return_value=httpx.Response(200, content=_MD_ARCHIVE_HTML)
    )
    respx.get("https://www.dllr.state.md.us/employment/warn2005.shtml").mock(
        return_value=httpx.Response(404)
    )

    assert _fetch_md_year(2010) == _MD_ARCHIVE_HTML
    assert _fetch_md_year(2005) is None


def test_md_parse_handles_archive_header_aliases():
    """2010-era pages use 'WIA Code'/'Type Code' instead of 'Local Area'/'Type'."""
    from warn_v2.scrapers.states.md import MDScraper

    rows = MDScraper().parse(_MD_ARCHIVE_HTML)
    assert len(rows) == 1
    row = rows[0]
    assert row.employer == "Marada Industries"
    assert row.notice_date == date(2010, 3, 15)
    assert row.closure_type == "CL"
    assert row.city == "Westminster"
    assert row.zip == "21157"


_WI_ARCHIVE_HTML = (
    b"<html><table><tr>"
    b"<th>Company</th><th>City</th><th>Affected Workers</th>"
    b"<th>Notice Received</th><th>Original Notice Type / Update Type</th>"
    b"<th>Layoff Begin Date</th><th>County</th>"
    b"<th>Workforce Development Area</th></tr>"
    b"<tr><td>Prinsco</td><td>Appleton</td><td>33</td><td>12/5/2018</td>"
    b"<td>CL</td><td>02/04/2019 Plastics Pipe Mfg</td><td>Outagamie</td>"
    b"<td>Bay Area</td></tr></table>"
    b"<table><tr><td>nav junk</td></tr></table></html>"
)


@respx.mock
def test_wi_fetch_archive_year_bounds_and_http():
    from warn_v2.scrapers.states.wi import _fetch_wi_archive_year

    respx.get("https://dwd.wisconsin.gov/dislocatedworker/warn/2018/default.htm").mock(
        return_value=httpx.Response(200, content=_WI_ARCHIVE_HTML)
    )

    assert _fetch_wi_archive_year(2018) == _WI_ARCHIVE_HTML
    # Outside the static-page era: no HTTP call, just None.
    assert _fetch_wi_archive_year(2015) is None
    assert _fetch_wi_archive_year(2020) is None


def test_parse_wi_archive_html_extracts_rows():
    from warn_v2.scrapers.states.wi import parse_wi_archive_html

    rows = parse_wi_archive_html(_WI_ARCHIVE_HTML, 2018)
    assert len(rows) == 1
    row = rows[0]
    assert row.employer == "Prinsco"
    assert row.notice_date == date(2018, 12, 5)
    # Leading date is split off the glued "date + industry" cell.
    assert row.effective_date == date(2019, 2, 4)
    assert row.layoff_count == 33
    assert row.city == "Appleton"
    assert row.county == "Outagamie"
    assert row.closure_type == "CL"
    assert "2018" in row.source_url


@respx.mock
def test_backfill_historical_wi_year_routes_archive_parser(db) -> None:
    """WI registry entry wires _fetch_wi_archive_year + parse_wi_archive_html."""
    respx.get("https://dwd.wisconsin.gov/dislocatedworker/warn/2018/default.htm").mock(
        return_value=httpx.Response(200, content=_WI_ARCHIVE_HTML)
    )

    stats = backfill_historical("WI", year_start=2018, year_end=2018, dry_run=True)

    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 1
    assert db.query(Notice).count() == 0


@respx.mock
def test_mn_discover_archive_pdf_urls_filters_and_sorts():
    """Monthly PDFs become Wayback replay URLs; annuals and non-reports drop."""
    from warn_v2.scrapers.states.mn import _CDX_API, _discover_archive_pdf_urls

    base = "https://mn.gov/deed/assets"
    cdx = [
        ["original", "timestamp"],
        [f"{base}/plant-closing-mass-layoff-warn-2026-january_x.pdf", "20260201000000"],
        # Annual summary (no month token) — excluded until a parser exists.
        [f"{base}/mass-layoff-summary-2018_y.pdf", "20190101000000"],
        [f"{base}/unrelated-budget-report.pdf", "20240101000000"],
        [f"{base}/plant-closing-april-2022_z.pdf", "20220501000000"],
        [f"{base}/plant-closing-april-2022_z.pdf", "20220601000000"],
        [f"{base}/some-page.html", "20240101000000"],
    ]
    respx.get(_CDX_API).mock(return_value=httpx.Response(200, json=cdx))

    urls = _discover_archive_pdf_urls()
    assert urls == [
        "https://web.archive.org/web/20220501000000id_/"
        "https://mn.gov/deed/assets/plant-closing-april-2022_z.pdf",
        "https://web.archive.org/web/20260201000000id_/"
        "https://mn.gov/deed/assets/plant-closing-mass-layoff-warn-2026-january_x.pdf",
    ]


def test_mn_is_annual_archive_url():
    from warn_v2.scrapers.states.mn import _is_annual_archive_url

    assert _is_annual_archive_url("https://mn.gov/deed/assets/mass-layoff-summary-2018_y.pdf")
    assert _is_annual_archive_url("https://mn.gov/deed/assets/plant-closing-mass-layoff-2021_z.pdf")
    assert not _is_annual_archive_url("https://mn.gov/deed/assets/plant-closing-april-2022_z.pdf")
    assert not _is_annual_archive_url("https://mn.gov/deed/assets/mass-layoff-summary0715_a.pdf")


def test_mn_parse_archive_pdf_strips_trailing_year():
    """Annual-era PDFs glue the report year onto employer names."""
    from warn_v2.scrapers.states import mn

    fake = [
        NoticeRow(state="MN", employer="National Recoveries 2021", notice_date=date(2021, 10, 15)),
        NoticeRow(state="MN", employer="Coleman", notice_date=date(2021, 8, 31)),
    ]
    with patch.object(mn, "_parse_pdf", return_value=fake):
        rows = mn._parse_archive_pdf(b"%PDF-1.4", "https://mn.gov/x.pdf")

    assert [r.employer for r in rows] == ["National Recoveries", "Coleman"]


def test_ms_parse_old_quarterly_merged_company_city():
    """PY2020-PY2022 quarterlies merge 'Company Name, City' into one column whose
    cell ends with a 'City (County)' line — split into employer/city/county."""
    from pathlib import Path

    from warn_v2.scrapers.states.ms import _parse_pdf

    pdf_bytes = (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "ms" / "sample_merged_city.pdf"
    ).read_bytes()

    rows = _parse_pdf(pdf_bytes)
    assert len(rows) == 1
    row = rows[0]
    assert row.employer == "Anthem, Inc./ Beacon Health Options"
    assert row.notice_date == date(2021, 9, 21)
    assert row.city == "Hernando"
    assert row.county == "Desoto"
    assert row.layoff_count == 4
    assert row.closure_type == "Layoff"


@respx.mock
def test_backfill_historical_ms_ingests_all_discovered_pdfs(db) -> None:
    """MS ingests every discovered quarterly PDF (the live scraper takes only [0])."""
    from pathlib import Path

    pdf_bytes = (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "ms" / "sample.pdf"
    ).read_bytes()

    urls = [
        "https://mdes.ms.gov/media/1/warn-py2021-qtr-1.pdf",
        "https://mdes.ms.gov/media/2/warn-py2021-qtr-2.pdf",
    ]
    for u in urls:
        respx.get(u).mock(return_value=httpx.Response(200, content=pdf_bytes))

    with patch(
        "warn_v2.scripts.backfill_historical._discover_ms_pdf_urls", return_value=urls
    ):
        stats = backfill_historical("MS", dry_run=True)

    assert stats["years_attempted"] == 2
    assert stats["years_ok"] == 2
    assert stats["rows_seen"] > 0
    assert db.query(Notice).count() == 0


@respx.mock
def test_il_discover_archive_xlsx_urls_unwraps_and_excludes_pdfs():
    from warn_v2.scrapers.states.il import _ARCHIVE_URL, _discover_archive_xlsx_urls

    html = (
        b"<html>"
        b"<a href='/_layouts/15/download.aspx?SourceUrl=https://www.illinoisworknet.com"
        b"/DownloadPrint/Jan2026MonthlyWARNReport.xlsx'>Jan 2026</a>"
        b"<a href='/_layouts/download.aspx?SourceUrl=https://www.illinoisworknet.com"
        b"/DownloadPrint/April%202020%20Monthly%20WARN%20Report.xlsx'>Apr 2020</a>"
        b"<a href='/_layouts/download.aspx?SourceUrl=https://www.illinoisworknet.com"
        b"/DownloadPrint/April%202005%20WARN.pdf'>Apr 2005 (PDF)</a>"
        b"<a href='/DownloadPrint/Direct.xls'>direct</a>"
        b"<a href='/_layouts/15/download.aspx?SourceUrl=https://www.illinoisworknet.com"
        b"/DownloadPrint/Jan2026MonthlyWARNReport.xlsx'>dup</a>"
        b"</html>"
    )
    respx.get(_ARCHIVE_URL).mock(return_value=httpx.Response(200, content=html))

    urls = _discover_archive_xlsx_urls()
    assert urls == [
        "https://www.illinoisworknet.com/DownloadPrint/Jan2026MonthlyWARNReport.xlsx",
        # Percent-encoding preserved (filename contains spaces).
        "https://www.illinoisworknet.com/DownloadPrint/April%202020%20Monthly%20WARN%20Report.xlsx",
        "https://www.illinoisworknet.com/DownloadPrint/Direct.xls",
    ]


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


# ---------------------------------------------------------------------------
# Wave 2B — OH (four era formats, see docs/historical-sources.md)
# ---------------------------------------------------------------------------

def _oh_fixture(name: str) -> bytes:
    from pathlib import Path

    return (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "oh" / name
    ).read_bytes()


def test_oh_year_sources_cover_all_eras():
    from warn_v2.scrapers.states.oh import _oh_year_sources

    assert _oh_year_sources(1996) == [
        "https://web.archive.org/web/2005id_/http://jfs.ohio.gov/warn/WARN_1996.pdf"
    ]
    assert _oh_year_sources(2005) == [
        "https://web.archive.org/web/2009id_/http://jfs.ohio.gov/warn/Warn_2005.pdf"
    ]
    # .stm era tries slug variants, all via Wayback
    urls_2010 = _oh_year_sources(2010)
    assert len(urls_2010) == 4
    assert all("web.archive.org" in u for u in urls_2010)
    # 2020: Wayback archive.stm only (live portal page is an empty shell)
    urls_2020 = _oh_year_sources(2020)
    assert urls_2020 == [
        "https://web.archive.org/web/2023id_/https://jfs.ohio.gov/warn/archive.stm?year=2020"
    ]
    # 2021: live portal first, Wayback archive.stm fallback
    urls_2021 = _oh_year_sources(2021)
    assert "jfs.ohio.gov/job-services-and-unemployment" in urls_2021[0]
    assert urls_2021[0].endswith(
        "2021-public-notices-of-layoffs-and-closures-sa/"
        "2021-public-notices-of-layoffs-and-closures"
    )
    assert "archive.stm" in urls_2021[1]
    # 2023/2024 parent slug has no -sa suffix
    assert "-sa/" not in _oh_year_sources(2023)[0]
    # 2025: no known source
    assert _oh_year_sources(2025) == []


def test_parse_oh_year_era_a_pdf():
    """1996-2003 per-year PDFs: text lines, bare city, 2-digit years."""
    from warn_v2.scrapers.states.oh import parse_oh_year

    rows = parse_oh_year(_oh_fixture("warn_2000.pdf"), 2000)
    assert len(rows) > 50
    first = rows[0]
    assert first.employer == "York International"
    assert first.notice_date == date(2000, 12, 26)
    assert first.city == "Elyria"
    assert first.layoff_count == 175
    assert first.effective_date == date(2001, 2, 28)


def test_parse_oh_year_era_b_pdf():
    """2007-2019 Excel-exported PDFs: 'City (County)' in the company blob."""
    from warn_v2.scrapers.states.oh import parse_oh_year

    rows = parse_oh_year(_oh_fixture("warn_2010.pdf"), 2010)
    assert len(rows) > 50
    first = rows[0]
    assert first.employer == "Magna Steyr"
    assert first.city == "Toledo"
    assert first.county == "Lucas"
    assert first.layoff_count == 213
    assert first.effective_date == date(2011, 2, 28)


def test_oh_split_employer_city_prefixes():
    from warn_v2.scrapers.states.oh import _split_employer_city

    assert _split_employer_city("Acme Steel East Liverpool (Columbiana)") == (
        "Acme Steel", "East Liverpool", "Columbiana"
    )
    assert _split_employer_city("Acme Steel New Philadelphia") == (
        "Acme Steel", "New Philadelphia", None
    )
    assert _split_employer_city("Acme Steel Toledo") == ("Acme Steel", "Toledo", None)


_OH_PORTAL_HTML = (
    b'<html><div id="js-placeholder-json-data" class="hidden">'
    b'{"data":[["s","h","s","s","s","s","s","s","s"],'
    b'["Company","URL","Date Received","City/County","Potential Number Affected",'
    b'"Layoff Date(s)","Phone Number","Union","Notice ID"],'
    b'["OneTouchPoint","https://jfs.ohio.gov/static/warn/pdf/OneTouchPoint.pdf",'
    b'"12/1/21","Cincinnati/Hamilton","65","12/01/2021 to 01/31/2022",'
    b'"(414) 902-2655","None","013-21-025"]]}'
    b"</div></html>"
)


def test_parse_oh_year_portal_json():
    from warn_v2.scrapers.states.oh import parse_oh_year

    rows = parse_oh_year(_OH_PORTAL_HTML, 2021)
    assert len(rows) == 1
    row = rows[0]
    assert row.employer == "OneTouchPoint"
    assert row.notice_date == date(2021, 12, 1)
    assert row.city == "Cincinnati"
    assert row.county == "Hamilton"
    assert row.layoff_count == 65
    assert row.effective_date == date(2021, 12, 1)
    assert row.raw_notice_url.endswith("OneTouchPoint.pdf")
    assert row.extra["warn_id"] == "013-21-025"


_OH_ARCHIVE_HTML = (
    b"<html>"
    b"<table><tr><td>A-Z index of services</td></tr></table>"
    b"<table><tr><th>Date Received</th><th>Company</th><th>City/County</th>"
    b"<th>Potential Number Affected</th><th>Layoff Date(s)</th>"
    b"<th>Phone Number</th><th>Union</th><th>Notice ID</th></tr>"
    b"<tr><td>12/01/2021</td><td>OneTouchPoint</td><td>Cincinnati/Hamilton</td>"
    b"<td>65</td><td>12/01/2021 to 01/31/2022</td><td>(414) 902-2655</td>"
    b"<td>None</td><td>013-21-025</td></tr></table></html>"
)


def test_parse_oh_year_archive_html_skips_nav_table():
    from warn_v2.scrapers.states.oh import parse_oh_year

    rows = parse_oh_year(_OH_ARCHIVE_HTML, 2021)
    assert len(rows) == 1
    assert rows[0].employer == "OneTouchPoint"
    assert rows[0].city == "Cincinnati"


@respx.mock
def test_oh_fetch_year_falls_through_candidates():
    """First candidate 404s; the Wayback fallback with valid content wins."""
    from warn_v2.scrapers.states.oh import _fetch_oh_year, _oh_year_sources

    urls = _oh_year_sources(2021)
    respx.get(urls[0]).mock(return_value=httpx.Response(404))
    respx.get(urls[1]).mock(return_value=httpx.Response(200, content=_OH_ARCHIVE_HTML))

    assert _fetch_oh_year(2021) == _OH_ARCHIVE_HTML


@respx.mock
def test_oh_fetch_year_rejects_shell_pages():
    """A 200 page without table/JSON markers (soft-404 shell) is not data."""
    from warn_v2.scrapers.states.oh import _fetch_oh_year, _oh_year_sources

    for u in _oh_year_sources(2020):
        respx.get(u).mock(return_value=httpx.Response(200, content=b"<html>shell</html>"))

    assert _fetch_oh_year(2020) is None
