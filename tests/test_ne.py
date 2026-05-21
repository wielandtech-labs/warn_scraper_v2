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
    / "ne"
    / "sample.html"
)


@pytest.fixture
def ne_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_ne_parses_live_sample(ne_sample_html: bytes) -> None:
    scraper = get_scraper("NE")
    rows = scraper.parse(ne_sample_html)
    assert len(rows) >= 10
    assert all(r.state == "NE" for r in rows)

    first = rows[0]
    assert "Tyson" in first.employer
    assert first.notice_date == date(2026, 1, 21)
    assert first.layoff_count == 294
    assert first.city == "Lexington"
    assert first.raw_notice_url is not None


def test_ne_notice_url_populated(ne_sample_html: bytes) -> None:
    scraper = get_scraper("NE")
    rows = scraper.parse(ne_sample_html)
    rows_with_url = [r for r in rows if r.raw_notice_url]
    assert rows_with_url, "expected at least some rows to have notice URLs"


def test_ne_comma_counts_parsed(ne_sample_html: bytes) -> None:
    """Jobs affected values like '3,212' should parse as integers."""
    scraper = get_scraper("NE")
    rows = scraper.parse(ne_sample_html)
    counts = [r.layoff_count for r in rows if r.layoff_count is not None]
    assert any(c >= 1000 for c in counts), "expected at least one 4-digit layoff count"


def test_ne_validation_passes(ne_sample_html: bytes) -> None:
    scraper = get_scraper("NE")
    rows = scraper.parse(ne_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ne_raises_without_table() -> None:
    scraper = get_scraper("NE")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
