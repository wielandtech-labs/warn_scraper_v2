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
    / "sample.csv"
)


@pytest.fixture
def oh_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_oh_parses_fixture(oh_sample: bytes) -> None:
    scraper = get_scraper("OH")
    rows = scraper.parse(oh_sample)
    assert len(rows) >= 5
    assert all(r.state == "OH" for r in rows)

    # Assert on a known notice (the fixture is a frozen snapshot); the CSV is
    # newest-first, so don't rely on positional order.
    ash = next(r for r in rows if r.employer == "Advanced Specialty Hospitals of Toledo")
    assert ash.notice_date == date(2026, 4, 9)
    assert ash.layoff_count == 116
    assert ash.city == "Toledo"
    assert ash.county == "Lucas"
    assert ash.closure_type == "Closure"
    assert ash.raw_notice_url is not None and ash.raw_notice_url.endswith(".pdf")


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


def test_oh_raises_without_header() -> None:
    scraper = get_scraper("OH")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table here</p></body></html>")
