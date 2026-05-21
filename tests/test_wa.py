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
    / "wa"
    / "sample.html"
)


@pytest.fixture
def wa_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_wa_parses_live_sample(wa_sample_html: bytes) -> None:
    scraper = get_scraper("WA")
    rows = scraper.parse(wa_sample_html)
    assert len(rows) >= 5

    first = rows[0]
    assert first.state == "WA"
    assert first.employer == "Starbucks"
    assert first.notice_date == date(2026, 5, 15)
    assert first.effective_date == date(2026, 7, 17)
    assert first.layoff_count == 252
    assert first.city == "Seattle"
    assert first.closure_type == "Permanent"


def test_wa_validation_passes(wa_sample_html: bytes) -> None:
    scraper = get_scraper("WA")
    rows = scraper.parse(wa_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_wa_skips_pagination_rows(wa_sample_html: bytes) -> None:
    scraper = get_scraper("WA")
    rows = scraper.parse(wa_sample_html)
    # No employer should be a bare page number
    employers = [r.employer for r in rows]
    assert not any(e.strip("0123456789. ") == "" for e in employers)


def test_wa_raises_without_table() -> None:
    scraper = get_scraper("WA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table here</p></body></html>")
