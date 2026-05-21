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
    / "mt"
    / "sample.xlsx"
)


@pytest.fixture
def mt_sample_xlsx() -> bytes:
    return FIXTURE.read_bytes()


def test_mt_parses_live_sample(mt_sample_xlsx: bytes) -> None:
    scraper = get_scraper("MT")
    rows = scraper.parse(mt_sample_xlsx)
    assert len(rows) >= 10
    assert all(r.state == "MT" for r in rows)

    first = rows[0]
    assert "Wells Fargo" in first.employer
    assert first.notice_date == date(2026, 3, 30)
    assert first.effective_date == date(2026, 5, 30)
    assert first.layoff_count == 77
    assert first.county == "Yellowstone"
    assert first.extra.get("industry") == "Banking"


def test_mt_county_populated(mt_sample_xlsx: bytes) -> None:
    scraper = get_scraper("MT")
    rows = scraper.parse(mt_sample_xlsx)
    with_county = [r for r in rows if r.county]
    assert with_county, "expected at least some rows to have county"


def test_mt_industry_in_extra(mt_sample_xlsx: bytes) -> None:
    scraper = get_scraper("MT")
    rows = scraper.parse(mt_sample_xlsx)
    with_industry = [r for r in rows if r.extra.get("industry")]
    assert with_industry, "expected at least some rows to have industry in extra"


def test_mt_validation_passes(mt_sample_xlsx: bytes) -> None:
    scraper = get_scraper("MT")
    rows = scraper.parse(mt_sample_xlsx)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_mt_raises_on_bad_xlsx() -> None:
    scraper = get_scraper("MT")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not an xlsx file")
