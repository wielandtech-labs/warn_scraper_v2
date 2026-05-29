from __future__ import annotations

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
    / "mi"
    / "sample.json"
)


@pytest.fixture
def mi_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_mi_parses_fixture(mi_sample: bytes) -> None:
    scraper = get_scraper("MI")
    rows = scraper.parse(mi_sample)
    # Fixture has 101 API results; 10 are Sitecore UI wrapper divs → 91 real records
    assert len(rows) >= 5
    assert all(r.state == "MI" for r in rows)
    first = rows[0]
    assert first.employer
    assert first.notice_date is not None
    # Spot-check first record from fixture (Our Next Energy, Novi, 2026-01-06)
    assert "Our Next Energy" in first.employer
    assert first.city == "Novi"
    assert first.county == "Oakland"
    # MI API only publishes the layoff date; both fields should be set to it.
    assert first.effective_date is not None
    assert first.effective_date == first.notice_date


def test_mi_layoff_counts_present(mi_sample: bytes) -> None:
    scraper = get_scraper("MI")
    rows = scraper.parse(mi_sample)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5


def test_mi_validation_passes(mi_sample: bytes) -> None:
    scraper = get_scraper("MI")
    rows = scraper.parse(mi_sample)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_mi_raises_on_bad_input() -> None:
    scraper = get_scraper("MI")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not valid json at all")
