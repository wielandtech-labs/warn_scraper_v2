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
    / "mo"
    / "sample.json"
)


@pytest.fixture
def mo_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_mo_parses_fixture(mo_sample: bytes) -> None:
    scraper = get_scraper("MO")
    rows = scraper.parse(mo_sample)
    assert len(rows) >= 5
    assert all(r.state == "MO" for r in rows)

    first = rows[0]
    assert "TimKen" in first.employer
    assert first.notice_date == date(2025, 1, 7)
    assert first.layoff_count == 97


def test_mo_layoff_counts_present(mo_sample: bytes) -> None:
    scraper = get_scraper("MO")
    rows = scraper.parse(mo_sample)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5


def test_mo_validation_passes(mo_sample: bytes) -> None:
    scraper = get_scraper("MO")
    rows = scraper.parse(mo_sample)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_mo_raises_on_bad_input() -> None:
    scraper = get_scraper("MO")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not valid json at all")
