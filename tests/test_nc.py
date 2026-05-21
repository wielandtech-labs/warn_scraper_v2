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
    / "nc"
    / "sample.html"
)


@pytest.fixture
def nc_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_nc_parses_live_sample(nc_sample_html: bytes) -> None:
    scraper = get_scraper("NC")
    rows = scraper.parse(nc_sample_html)
    assert len(rows) >= 5

    first = rows[0]
    assert first.state == "NC"
    assert first.employer == "Avelo Airlines, Inc."
    assert first.notice_date == date(2026, 1, 7)
    assert first.effective_date == date(2026, 3, 6)
    assert first.layoff_count == 82
    assert first.city == "Wilmington"
    assert first.county == "New Hanover County"
    assert first.closure_type == "Permanent"
    assert first.extra.get("warn_number") == "202600001"


def test_nc_validation_passes(nc_sample_html: bytes) -> None:
    scraper = get_scraper("NC")
    rows = scraper.parse(nc_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_nc_has_closure_type(nc_sample_html: bytes) -> None:
    scraper = get_scraper("NC")
    rows = scraper.parse(nc_sample_html)
    assert all(r.closure_type for r in rows), "all rows should have a closure type"


def test_nc_raises_without_table() -> None:
    scraper = get_scraper("NC")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
