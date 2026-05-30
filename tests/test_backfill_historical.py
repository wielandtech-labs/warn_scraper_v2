"""Tests for backfill_historical — per-state fetch helpers and ingest loop."""
from __future__ import annotations

import io
import json
from datetime import date
from unittest.mock import MagicMock, patch

import httpx
import openpyxl
import pytest
import respx

from warn_v2.db.models import Notice, ScraperRun
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
    from warn_v2.scrapers.states.ca import _discover_archive_urls, _ARCHIVE_PAGE

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
    from warn_v2.scrapers.states.ca import _discover_archive_urls, _ARCHIVE_PAGE

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
    respx.get(search_url).mock(return_value=httpx.Response(200, content=b"<html><table></table></html>"))

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
