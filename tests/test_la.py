from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "la"
    / "sample.pdf"
)


@pytest.fixture
def la_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_la_parses_pdf(la_sample_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_sample_pdf)
    assert len(rows) >= 1
    assert all(r.state == "LA" for r in rows)
    assert all(r.employer for r in rows)
    assert all(r.notice_date is not None for r in rows)


def test_la_first_row(la_sample_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_sample_pdf)
    first = rows[0]
    assert "McGlinchey" in first.employer
    assert first.notice_date == date(2026, 1, 13)
    assert first.layoff_count == 101
    assert first.city == "New Orleans"
    assert first.zip == "70130"
    assert first.extra.get("industry") == "Legal Services"


def test_la_city_zip_extraction(la_sample_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_sample_pdf)
    # All rows should have city and zip extracted from address.
    rows_with_city = [r for r in rows if r.city]
    assert rows_with_city, "expected at least one row with city"
    rows_with_zip = [r for r in rows if r.zip]
    assert rows_with_zip, "expected at least one row with zip"


def test_la_validation_passes(la_sample_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_la_raises_on_bad_pdf() -> None:
    scraper = get_scraper("LA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not a pdf")


# ---------------------------------------------------------------------------
# 2025 layout era — no banner row, no Address column, header repeated per
# page, employer + address merged in the Company Name cell.
# ---------------------------------------------------------------------------

FIXTURE_2025 = FIXTURE.parent / "sample_2025.pdf"


@pytest.fixture
def la_2025_pdf() -> bytes:
    return FIXTURE_2025.read_bytes()


def test_la_2025_layout_parses_all_rows(la_2025_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_2025_pdf)
    # 24 dated data rows across 2 pages; one has notice date "Not specified"
    # and is skipped, as is a rescission footnote with empty date cells.
    assert len(rows) == 23
    assert all(r.notice_date is not None for r in rows)
    months = {r.notice_date.month for r in rows}
    assert min(months) == 1 and max(months) == 12


def test_la_2025_employer_address_split(la_2025_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_2025_pdf)
    boeing = next(r for r in rows if "Boeing" in r.employer)
    assert boeing.employer == "Boeing Company"
    assert boeing.city == "New Orleans"
    # ZIP must be the trailing ZIP, not the 5-digit street number 13800.
    assert boeing.zip == "70129"
    assert boeing.layoff_count == 89


def test_la_2025_layoff_date_range_uses_start(la_2025_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_2025_pdf)
    cornerstone = next(r for r in rows if "Cornerstone" in r.employer)
    # Layoff Date cell reads "7/31/25 to 12/31/25".
    assert cornerstone.effective_date == date(2025, 7, 31)


def test_la_2025_validation_passes(la_2025_pdf: bytes) -> None:
    scraper = get_scraper("LA")
    rows = scraper.parse(la_2025_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason
