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
    / "va"
    / "sample.html"
)


@pytest.fixture
def va_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_va_parses_live_sample(va_sample_html: bytes) -> None:
    scraper = get_scraper("VA")
    rows = scraper.parse(va_sample_html)
    # Cumulative table — 1000+ rows expected.
    assert len(rows) >= 100
    assert all(r.state == "VA" for r in rows)

    first = rows[0]
    assert "Parkhurst" in first.employer
    assert first.notice_date == date(2026, 5, 18)
    assert first.effective_date == date(2026, 7, 21)
    assert first.layoff_count == 65
    assert first.city == "Bridgewater"
    assert first.closure_type == "Closure"
    assert first.raw_notice_url is not None


def test_va_notice_url_populated(va_sample_html: bytes) -> None:
    scraper = get_scraper("VA")
    rows = scraper.parse(va_sample_html)
    rows_with_url = [r for r in rows if r.raw_notice_url]
    assert rows_with_url, "expected at least some rows to have notice PDFs"


def test_va_validation_passes(va_sample_html: bytes) -> None:
    scraper = get_scraper("VA")
    rows = scraper.parse(va_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_va_raises_without_table() -> None:
    scraper = get_scraper("VA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
