"""Tests for backfill_historical — per-state fetch helpers and ingest loop."""
from __future__ import annotations

import io
import json
import logging
from datetime import date
from pathlib import Path
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
    # Chunk runs are recorded with the backfill_ prefix so they never shadow
    # the live scraper's latest run in health checks.
    from warn_v2.db.models import ScraperRun

    assert {r.status for r in db.query(ScraperRun).filter_by(state="DC")} == {"backfill_ok"}


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
        "MD", "WI", "MN", "MS", "IL", "OH", "LA", "NV",
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
def test_ky_discover_workbook_picks_most_recently_modified_xlsx():
    """The workbook route ignores CSVs and picks the newest .xlsx by
    TimeLastModified (file names are too inconsistent to sort)."""
    from warn_v2.scrapers.states.ky import _discover_workbook_urls

    year = date.today().year
    api = (
        "https://kcc.ky.gov/_api/web/GetFolderByServerRelativeUrl("
        f"'/WARN notices/WARN Notices {year}')/Files?$select=Name,TimeLastModified"
    )
    feed = (
        b"<?xml version='1.0'?><feed xmlns:d='http://schemas.microsoft.com/ado/"
        b"2007/08/dataservices' xmlns:m='http://schemas.microsoft.com/ado/2007/"
        b"08/dataservices/metadata'>"
        b"<entry><content><m:properties><d:Name>WARN Report latest.csv</d:Name>"
        b"<d:TimeLastModified>2026-07-01T15:54:53Z</d:TimeLastModified>"
        b"</m:properties></content></entry>"
        b"<entry><content><m:properties><d:Name>WARN  Notice newest.xlsx</d:Name>"
        b"<d:TimeLastModified>2026-04-24T19:59:03Z</d:TimeLastModified>"
        b"</m:properties></content></entry>"
        b"<entry><content><m:properties><d:Name>WARN Notice older.xlsx</d:Name>"
        b"<d:TimeLastModified>2026-01-20T09:06:05Z</d:TimeLastModified>"
        b"</m:properties></content></entry>"
        b"</feed>"
    )
    respx.get(api).mock(return_value=httpx.Response(200, content=feed))

    urls = _discover_workbook_urls()
    assert urls == [
        f"https://kcc.ky.gov/WARN%20notices/WARN%20Notices%20{year}/"
        "WARN%20%20Notice%20newest.xlsx"
    ]


def test_ky_workbook_parses_per_year_sheets_pre_csv_era_only():
    """Real workbook fixture: one sheet per year 2017-2026; sheets for the
    CSV era (2025+) are skipped so backfill cannot duplicate CSV rows."""
    from warn_v2.scrapers.states.ky import parse_ky_workbook

    fixture = (
        Path(__file__).resolve().parent.parent
        / "warn_v2" / "scrapers" / "fixtures" / "ky" / "workbook.xlsx"
    )
    rows = parse_ky_workbook(fixture.read_bytes())

    years = {r.notice_date.year for r in rows}
    assert min(years) == 2017
    assert max(years) <= 2024
    assert len(rows) > 300  # 2017-2024 sheets hold ~356 rows
    assert all(r.state == "KY" for r in rows)
    sample = next(r for r in rows if r.employer == "Bel USA, Inc")
    assert sample.notice_date == date(2024, 12, 11)
    assert sample.layoff_count == 270
    assert sample.county == "Hardin"
    assert sample.closure_type == "Closure"


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
    """Report PDFs (monthly and annual) become Wayback replay URLs."""
    from warn_v2.scrapers.states.mn import _CDX_API, _discover_archive_pdf_urls

    base = "https://mn.gov/deed/assets"
    cdx = [
        ["original", "timestamp"],
        [f"{base}/plant-closing-mass-layoff-warn-2026-january_x.pdf", "20260201000000"],
        [f"{base}/mass-layoff-summary-2018_y.pdf", "20190101000000"],
        [f"{base}/unrelated-budget-report.pdf", "20240101000000"],
        [f"{base}/plant-closing-april-2022_z.pdf", "20220501000000"],
        [f"{base}/plant-closing-april-2022_z.pdf", "20220601000000"],
        [f"{base}/some-page.html", "20240101000000"],
    ]
    respx.get(_CDX_API).mock(return_value=httpx.Response(200, json=cdx))

    urls = _discover_archive_pdf_urls()
    assert urls == [
        "https://web.archive.org/web/20190101000000id_/"
        "https://mn.gov/deed/assets/mass-layoff-summary-2018_y.pdf",
        "https://web.archive.org/web/20220501000000id_/"
        "https://mn.gov/deed/assets/plant-closing-april-2022_z.pdf",
        "https://web.archive.org/web/20260201000000id_/"
        "https://mn.gov/deed/assets/plant-closing-mass-layoff-warn-2026-january_x.pdf",
    ]


def test_mn_archive_file_year():
    """Filename year detection ignores the _tcm asset token; MMYY handled."""
    from warn_v2.scrapers.states.mn import _archive_file_year

    assert _archive_file_year("https://x/plant-closing-mass-layoff-2021_tcm1045-515051.pdf") == 2021
    assert _archive_file_year("https://x/mass-layoff-summary0815_tcm1045-133763.pdf") == 2015
    assert _archive_file_year("https://x/mass-layoff-summary-mar2016_tcm1045-226970.pdf") == 2016
    assert (
        _archive_file_year("https://x/plant-closing-mass-layoff-warn-2026-january_tcm1045-722872.pdf")
        == 2026
    )
    assert _archive_file_year("https://x/dwp-mass-layoff-english_tcm1045-259927.pdf") is None


def test_mn_parse_archive_pdf_routes_2025_plus_to_live_chain():
    """2025+ files keep the live parser chain (identical hashing with live rows)."""
    from warn_v2.scrapers.states import mn

    fake = [
        NoticeRow(state="MN", employer="National Recoveries 2025", notice_date=date(2025, 10, 15)),
        NoticeRow(state="MN", employer="Coleman", notice_date=date(2025, 8, 31)),
    ]
    with patch.object(mn, "_parse_pdf", return_value=fake) as parse_pdf:
        rows = mn._parse_archive_pdf(b"%PDF-1.4", "https://mn.gov/plant-closing-warn-march-2025.pdf")

    parse_pdf.assert_called_once()
    assert [r.employer for r in rows] == ["National Recoveries", "Coleman"]


