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
    / "dc"
    / "sample.html"
)


@pytest.fixture
def dc_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_dc_parses_live_sample(dc_sample_html: bytes) -> None:
    scraper = get_scraper("DC")
    rows = scraper.parse(dc_sample_html)
    assert len(rows) >= 1
    assert all(r.state == "DC" for r in rows)

    first = rows[0]
    assert first.employer == "Elior North America"
    assert first.notice_date == date(2026, 2, 2)
    assert first.layoff_count == 76
    assert first.closure_type == "Layoff"


def test_dc_code_type_2_is_permanent_closures(dc_sample_html: bytes) -> None:
    scraper = get_scraper("DC")
    rows = scraper.parse(dc_sample_html)
    perm = [r for r in rows if r.closure_type == "Permanent Closures"]
    assert perm, "expected at least one Permanent Closures row (Code Type 2)"


def test_dc_validation_passes(dc_sample_html: bytes) -> None:
    scraper = get_scraper("DC")
    rows = scraper.parse(dc_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_dc_raises_without_table() -> None:
    scraper = get_scraper("DC")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
