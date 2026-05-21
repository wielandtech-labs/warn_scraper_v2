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
    / "ut"
    / "sample.html"
)


@pytest.fixture
def ut_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_ut_parses_live_sample(ut_sample_html: bytes) -> None:
    scraper = get_scraper("UT")
    rows = scraper.parse(ut_sample_html)
    assert len(rows) >= 5
    assert all(r.state == "UT" for r in rows)

    first = rows[0]
    assert "Milestone" in first.employer
    assert first.notice_date == date(2026, 4, 29)
    assert first.layoff_count == 50
    assert first.city == "Eagle Mountain"


def test_ut_validation_passes(ut_sample_html: bytes) -> None:
    scraper = get_scraper("UT")
    rows = scraper.parse(ut_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ut_raises_without_table() -> None:
    scraper = get_scraper("UT")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
