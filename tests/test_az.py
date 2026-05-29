"""AZ JobLink scraper tests — also exercises the shared JobLinkScraper base."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.registry import get_scraper

_FIXTURE_DIR = (
    Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "az"
)

FIXTURE_HTML = _FIXTURE_DIR / "sample.html"
FIXTURE_BUNDLE = _FIXTURE_DIR / "sample_bundle.json"


@pytest.fixture
def az_sample_html() -> bytes:
    return FIXTURE_HTML.read_bytes()


@pytest.fixture
def az_sample_bundle() -> bytes:
    return FIXTURE_BUNDLE.read_bytes()


# ---------------------------------------------------------------------------
# Raw HTML path (backward compat — old snapshots have no detail data)
# ---------------------------------------------------------------------------

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
    # Raw HTML path has no detail data
    assert first.layoff_count is None
    assert first.address is None
    assert first.extra["lwib_area"].startswith("7 - ARIZONA")


def test_az_fixture_passes_validation(az_sample_html: bytes) -> None:
    scraper = get_scraper("AZ")
    rows = scraper.parse(az_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


# ---------------------------------------------------------------------------
# Bundle path (fetch() output — includes detail page data)
# ---------------------------------------------------------------------------

def test_az_bundle_populates_count_and_address(az_sample_bundle: bytes) -> None:
    scraper = get_scraper("AZ")
    rows = scraper.parse(az_sample_bundle)
    assert len(rows) == 7

    first = rows[0]
    assert first.employer == "Block, Inc."
    assert first.notice_date == date(2026, 2, 26)
    # Detail data from sample_bundle.json (real values from live page)
    assert first.layoff_count == 83
    assert first.address == "1955 Broadway, Suite 600 Oakland, California 94612"

    # Spot-check second and third row
    assert rows[1].layoff_count == 1
    assert rows[2].layoff_count == 89
    assert rows[2].address == "10111 Richmond Ave, Suite 130 Houston, Texas 77042"


def test_az_bundle_passes_validation(az_sample_bundle: bytes) -> None:
    scraper = get_scraper("AZ")
    rows = scraper.parse(az_sample_bundle)
    result = validate(scraper, rows)
    assert result.ok, result.reason


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

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


def test_az_bundle_missing_detail_leaves_none() -> None:
    """If a detail page is absent from the bundle, count and address stay None."""
    import json

    bundle = json.dumps({
        "search_html": FIXTURE_HTML.read_text(),
        "details": {},  # no detail pages
    }).encode()
    scraper = get_scraper("AZ")
    rows = scraper.parse(bundle)
    assert len(rows) == 7
    assert all(r.layoff_count is None for r in rows)
    assert all(r.address is None for r in rows)
