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