_MN_FIXTURES = Path(__file__).resolve().parents[1] / "warn_v2" / "scrapers" / "fixtures" / "mn"


def test_mn_parse_archive_2015_monthly():
    """2015-16 era: Name|City|Start|Industry|Count|WARN|Provider|Status|TAA."""
    from warn_v2.scrapers.states import mn

    rows = mn._parse_archive_pdf(
        (_MN_FIXTURES / "archive_monthly_2015_08.pdf").read_bytes(),
        "https://web.archive.org/web/x/mass-layoff-summary0815_tcm1045-133763.pdf",
    )
    assert [r.employer for r in rows] == ["Sivantos", "Univita Health"]  # WARN=YES only
    sivantos = rows[0]
    assert sivantos.city == "Plymouth"
    assert sivantos.layoff_count == 96
    assert sivantos.notice_date == date(2015, 8, 17)  # no WARN Received column
    assert sivantos.extra["industry"] == "Manufacturing"
    # "Univita Health 2015" wraps its city onto a second line ("Eden"/"Prairie").
    assert rows[1].city == "Eden Prairie"


def test_mn_parse_archive_2016_cumulative():
    """Dec-2016 era reorders columns (Industry before Start) and runs 24 pages
    of month sections cumulatively back through 2014."""
    from warn_v2.scrapers.states import mn

    rows = mn._parse_archive_pdf(
        (_MN_FIXTURES / "archive_cumulative_2016_12.pdf").read_bytes(),
        "https://web.archive.org/web/x/mass-layoff-summary-december-2016_tcm1045-270006.pdf",
    )
    assert len(rows) == 112
    assert all(r.notice_date is not None for r in rows)
    years = {r.notice_date.year for r in rows}
    assert 2014 in years and 2016 in years
    elite = next(r for r in rows if r.employer.startswith("Elite Line Services"))
    assert elite.city == "St Paul"
    assert elite.layoff_count == 86
    assert elite.notice_date == date(2017, 1, 31)
    assert elite.extra["industry"] == "Accommodation"


def test_mn_parse_archive_2021_annual():
    """2021+ era adds WARN Received; its value can print left of its own
    header label (into the WARN Act column) and must be reassigned."""
    from warn_v2.scrapers.states import mn

    rows = mn._parse_archive_pdf(
        (_MN_FIXTURES / "archive_annual_2021.pdf").read_bytes(),
        "https://web.archive.org/web/x/plant-closing-mass-layoff-2021_tcm1045-515051.pdf",
    )
    assert len(rows) == 11
    nr = next(r for r in rows if r.employer == "National Recoveries")  # year stripped
    assert nr.notice_date == date(2021, 10, 15)  # WARN Received
    assert nr.effective_date == date(2021, 10, 1)  # Layoff Start
    assert nr.city == "Arden Hills"
    assert nr.layoff_count == 60
    assert nr.closure_type == "Workforce Reduction"


def test_mn_parse_archive_2024_monthly():
    """2023-24 era prints the whole header on one dense line (vocabulary split)
    and no lines-strategy table exists at all."""
    from warn_v2.scrapers.states import mn

    rows = mn._parse_archive_pdf(
        (_MN_FIXTURES / "archive_monthly_2024_04.pdf").read_bytes(),
        "https://web.archive.org/web/x/plant-closing-mass-layoff-warn-april-2024_tcm1045-623664.pdf",
    )
    assert [r.employer for r in rows] == ["Aramark at General Mills"]
    aramark = rows[0]
    assert aramark.city == "Golden Valley"
    assert aramark.notice_date == date(2024, 4, 4)
    assert aramark.effective_date == date(2024, 5, 31)
    assert aramark.layoff_count == 56


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


def test_nj_parse_archive_xlsx():
    """The cumulative NJ workbook (one sheet per year, 2004+) parses with the
    live PDF parser's semantics; footnote/blank/spillover rows are dropped."""
    from warn_v2.scrapers.states.nj import ARCHIVE_XLSX_URL, parse_nj_archive_xlsx

    rows = parse_nj_archive_xlsx(
        (
            Path(__file__).resolve().parents[1]
            / "warn_v2" / "scrapers" / "fixtures" / "nj" / "archive_sample.xlsx"
        ).read_bytes()
    )

    assert {r.notice_date.year for r in rows} == {2004, 2007, 2009, 2021, 2023}
    assert all(r.state == "NJ" and r.source_url == ARCHIVE_XLSX_URL for r in rows)

    pnc = next(r for r in rows if r.employer == "PNC FINANCIAL")
    assert pnc.notice_date == date(2004, 1, 1)  # Month Posted + sheet year
    assert pnc.effective_date == date(2004, 3, 19)  # datetime cell
    assert (pnc.layoff_count, pnc.city) == (131, "BRIDGEWATER")

    jc = next(r for r in rows if r.employer == "JOHNSON CONTROLS")
    assert jc.effective_date == date(2007, 3, 4)  # nbsp-padded string date

    dash = next(r for r in rows if r.employer == "UNIVERSAL FOLDING BOX")
    assert dash.layoff_count is None  # workforce cell is '-'

    # 2009 footnote row ('* Most employees...') and blank rows are skipped.
    assert [r.employer for r in rows if r.notice_date.year == 2009] == ["Alcan Baltek"]
    # The 2023 sheet ends with a January row duplicated from the 2024 sheet;
    # dating it 2023-01 would mint a mis-dated near-duplicate — dropped.
    assert not any("ACME" in r.employer for r in rows)


def test_nj_parse_archive_xlsx_raises_on_bad_bytes():
    from warn_v2.scrapers.base import ParseFailed
    from warn_v2.scrapers.states.nj import parse_nj_archive_xlsx

    with pytest.raises(ParseFailed):
        parse_nj_archive_xlsx(b"this is not a workbook")


