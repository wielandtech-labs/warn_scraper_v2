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
    / "al"
    / "sample.html"
)


@pytest.fixture
def al_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_al_parses_live_sample(al_sample_html: bytes) -> None:
    scraper = get_scraper("AL")
    rows = scraper.parse(al_sample_html)
    # Cumulative dataset since 1998 — expect many rows.
    assert len(rows) >= 100

    first = rows[0]
    assert first.state == "AL"
    assert first.employer == "LineQuest LLC"
    assert first.notice_date == date(2026, 4, 23)
    assert first.effective_date == date(2026, 8, 1)
    assert first.layoff_count == 113
    assert first.city == "Pelham"
    assert first.closure_type == "Closure"


def test_al_validation_passes(al_sample_html: bytes) -> None:
    scraper = get_scraper("AL")
    rows = scraper.parse(al_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_al_has_historical_data(al_sample_html: bytes) -> None:
    """Dataset is cumulative from 1998; old rows should be present."""
    scraper = get_scraper("AL")
    rows = scraper.parse(al_sample_html)
    old_rows = [r for r in rows if r.notice_date and r.notice_date.year < 2010]
    assert old_rows, "expected historical rows from before 2010"


def test_al_raises_without_table() -> None:
    scraper = get_scraper("AL")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
