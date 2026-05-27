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
    / "mn"
    / "sample.json"
)


@pytest.fixture
def mn_sample() -> bytes:
    return FIXTURE.read_bytes()


def test_mn_parses_fixture(mn_sample: bytes) -> None:
    scraper = get_scraper("MN")
    rows = scraper.parse(mn_sample)
    # May 2025 PDF has 3 WARN Act=YES rows
    assert len(rows) >= 1
    assert all(r.state == "MN" for r in rows)
    first = rows[0]
    assert first.employer
    assert first.notice_date is not None


def test_mn_layoff_counts_present(mn_sample: bytes) -> None:
    scraper = get_scraper("MN")
    rows = scraper.parse(mn_sample)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 1


def test_mn_validation_passes(mn_sample: bytes) -> None:
    scraper = get_scraper("MN")
    rows = scraper.parse(mn_sample)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_mn_raises_on_bad_input() -> None:
    scraper = get_scraper("MN")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not valid json at all")