def test_ms_parse_stacked_header_quarterly():
    """PY2023-PY2024 quarterlies stack header labels across rows ('Date of' /
    'WARN' / 'Notice') and pad the grid with ghost columns; the '(County)'
    line can wrap below its city inside the merged company cell."""
    from pathlib import Path

    from warn_v2.scrapers.states.ms import _parse_pdf

    pdf_bytes = (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "ms" / "sample_stacked_header.pdf"
    ).read_bytes()

    rows = _parse_pdf(pdf_bytes)
    assert len(rows) == 3
    first = rows[0]
    assert first.employer == "View Operating Corporation"
    assert first.notice_date == date(2024, 10, 3)
    assert first.city == "Olive Branch"
    assert first.county == "DeSoto"
    assert first.layoff_count == 147
    assert first.closure_type == "Layoff"
    levi = next(r for r in rows if "Levi Strauss" in r.employer)
    assert (levi.city, levi.county) == ("Canton", "Madison")


def test_ms_parse_stacked_wide_quarterly():
    """The PY2024 Q4 variant pads the same stacked layout out to 25 grid
    columns and appends a summary page, which must not be ingested as data."""
    from pathlib import Path

    from warn_v2.scrapers.states.ms import _parse_pdf

    pdf_bytes = (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "ms" / "sample_stacked_wide.pdf"
    ).read_bytes()

    rows = _parse_pdf(pdf_bytes)
    assert len(rows) == 7  # matches the PDF's own summary total
    first = rows[0]
    assert first.employer == "NauticStar Boats"
    assert first.notice_date == date(2025, 3, 18)
    assert first.effective_date == date(2025, 4, 17)
    assert (first.city, first.county) == ("Amory", "Monroe")
    assert first.layoff_count == 47
    assert all("notices" not in r.employer.lower() for r in rows)  # no summary rows


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


@pytest.fixture
def _no_stm_cdx(monkeypatch):
    """Stub the .stm-era CDX discovery so source-list tests stay offline."""
    from warn_v2.scrapers.states import oh

    monkeypatch.setattr(oh, "_stm_replay_urls", lambda: {})


def test_oh_year_sources_cover_all_eras(_no_stm_cdx):
    from warn_v2.scrapers.states.oh import _oh_year_sources

    assert _oh_year_sources(1996) == [
        "https://web.archive.org/web/2005id_/http://jfs.ohio.gov/warn/WARN_1996.pdf"
    ]
    assert _oh_year_sources(2005) == [
        "https://web.archive.org/web/2009id_/http://jfs.ohio.gov/warn/Warn_2005.pdf"
    ]
    # .stm era tries slug variants, all via Wayback (no CDX pin here — stubbed)
    urls_2010 = _oh_year_sources(2010)
    assert len(urls_2010) == 4
    assert all("web.archive.org" in u for u in urls_2010)
    # 2020: Wayback archive.stm only (live portal page is an empty shell)
    urls_2020 = _oh_year_sources(2020)
    assert urls_2020 == [
        "https://web.archive.org/web/2023id_/https://jfs.ohio.gov/warn/archive.stm?year=2020"
    ]
    # 2021: live year page first, then old-portal capture, then archive.stm
    urls_2021 = _oh_year_sources(2021)
    assert urls_2021[0] == (
        "https://jfs.ohio.gov/job-workforce-services/job-programs-and-services/"
        "submit-a-warn-notice/2021-public-notices-of-layoffs-and-closures"
    )
    assert "jfs.ohio.gov/job-services-and-unemployment" in urls_2021[1]
    assert urls_2021[1].endswith(
        "2021-public-notices-of-layoffs-and-closures-sa/"
        "2021-public-notices-of-layoffs-and-closures"
    )
    assert "archive.stm" in urls_2021[2]
    # 2023/2024: live year page + old-portal capture (parent slug has no -sa)
    urls_2023 = _oh_year_sources(2023)
    assert urls_2023[0].endswith("/2023-public-notices-of-layoffs-and-closures")
    assert "web.archive.org/web/20250601id_/" in urls_2023[1]
    assert "-sa/" not in urls_2023[1]
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


def test_parse_oh_pdf_line_excel_serial_layoff_date():
    """A layoff-date cell rendered as a bare Excel serial must not be
    concatenated into the count (WARN_2003's AD-EX line: '110 37971' became
    layoff_count=11037971)."""
    from warn_v2.scrapers.states.oh import _excel_serial_date, _parse_oh_pdf_line

    row = _parse_oh_pdf_line(
        "09/23/03",
        "Affinity Displays & Expositions Inc. dba AD-EX Cincinnati 110 37971 "
        "(513) 771-2339 None 724-03-024",
        2003,
    )
    assert row is not None
    assert row.layoff_count == 110
    assert row.effective_date == date(2003, 12, 16)  # serial 37971
    assert row.city == "Cincinnati"

    # Only serials landing in the file's year window (Y..Y+1) decode; anything
    # else is not treated as a date.
    assert _excel_serial_date("37971", 2003) == date(2003, 12, 16)
    assert _excel_serial_date("38200", 2003) == date(2004, 8, 1)  # spillover ok
    assert _excel_serial_date("12345", 2003) is None  # 1933 — not a layoff date
    assert _excel_serial_date("37971", 2010) is None  # wrong file year


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


@pytest.fixture
def _no_wayback_delays(monkeypatch):
    """Zero the Wayback politeness delays so fetch tests don't sleep."""
    from warn_v2.scrapers.states import oh

    monkeypatch.setattr(oh, "_WAYBACK_DELAY", 0.0)
    monkeypatch.setattr(oh, "_WAYBACK_BACKOFF", 0.0)


@respx.mock
def test_oh_fetch_year_falls_through_candidates(_no_wayback_delays):
    """First candidate 404s; the Wayback fallback with valid content wins."""
    from warn_v2.scrapers.states.oh import _fetch_oh_year, _oh_year_sources

    urls = _oh_year_sources(2021)
    respx.get(urls[0]).mock(return_value=httpx.Response(404))
    respx.get(urls[1]).mock(return_value=httpx.Response(200, content=_OH_ARCHIVE_HTML))

    assert _fetch_oh_year(2021) == _OH_ARCHIVE_HTML


