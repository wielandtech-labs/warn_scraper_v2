"""AZ JobLink scraper tests — also exercises the shared JobLinkScraper base."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "az"
    / "sample.html"
)


@pytest.fixture
def az_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_az_parses_all_rows(az_sample_html: bytes) -> None:
    scraper = get_scraper("AZ")
    rows = scraper.parse(az_sample_html)
    assert len(rows) == 7

    first = rows[0]
    assert first.state == "AZ"
    assert first.employer == "Block, Inc."
    assert first.city == "Oakland"
    assert first.zip == "94612"
    assert first.notice_date == date(2026, 2, 26)
    assert first.closure_type == "WARN"
    assert first.raw_notice_url == "https://www.azjobconnection.gov/search/warn_lookups/954"
    assert first.layoff_count is None  # filled in by enrichment, not the scraper
    assert first.extra["lwib_area"].startswith("7 - ARIZONA")


def test_az_fixture_passes_validation(az_sample_html: bytes) -> None:
    scraper = get_scraper("AZ")
    rows = scraper.parse(az_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_az_skips_empty_table() -> None:
    """A real 'no notices found' page has a table with only a placeholder row."""
    empty = (
        b'<html><body><table><tbody><tr><td colspan="6">No results.</td></tr>'
        b"</tbody></table></body></html>"
    )
    scraper = get_scraper("AZ")
    rows = scraper.parse(empty)
    assert rows == []


def test_az_raises_when_no_table() -> None:
    from warn_v2.scrapers.base import ParseFailed

    scraper = get_scraper("AZ")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>error</p></body></html>")
