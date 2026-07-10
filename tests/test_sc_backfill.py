"""SC historical backfill (2009-2025): era parsers, URL list, registry wiring.

Fixture provenance (trimmed from the 2026-07 sweep cache):
  * 2012_monthly_sample.pdf — pages 0-1 of the Wayback 2012 edition
    (2009-2012 "Layoff Notification Report" era: monthly sections, county +
    NAICS, wrapped county cells).
  * 2016_yearly_sample.pdf — the full 2-page Wayback 2016 edition
    (2013-2021 "WARN Notification Report {year}" era: TBD counts, "Closing"
    type, a date cell wrapped onto its own line).
  * 2020_yearly_sample.pdf — pages 0-1 of the live 2020 edition (same era
    but with the date/count/type column order shuffled).
  * sample.pdf — current era (2022+), shared with test_sc.py.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.sc import (
    _discover_sc_archive_urls,
    parse_sc_archive_pdf,
)
from warn_v2.scripts.backfill_historical import _BACKFILL

FIXTURES = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "sc"
)


@pytest.fixture(scope="module")
def monthly_pdf() -> bytes:
    return (FIXTURES / "2012_monthly_sample.pdf").read_bytes()


@pytest.fixture(scope="module")
def yearly_2016_pdf() -> bytes:
    return (FIXTURES / "2016_yearly_sample.pdf").read_bytes()


@pytest.fixture(scope="module")
def yearly_2020_pdf() -> bytes:
    return (FIXTURES / "2020_yearly_sample.pdf").read_bytes()


@pytest.fixture(scope="module")
def current_pdf() -> bytes:
    return (FIXTURES / "sample.pdf").read_bytes()


# ---------------------------------------------------------------------------
# URL discovery
# ---------------------------------------------------------------------------

def test_discover_returns_one_edition_per_year() -> None:
    urls = _discover_sc_archive_urls()
    assert len(urls) == 17  # 2009-2025; 2026 stays with the live scraper
    # No 2026 report edition (filenames start with the report year).
    assert not any(u.rsplit("/", 1)[-1].startswith("2026") for u in urls)


def test_discover_wayback_urls_use_id_replay() -> None:
    urls = _discover_sc_archive_urls()
    wayback = [u for u in urls if "web.archive.org" in u]
    assert len(wayback) == 11  # 2009-2019
    assert all("id_/https://scworks.org/" in u for u in wayback)


def test_discover_live_urls_are_dew_or_scworks() -> None:
    urls = _discover_sc_archive_urls()
    live = [u for u in urls if "web.archive.org" not in u]
    assert len(live) == 6  # 2020-2025
    assert all(
        u.startswith(("https://scworks.org/", "https://dew.sc.gov/")) for u in live
    )


# ---------------------------------------------------------------------------
# Era A: 2009-2012 monthly "Layoff Notification Report"
# ---------------------------------------------------------------------------

def test_monthly_era_parses_rows(monthly_pdf: bytes) -> None:
    rows = parse_sc_archive_pdf(monthly_pdf, "http://example/2012.pdf")
    assert len(rows) == 48  # Jan (26) + Feb (22) 2012
    assert all(r.state == "SC" for r in rows)
    assert all(r.source_url == "http://example/2012.pdf" for r in rows)


def test_monthly_era_notice_date_is_section_month(monthly_pdf: bytes) -> None:
    rows = parse_sc_archive_pdf(monthly_pdf, "u")
    months = {r.notice_date for r in rows}
    assert months == {date(2012, 1, 1), date(2012, 2, 1)}


def test_monthly_era_first_row_fields(monthly_pdf: bytes) -> None:
    first = parse_sc_archive_pdf(monthly_pdf, "u")[0]
    assert first.employer == "Sears Auto Center"
    assert first.city == "Sumter"
    assert first.county == "Sumter"
    assert first.notice_date == date(2012, 1, 1)
    assert first.effective_date == date(2012, 1, 28)
    assert first.layoff_count == 10
    assert first.closure_type == "closure"
    assert first.naics_code == "811111"


def test_monthly_era_wrapped_county_is_recovered(monthly_pdf: bytes) -> None:
    # The Inteva row's county ("Marion") wraps onto its own line.
    rows = parse_sc_archive_pdf(monthly_pdf, "u")
    inteva = next(r for r in rows if r.employer.startswith("Inteva"))
    assert inteva.county == "Marion"
    assert inteva.city == "Mullins"
    assert inteva.layoff_count == 40


def test_monthly_era_multiword_city(monthly_pdf: bytes) -> None:
    rows = parse_sc_archive_pdf(monthly_pdf, "u")
    cities = {r.city for r in rows}
    assert "Mt. Pleasant" in cities
    assert "Moncks Corner" in cities


# ---------------------------------------------------------------------------
# Era B: 2013-2021 yearly "WARN Notification Report {year}"
# ---------------------------------------------------------------------------

def test_yearly_era_parses_rows(yearly_2016_pdf: bytes) -> None:
    rows = parse_sc_archive_pdf(yearly_2016_pdf, "http://example/2016.pdf")
    assert len(rows) == 31
    assert all(r.notice_date == date(2016, 1, 1) for r in rows)
    assert all(r.source_url == "http://example/2016.pdf" for r in rows)


def test_yearly_era_wrapped_company_name(yearly_2016_pdf: bytes) -> None:
    rows = parse_sc_archive_pdf(yearly_2016_pdf, "u")
    assert rows[0].employer == "Frederick J. Hanna & Associates, PC"
    assert rows[0].city == "Greenville"
    assert rows[0].effective_date == date(2016, 2, 10)
    assert rows[0].layoff_count is None  # "TBD" in the source
    assert rows[0].naics_code == "332991"


def test_yearly_era_wrapped_date_cell(yearly_2016_pdf: bytes) -> None:
    # Amazon's date ("02/15/2017") renders on its own text line; the table
    # extractor reunites it with the row.
    rows = parse_sc_archive_pdf(yearly_2016_pdf, "u")
    amazon = next(r for r in rows if r.employer == "Amazon")
    assert amazon.effective_date == date(2017, 2, 15)
    assert amazon.layoff_count == 149


def test_yearly_era_closing_type(yearly_2016_pdf: bytes) -> None:
    rows = parse_sc_archive_pdf(yearly_2016_pdf, "u")
    hubbell = next(r for r in rows if r.employer == "Hubbell")
    assert hubbell.closure_type == "Closing"


def test_yearly_era_2020_column_order(yearly_2020_pdf: bytes) -> None:
    # 2020 swaps the date/count/type column order; cells are classified by
    # content, not position.
    rows = parse_sc_archive_pdf(yearly_2020_pdf, "u")
    assert len(rows) == 37
    gnc = rows[0]
    assert gnc.employer == "GNC"
    assert gnc.city == "Anderson"
    assert gnc.notice_date == date(2020, 1, 1)
    assert gnc.effective_date == date(2020, 3, 1)
    assert gnc.layoff_count == 65
    assert gnc.closure_type == "Closure"
    assert gnc.naics_code == "446191"


def test_yearly_era_missing_count(yearly_2020_pdf: bytes) -> None:
    rows = parse_sc_archive_pdf(yearly_2020_pdf, "u")
    auction = next(r for r in rows if "Auto Auction" in r.employer)
    assert auction.layoff_count is None
    assert auction.effective_date == date(2020, 3, 17)


# ---------------------------------------------------------------------------
# Era C: 2022+ current layout routes through parse_sc_pdf
# ---------------------------------------------------------------------------

def test_current_era_dispatch_overrides_source_url(current_pdf: bytes) -> None:
    url = "https://dew.sc.gov/sites/dew/files/Documents/2023.pdf"
    rows = parse_sc_archive_pdf(current_pdf, url)
    assert len(rows) >= 5
    assert all(r.source_url == url for r in rows)
    assert all(r.notice_date is not None for r in rows)


def test_archive_parse_raises_on_garbage() -> None:
    with pytest.raises(ParseFailed):
        parse_sc_archive_pdf(b"not a pdf", "u")


# ---------------------------------------------------------------------------
# Backfill registry wiring
# ---------------------------------------------------------------------------

def test_sc_backfill_spec_registered() -> None:
    spec = _BACKFILL["SC"]
    assert spec.discover_urls is not None
    assert spec.parse_for_url is not None
    urls = spec.discover_urls()
    assert len(urls) == 17


def test_sc_backfill_parse_for_url_binds_url(current_pdf: bytes) -> None:
    spec = _BACKFILL["SC"]
    url = "https://scworks.org/sites/scworks/files/x.pdf"
    parse_fn = spec.parse_for_url(url)
    rows = parse_fn(current_pdf)
    assert rows
    assert all(r.source_url == url for r in rows)