@respx.mock
def test_oh_fetch_year_rejects_shell_pages(_no_wayback_delays):
    """A 200 page without table/JSON markers (soft-404 shell) is not data."""
    from warn_v2.scrapers.states.oh import _fetch_oh_year, _oh_year_sources

    for u in _oh_year_sources(2020):
        respx.get(u).mock(return_value=httpx.Response(200, content=b"<html>shell</html>"))

    assert _fetch_oh_year(2020) is None


@respx.mock
def test_oh_fetch_year_retries_throttled_wayback(_no_wayback_delays, _no_stm_cdx):
    """A throttled Wayback response (429) is retried once after a backoff."""
    from warn_v2.scrapers.states.oh import _fetch_oh_year, _oh_year_sources

    url = _oh_year_sources(2010)[0]
    respx.get(url).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, content=b"%PDF-1.4 era pdf"),
        ]
    )

    raw = _fetch_oh_year(2010)
    assert raw == b"%PDF-1.4 era pdf"


@pytest.fixture
def _fresh_stm_cdx_cache():
    """Clear the lru_cache around tests that exercise the real CDX discovery."""
    from warn_v2.scrapers.states.oh import _stm_replay_urls

    _stm_replay_urls.cache_clear()
    yield
    _stm_replay_urls.cache_clear()


@respx.mock
def test_oh_stm_replay_urls_pins_latest_200_capture(_no_wayback_delays, _fresh_stm_cdx_cache):
    """CDX discovery picks the latest 200 capture per year and skips junk URLs."""
    from warn_v2.scrapers.states.oh import _CDX_API, _oh_year_sources, _stm_replay_urls

    cdx = [
        ["timestamp", "original"],
        ["20150311163358", "http://jfs.ohio.gov:80/warn/WARN_2011.stm"],
        ["20221108012742", "https://jfs.ohio.gov/warn/WARN_2011.stm"],
        ["20180102022009", "http://jfs.ohio.gov:80/warn/WARN2014.stm"],
        # Junk that must not match: trailing colon, per-notice .stm under /pdf/
        ["20250825013911", "https://jfs.ohio.gov/warn/WARN2018.stm:"],
        ["20230609235443", "https://jfs.ohio.gov/warn/pdf/2023-01-13-Energy-Harbor.stm"],
    ]
    respx.get(_CDX_API).mock(return_value=httpx.Response(200, json=cdx))

    urls = _stm_replay_urls()
    assert urls[2011] == (
        "https://web.archive.org/web/20221108012742id_/"
        "https://jfs.ohio.gov/warn/WARN_2011.stm"
    )
    assert urls[2014].endswith("WARN2014.stm")
    assert 2018 not in urls
    assert 2023 not in urls
    # The pinned snapshot leads the candidate list; anchored variants follow.
    sources = _oh_year_sources(2011)
    assert sources[0] == urls[2011]
    assert len(sources) == 5


@respx.mock
def test_oh_stm_replay_urls_empty_on_cdx_error(_no_wayback_delays, _fresh_stm_cdx_cache):
    """CDX failure degrades to the anchored slug variants, not a crash."""
    from warn_v2.scrapers.states.oh import _CDX_API, _oh_year_sources, _stm_replay_urls

    respx.get(_CDX_API).mock(return_value=httpx.Response(503))

    assert _stm_replay_urls() == {}
    assert len(_oh_year_sources(2010)) == 4


_OH_YEAR_CSV = (
    b"s,h,s,h,s,s,s,s,s,s\n"
    b",,,,,,,,,\n"
    b"Company,Company,Date Received,URL,City/County,Potential Number Affected,"
    b"Layoff Date(s),Phone Number,Union,Notice ID\n"
    b"Acme Logistics,Acme Logistics,12/23/24,"
    b"https://dam.assets.ohio.gov/image/upload/x.pdf,"
    b"Delaware/Delaware,151,2/21/25,(614) 555-0101,N,000-24-094\n"
    b"Compound Dates LLC,Compound Dates LLC,12/30/2024 & 12/24/2024,"
    b"https://dam.assets.ohio.gov/image/upload/y.pdf,"
    b"Columbus/Franklin,13,2/19/25,(614) 555-0102,N,000-24-095\n"
)


@respx.mock
def test_oh_fetch_year_follows_year_page_csv_link(_no_wayback_delays):
    """June-2026 year pages link a dam.assets CSV instead of embedding data."""
    from warn_v2.scrapers.states.oh import _fetch_oh_year, _oh_year_sources

    csv_url = "https://dam.assets.ohio.gov/raw/upload/v1/jfs.ohio.gov/2026/2024_warn_notice.csv"
    page = f'<html><a href="{csv_url}">2024 WARN CSV</a></html>'.encode()
    respx.get(_oh_year_sources(2024)[0]).mock(return_value=httpx.Response(200, content=page))
    respx.get(csv_url).mock(return_value=httpx.Response(200, content=_OH_YEAR_CSV))

    assert _fetch_oh_year(2024) == _OH_YEAR_CSV


def test_parse_oh_year_csv():
    """Year CSVs reuse the live CSV parser, re-sourced to the per-year page."""
    from warn_v2.scrapers.states.oh import parse_oh_year

    rows = parse_oh_year(_OH_YEAR_CSV, 2024)
    assert len(rows) == 2
    row = rows[0]
    assert row.employer == "Acme Logistics"
    assert row.notice_date == date(2024, 12, 23)
    assert row.city == "Delaware"
    assert row.county == "Delaware"
    assert row.layoff_count == 151
    # 2-digit layoff-date years ("2/21/25") are accepted.
    assert row.effective_date == date(2025, 2, 21)
    assert row.raw_notice_url.endswith("x.pdf")
    assert row.extra["warn_id"] == "000-24-094"
    assert row.source_url.endswith("/2024-public-notices-of-layoffs-and-closures")
    # Compound "Date Received" cells fall back to the first date.
    assert rows[1].notice_date == date(2024, 12, 30)


