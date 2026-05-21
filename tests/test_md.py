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
    / "md"
    / "sample.html"
)


@pytest.fixture
def md_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_md_parses_live_sample(md_sample_html: bytes) -> None:
    scraper = get_scraper("MD")
    rows = scraper.parse(md_sample_html)
    # MD lists 60+ notices on a single page.
    assert len(rows) >= 30

    first = rows[0]
    assert first.state == "MD"
    assert first.employer == "U.S. Bank"
    assert first.notice_date == date(2026, 5, 20)
    assert first.effective_date == date(2026, 7, 24)
    assert first.layoff_count == 36
    assert first.city == "Frederick"
    assert first.zip == "21704"
    assert first.county == "Frederick"
    assert first.closure_type == "Mass Layoff"
    assert first.extra["naics"] == "522110"


def test_md_validation_passes(md_sample_html: bytes) -> None:
    scraper = get_scraper("MD")
    rows = scraper.parse(md_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_md_handles_plant_closure_row(md_sample_html: bytes) -> None:
    """A second row has 'Plant Closure' as the Type; make sure we surface it."""
    scraper = get_scraper("MD")
    rows = scraper.parse(md_sample_html)
    closures = [r for r in rows if r.closure_type == "Plant Closure"]
    assert closures, "expected at least one Plant Closure row"


def test_md_raises_without_table() -> None:
    scraper = get_scraper("MD")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
