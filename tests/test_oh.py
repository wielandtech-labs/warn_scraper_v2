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
    / "oh"
    / "sample.html"
)


@pytest.fixture
def oh_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_oh_parses_fixture(oh_sample: bytes) -> None:
    scraper = get_scraper("OH")
    rows = scraper.parse(oh_sample)
    assert len(rows) >= 5
    assert all(r.state == "OH" for r in rows)

    first = rows[0]
    assert "Toledo" in first.employer or first.employer
    assert first.notice_date == date(2026, 4, 9)
    assert first.layoff_count == 116
    assert first.city == "Toledo"
    assert first.county == "Lucas"


def test_oh_layoff_counts_present(oh_sample: bytes) -> None:
    scraper = get_scraper("OH")
    rows = scraper.parse(oh_sample)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5


def test_oh_validation_passes(oh_sample: bytes) -> None:
    scraper = get_scraper("OH")
    rows = scraper.parse(oh_sample)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_oh_raises_without_table() -> None:
    scraper = get_scraper("OH")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table here</p></body></html>")