# ---------------------------------------------------------------------------
# Wave 2B — PA (archived month pages, portal + SharePoint eras)
# ---------------------------------------------------------------------------

def _pa_month_envelope(fixture: str, month: int) -> bytes:
    from pathlib import Path

    html = (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "pa" / fixture
    ).read_text(encoding="utf-8", errors="replace")
    return json.dumps({"month": month, "html": html}).encode()


def test_parse_pa_month_portal_era():
    """2001-2015 portal.state.pa.us pages: bold employer, standalone closure line."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_portal_2001_04.html", 4), 2001)
    assert len(rows) == 23
    first = rows[0]
    assert first.employer == "C-COR.net"
    assert first.notice_date == date(2001, 4, 1)  # month page -> first-of-month
    assert first.city == "Tipton"
    assert first.county == "Blair"
    assert first.zip == "16684"
    assert first.layoff_count == 418
    assert first.effective_date == date(2001, 5, 29)  # "05/29/01" 2-digit year
    assert first.closure_type == "PLANT CLOSING"
    # ZIP-less "Dunmore, PA" address still yields the city.
    assert rows[1].city == "Dunmore"
    assert rows[1].zip is None
    # No label/closure text ever leaks into employer names.
    assert not any(
        w in r.employer.upper()
        for r in rows
        for w in ("CLOSING", "CLOSURE", "LAYOFF", "AFFECTED", "COUNTY")
    )


def test_parse_pa_month_portal_multiword_closure_line():
    """'PLANT CLOSURE AND MASS LAYOFF' is a closure line, not a new employer."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_portal_2010_12.html", 12), 2010)
    assert len(rows) == 8
    ch = next(r for r in rows if "Hochman" in r.employer)
    assert ch.closure_type == "PLANT CLOSURE AND MASS LAYOFF"
    assert ch.layoff_count == 116
    assert ch.effective_date == date(2011, 2, 2)
    # Out-of-state HQ address ("New York, NY") must not produce a PA city.
    assert ch.city is None


def test_parse_pa_month_sharepoint_late_era():
    """~2021+ SharePoint pages label the type inline: 'CLOSING OR LAYOFF: X'."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_sp_2022_08.html", 8), 2022)
    assert len(rows) == 5
    first = rows[0]
    assert first.employer == "Conduit Global Inc."
    assert first.city == "Bethlehem"
    assert first.layoff_count == 175
    assert first.closure_type == "Closure"
    # Wave ranges take the first date: "1st Wave - 8/3/2022, 2nd Wave - ..."
    assert first.effective_date == date(2022, 8, 3)


def test_pa_fetch_year_hard_caps_at_live_era():
    """2023+ months are the AEM live scraper's territory — never backfilled."""
    from warn_v2.scrapers.states.pa import _fetch_pa_year

    assert _fetch_pa_year(2023) is None
    assert _fetch_pa_year(2024) is None


def test_oh_own_year_rows_drops_cross_year():
    """Per-year era files sometimes carry the previous year's listing appended
    (CDX-pinned WARN_2013.stm); those rows are junk or duplicates of the
    canonical year file and must be dropped."""
    from warn_v2.scrapers.states.oh import _own_year_rows

    mk = lambda y, m, d, emp: NoticeRow(  # noqa: E731
        state="OH", employer=emp, notice_date=date(y, m, d)
    )
    rows = [
        mk(2013, 8, 9, "Real Co"),
        mk(2012, 2, 28, "63"),        # wrapped-line fragment from the 2012 section
        mk(2012, 2, 21, "Kodak"),     # real notice, but 2012's file is canonical
    ]
    kept = _own_year_rows(rows, 2013)
    assert [r.employer for r in kept] == ["Real Co"]


def test_parse_pa_month_label_variants_2017_2020():
    """2017-2020 pages use 'LAYOFF EFFECTIVE DATE(S):' labels and '*UPDATE*'
    marker lines; neither may leak into employer names (they produced ~200
    bogus locationless rows in the first backfill run)."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_sp_2018_08.html", 8), 2018)
    assert not any(
        w in r.employer.upper()
        for r in rows
        for w in ("EFFECTIVE", "AFFECTED", "COUNTY:", "*UPDATE", "LAYOF")
    )
    hw = next(r for r in rows if "Harbison" in r.employer)
    # The '*UPDATE to January 29, 2018 WARN*' marker precedes the name in the
    # same bold block and must be skipped, not taken as the employer.
    assert hw.employer == "Harbison Walker International"
    assert hw.layoff_count == 88
    assert hw.effective_date == date(2018, 7, 27)  # LAYOFF EFFECTIVE DATE:
    assert hw.closure_type == "Closure"
    assert hw.city == "Claysburg"


def test_parse_pa_month_unstarred_update_and_contract_cancelled():
    """Sept 2014 has annotation lines without asterisks: a bare 'UPDATE' before
    an employer name and 'CONTRACT CANCELLED' between the label lines of a
    completed block. Neither may become an employer row (prod grew 'UPDATE' /
    'CONTRACT CANCELLED' rows from this month), and the annotation must not
    split its block's remaining labels into a bogus second notice."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_sp_2014_09.html", 9), 2014)
    assert len(rows) == 14
    assert not any(
        w in r.employer.upper() for r in rows for w in ("UPDATE", "CANCEL")
    )
    # The bare 'UPDATE' marker preceded Bank of America's name in its cell.
    boa = next(r for r in rows if r.employer == "Bank of America")
    assert boa.layoff_count == 2
    assert boa.effective_date == date(2014, 10, 26)
    assert boa.city == "Pittsburgh"
    # 'CONTRACT CANCELLED' sat between '# AFFECTED: 77' and 'EFFECTIVE DATE:';
    # the block must survive intact with both values.
    npb = next(r for r in rows if r.employer == "National Penn Bank")
    assert npb.layoff_count == 77
    assert npb.effective_date == date(2014, 10, 24)


