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
    / "ma"
    / "sample.json"
)


@pytest.fixture
def ma_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_ma_parses_fixture(ma_sample: bytes) -> None:
    scraper = get_scraper("MA")
    rows = scraper.parse(ma_sample)
    assert len(rows) >= 5
    assert all(r.state == "MA" for r in rows)

    first = rows[0]
    assert first.employer
    assert first.notice_date is not None
    assert first.city is not None


def test_ma_layoff_counts_present(ma_sample: bytes) -> None:
    scraper = get_scraper("MA")
    rows = scraper.parse(ma_sample)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5


def test_ma_validation_passes(ma_sample: bytes) -> None:
    scraper = get_scraper("MA")
    rows = scraper.parse(ma_sample)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ma_raises_on_bad_input() -> None:
    scraper = get_scraper("MA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not valid json")