def test_parse_pa_month_paren_update_markers():
    """Oct 2010 (portal era) uses parenthesized '(Updated WARN)' annotations;
    they must be skipped, not taken as employers."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_portal_2010_10.html", 10), 2010)
    assert len(rows) == 10
    assert not any("UPDAT" in r.employer.upper() for r in rows)
    sm = next(r for r in rows if r.employer == "St. Michaels School")
    assert sm.layoff_count == 136
    assert sm.effective_date == date(2010, 10, 29)
    assert sm.city == "Tunkhannock"


def test_parse_pa_month_not_specified_closure_slot():
    """Sept 2001: 'NOT SPECIFIED' stands in for the closure-type line between
    labels; it must not become an employer row, and the block it interrupts
    keeps its remaining labels (prod grew 3 'NOT SPECIFIED' rows from this)."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_portal_2001_09.html", 9), 2001)
    assert not any("SPECIFIED" in r.employer.upper() for r in rows)
    mw = next(r for r in rows if r.employer == "Mail-Well Envelope")
    assert mw.layoff_count == 112
    assert mw.effective_date == date(2001, 10, 29)
    assert mw.county == "Lehigh"


def test_parse_pa_month_bare_permanent_closure_line():
    """June 2013 writes just 'PERMANENT' where the closure line goes; it must
    be read as the closure type, not the next employer (prod grew 2
    'PERMANENT' rows). Full-line match only — an employer named 'X Temporary
    Services' must never be eaten as a closure line."""
    from warn_v2.scrapers.states.pa import _CLOSURE_LINE_RE, parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_sp_2013_06.html", 6), 2013)
    assert not any(r.employer.upper() == "PERMANENT" for r in rows)
    ab = next(r for r in rows if "Abraxas" in r.employer)
    assert ab.closure_type == "PERMANENT"
    assert ab.layoff_count == 63
    assert ab.effective_date == date(2013, 7, 19)
    assert not _CLOSURE_LINE_RE.match("Kelly Temporary Services")


def test_parse_pa_month_split_affected_label():
    """July 2004 wraps the '# AFFECTED:' label across lines ('#' then
    'AFFECTED: 101'). The lone '#' must not start a bogus employer row, and
    the count must land on the real employer (prod grew '#' rows with the
    real rows' counts lost)."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_portal_2004_07.html", 7), 2004)
    assert not any(r.employer == "#" for r in rows)
    bh = next(r for r in rows if r.employer == "Breuners Home")
    assert bh.layoff_count == 101
    assert bh.effective_date == date(2004, 7, 12)
    assert bh.closure_type == "PLANT CLOSING"


def test_parse_pa_month_monthname_effective_dates():
    """'LAYOFF EFFECTIVE DATES: May 30, 2019' — month-name dates parse."""
    from warn_v2.scrapers.states.pa import parse_pa_month

    rows = parse_pa_month(_pa_month_envelope("archive_sp_2019_02.html", 2), 2019)
    cm = next(r for r in rows if "Conemaugh" in r.employer)
    assert cm.effective_date == date(2019, 5, 30)
    assert cm.layoff_count == 100
    # Every row in this month resolves an effective date (source has none TBD).
    assert all(r.effective_date is not None for r in rows)


def test_parse_oh_pdf_line_wrapped_date_fragments():
    """.stm-era PDFs wrap long layoff-date cells, leaving fragments after the
    count; those must not merge into the count (prod saw 65 2009 -> 652009,
    57 4525 -> 574525, 394 and June 18, 2009 -> 182009)."""
    from warn_v2.scrapers.states.oh import _parse_oh_pdf_line

    # Month-name date fragment (optionally led by and/until/through).
    row = _parse_oh_pdf_line(
        "4/7/2009",
        "Alliance Castings Company, LLC Alliance (Stark) 394 and June 18, 2009 "
        "(330) 829-5600 Lodge DS30 006-08-171",
        2009,
    )
    assert row.layoff_count == 394
    assert row.effective_date == date(2009, 6, 18)

    # Bare-year fragment: count only, no date.
    row = _parse_oh_pdf_line(
        "3/31/2009",
        "Myers Industries Company) (Hancock) 54 2009 (419) 435-1811 #1915 007-08-167",
        2009,
    )
    assert row.layoff_count == 54
    assert row.effective_date is None

    # Other fragment (split phone number): implausible merge keeps the first
    # number.
    row = _parse_oh_pdf_line(
        "11/10/2008",
        "Rexam Closure Systems, Inc. (Wood) 57 4525 (419) 373-4525 UAW 007-08-063",
        2008,
    )
    assert row.layoff_count == 57

    # Plausible single-number splits ("1 ,200") still merge as before.
    row = _parse_oh_pdf_line("1/5/2000", "Acme Corp Dayton 1 ,200", 2000)
    assert row.layoff_count == 1200


# ---------------------------------------------------------------------------
# Wave 2C — NY (archived details.asp records via Wayback CDX)
# ---------------------------------------------------------------------------

def _ny_fixture(name: str) -> bytes:
    return (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "ny" / name
    ).read_bytes()


@respx.mock
def test_ny_discover_detail_urls_dedupes_by_id_latest_capture():
    """URL variants (scheme/www/_ga junk) collapse to one replay URL per id,
    keeping the latest timestamp; non-detail rows are ignored."""
    from warn_v2.scrapers.states.ny import _CDX_API, _discover_ny_detail_urls

    cdx = [
        ["timestamp", "original"],
        ["20090402165641", "http://www.labor.ny.gov/app/warn/details.asp?id=2127"],
        ["20150306060857", "https://labor.ny.gov/app/warn/details.asp?id=2127"],
        ["20200906172615", "https://www.labor.ny.gov/app/warn/details.asp?id=9073&_ga=2.30854839"],
        ["20090223200406", "http://www.labor.ny.gov/app/warn/details.asp?"],  # no id
        ["20140406215943", "http://www.labor.ny.gov/app/warn/default.asp?warnYr=2001"],
    ]
    respx.get(_CDX_API).mock(return_value=httpx.Response(200, json=cdx))

    urls = _discover_ny_detail_urls()
    assert urls == [
        "https://web.archive.org/web/20150306060857id_/"
        "https://labor.ny.gov/app/warn/details.asp?id=2127",
        "https://web.archive.org/web/20200906172615id_/"
        "https://www.labor.ny.gov/app/warn/details.asp?id=9073&_ga=2.30854839",
    ]


def test_parse_ny_detail_full_record_and_other_site():
    """Real 2009 capture (Kodak, id=2127): full main record plus the
    'Other site affected:' appendix as its own row."""
    from warn_v2.scrapers.states.ny import parse_ny_detail

    rows = parse_ny_detail(
        _ny_fixture("detail_2127.html"),
        "https://web.archive.org/web/20090402165641id_/"
        "http://www.labor.ny.gov/app/warn/details.asp?id=2127",
    )
    assert len(rows) == 2
    main, other = rows
    assert main.employer == "Eastman Kodak Company Office"  # control token stripped
    assert main.notice_date == date(2009, 3, 17)
    assert main.effective_date == date(2009, 6, 4)  # "To begin between 6/4/2009 and ..."
    assert main.layoff_count == 2
    assert main.city == "Rochester"
    assert main.zip == "14650"
    assert main.county == "Monroe"
    assert main.closure_type == "Plant Layoff"
    assert main.extra["control_number"] == "2008-W287 & W288"
    assert main.extra["region"] == "FINGER LAKES"
    # Wayback prefix stripped from the stored source.
    assert main.source_url == "http://www.labor.ny.gov/app/warn/details.asp?id=2127"

    assert other.employer == "Eastman Kodak, Kodak Research Labs"
    assert other.layoff_count == 8  # "(8 affected)"
    assert other.city == "Rochester"
    assert other.extra["control_number"] == "2008-W288"


def test_parse_ny_detail_empty_shell_returns_no_rows():
    """Some archived ids are chrome-only shells with no record body."""
    from warn_v2.scrapers.states.ny import parse_ny_detail

    html = b"<html><body><h1>WARN Details</h1><p>Contact Us</p></body></html>"
    assert parse_ny_detail(html, "http://x/details.asp?id=3") == []


def test_parse_ny_detail_dashes_mean_not_provided():
    from warn_v2.scrapers.states.ny import parse_ny_detail

    html = (
        b"<html><body><p>Date of Notice: 5/1/2005</p>"
        b"<p>Company: Acme Corp</p><p>12 Main St</p><p>Utica, NY 13501</p>"
        b"<p>County: Oneida | WIB: ONEIDA| Region: MOHAWK VALLEY</p>"
        b"<p>Number Affected: -----</p><p>Layoff Date: -----</p>"
        b"<p>Closing Date: 7/1/2005</p>"
        b"<p>Reason Stated for Filing: Plant Closing</p></body></html>"
    )
    (row,) = parse_ny_detail(html, "http://x/details.asp?id=500")
    assert row.layoff_count is None
    assert row.effective_date == date(2005, 7, 1)  # Closing Date fallback
    assert row.closure_type == "Plant Closing"
    assert row.city == "Utica"


@respx.mock
def test_backfill_historical_ny_url_list_with_limit(db) -> None:
    """NY runs in url-list mode; --limit slices the discovered list."""
    replay = (
        "https://web.archive.org/web/20090402165641id_/"
        "http://www.labor.ny.gov/app/warn/details.asp?id=2127"
    )
    respx.get(replay).mock(
        return_value=httpx.Response(200, content=_ny_fixture("detail_2127.html"))
    )

    with patch(
        "warn_v2.scripts.backfill_historical._discover_ny_detail_urls"
    ) as mock_disc:
        mock_disc.return_value = [replay, "https://web.archive.org/web/x/never-fetched"]
        with patch("warn_v2.scripts.backfill_historical.session_scope") as mock_scope:
            mock_scope.return_value.__enter__ = lambda _: db
            mock_scope.return_value.__exit__ = MagicMock(return_value=False)
            stats = backfill_historical("NY", limit=1)

    assert stats["years_attempted"] == 1  # second URL never fetched
    assert stats["rows_seen"] == 2  # main + other-site row
    assert db.query(Notice).filter(Notice.state == "NY").count() == 2


# ---------------------------------------------------------------------------
# NC — archive-hub discovery + three-era parse_nc_pdf
# ---------------------------------------------------------------------------

def _nc_fixture(name: str) -> bytes:
    return (
        Path(__file__).resolve().parents[1]
        / "warn_v2" / "scrapers" / "fixtures" / "nc" / name
    ).read_bytes()


@respx.mock
def test_nc_discover_pdf_urls_dedupes_years_and_absolutizes():
    """Hub lists three slug families back to 2014, newest first; one URL/year."""
    from warn_v2.scrapers.states.nc import _ARCHIVE_HUB, _discover_nc_pdf_urls

    html = (
        b"<html><body>"
        b"<a href='/.../report-workforce-warn-listings-2025/open'>2025</a>"
        b"<a href='/worker-adjustment-and-retraining-notification-warn-report-2021/open'>2021</a>"
        b"<a href='/warn-report-2019/open'>2019</a>"
        b"<a href='/warn-report-2014-0/open'>2014</a>"
        b"<a href='/warn-report-2014-0/open'>2014 dup</a>"
        b"<a href='/data-tools-reports/some-other-report-2023/open'>not warn</a>"
        b"<a href='/warn-summary-report-archives'>hub self-link</a>"
        b"</body></html>"
    )
    respx.get(_ARCHIVE_HUB).mock(return_value=httpx.Response(200, content=html))

    urls = _discover_nc_pdf_urls()
    assert urls == [
        "https://www.commerce.nc.gov/.../report-workforce-warn-listings-2025/open",
        "https://www.commerce.nc.gov/worker-adjustment-and-retraining-notification-warn-report-2021/open",
        "https://www.commerce.nc.gov/warn-report-2019/open",
        "https://www.commerce.nc.gov/warn-report-2014-0/open",
    ]


@respx.mock
def test_nc_discover_pdf_urls_empty_on_http_error():
    from warn_v2.scrapers.states.nc import _ARCHIVE_HUB, _discover_nc_pdf_urls

    respx.get(_ARCHIVE_HUB).mock(return_value=httpx.Response(500))
    assert _discover_nc_pdf_urls() == []


def test_nc_parse_pdf_summary_count_era():
    """2014-~2017 'WARN Notice - Summary Count' flowing text: word-position
    columns, monthly subtotal lines skipped, wrapped company names rejoined."""
    from warn_v2.scrapers.states.nc import parse_nc_pdf

    rows = parse_nc_pdf(_nc_fixture("archive_summary_2016.pdf"), "http://x/2016")
    assert len(rows) >= 15
    assert all(r.state == "NC" and r.source_url == "http://x/2016" for r in rows)

    first = rows[0]
    assert first.employer == "Daimler Trucks North America LLC"
    assert first.notice_date == date(2016, 1, 4)
    assert first.effective_date == date(2016, 3, 5)
    assert first.layoff_count == 936
    assert first.city == "Cleveland"
    assert first.closure_type == "Layoff/Temporary"

    # Company name wrapped across two lines is reassembled.
    morrison = next(r for r in rows if "Morrison" in r.employer)
    assert morrison.employer == "(Morrison Healthcare) Carolina Medical Center"
    assert (morrison.city, morrison.layoff_count) == ("Charlotte", 47)

    # Monthly subtotal / header lines never become notices.
    assert not any("Sum of" in r.employer or "Total" in r.employer for r in rows)


def test_nc_parse_pdf_ssrs_era():
    """~2018-2021 SSRS grid: city+zip pulled from the glued Address cell; a WARN
    number spanning multiple address lines collapses to one row (no double count)."""
    from warn_v2.scrapers.states.nc import parse_nc_pdf

    rows = parse_nc_pdf(_nc_fixture("archive_ssrs_2018.pdf"), "http://x/2018")
    assert all(r.state == "NC" for r in rows)

    aon = next(r for r in rows if r.employer == "Aon Hewitt (Aon)")
    assert aon.notice_date == date(2018, 1, 4)
    assert aon.effective_date == date(2018, 3, 9)
    assert aon.layoff_count == 76
    assert aon.city == "Charlotte"
    assert aon.zip == "28262"
    assert aon.county == "Mecklenburg County"
    assert aon.extra["warn_number"] == "20180001"

    # WARN 20180002 (Flextronics) appears on two address lines, same total (69);
    # it must collapse to a single row rather than sum to 138.
    flex = [r for r in rows if r.extra.get("warn_number") == "20180002"]
    assert len(flex) == 1
    assert flex[0].layoff_count == 69


def test_nc_ssrs_city_zip_anchors_on_state_not_first_digits():
    """ZIP + city come from the trailing 'NC <zip>', never the first 5-digit run
    (a 5-digit street number) or an out-of-state HQ ZIP glued into the cell."""
    from warn_v2.scrapers.states.nc import _ssrs_city_zip

    # 5-digit street number must NOT be taken as the ZIP.
    assert _ssrs_city_zip("10815 Quality Dr Charlotte NC 28278") == ("Charlotte", "28278")
    assert _ssrs_city_zip(
        "10101 David Taylor Drive Suite 200 Charlotte NC 28262"
    ) == ("Charlotte", "28262")
    # Out-of-state HQ ZIP glued in front of the real NC worksite ZIP.
    assert _ssrs_city_zip(
        "2701 N. Rocky Point Drive Tampa Fl 33607 Fayetteville NC 28314"
    ) == ("Fayetteville", "28314")
    # Normal 4-digit street number and a two-word city.
    assert _ssrs_city_zip("7201 Hewitt Associates Drive Charlotte NC 28262") == (
        "Charlotte",
        "28262",
    )
    assert _ssrs_city_zip("123 Main St Rocky Mount NC 27801") == ("Rocky Mount", "27801")
    # No NC anchor -> nothing.
    assert _ssrs_city_zip("somewhere with no state") == (None, None)


def test_nc_parse_pdf_current_grid_era():
    """2022+ grid shares the live HTML schema and _row_from_nc_grid."""
    from warn_v2.scrapers.states.nc import parse_nc_pdf

    rows = parse_nc_pdf(_nc_fixture("archive_grid_2025.pdf"), "http://x/2025")
    assert len(rows) >= 15

    first = rows[0]
    assert first.employer == "Resilience US, Inc."
    assert first.notice_date == date(2025, 1, 6)
    assert first.effective_date == date(2025, 12, 15)
    assert first.layoff_count == 120
    assert first.city == "Durham"
    assert first.county == "Durham County"
    assert first.closure_type == "Permanent"
    assert first.extra["warn_number"] == "202500001"
    assert first.extra["warn_notice_type"] == "Layoff"


def test_nc_parse_pdf_raises_on_bad_bytes():
    from warn_v2.scrapers.base import ParseFailed
    from warn_v2.scrapers.states.nc import parse_nc_pdf

    with pytest.raises(ParseFailed):
        parse_nc_pdf(b"not a pdf", "http://x/bad")


@respx.mock
def test_backfill_historical_nc_dispatches_per_url(db) -> None:
    """NC runs in url-list mode; each discovered PDF is parsed by parse_nc_pdf."""
    summary_url = "https://www.commerce.nc.gov/warn-report-2016-0/open"
    grid_url = "https://www.commerce.nc.gov/.../report-workforce-warn-listings-2025/open"
    respx.get(summary_url).mock(
        return_value=httpx.Response(200, content=_nc_fixture("archive_summary_2016.pdf"))
    )
    respx.get(grid_url).mock(
        return_value=httpx.Response(200, content=_nc_fixture("archive_grid_2025.pdf"))
    )

    with patch(
        "warn_v2.scripts.backfill_historical._discover_nc_pdf_urls",
        return_value=[grid_url, summary_url],
    ):
        stats = backfill_historical("NC", dry_run=True)

    assert stats["years_attempted"] == 2
    assert stats["years_ok"] == 2
    assert stats["rows_seen"] > 0
    assert db.query(Notice).count() == 0  # dry run writes nothing
