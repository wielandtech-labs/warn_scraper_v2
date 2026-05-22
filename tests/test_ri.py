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
    / "ri"
    / "sample.xlsx"
)


@pytest.fixture
def ri_sample_xlsx() -> bytes:
    return FIXTURE.read_bytes()


def test_ri_parses_live_sample(ri_sample_xlsx: bytes) -> None:
    scraper = get_scraper("RI")
    rows = scraper.parse(ri_sample_xlsx)
    # Multi-sheet workbook: 2026 + 2025 + 2024 + Previous Years.
    assert len(rows) >= 20
    assert all(r.state == "RI" for r in rows)

    first = rows[0]
    assert "Ideal" in first.employer
    assert first.notice_date == date(2026, 5, 1)
    assert first.effective_date == date(2026, 7, 1)
    assert first.layoff_count == 9891


def test_ri_closure_type_populated(ri_sample_xlsx: bytes) -> None:
    scraper = get_scraper("RI")
    rows = scraper.parse(ri_sample_xlsx)
    closures = [r for r in rows if r.closure_type == "Closure"]
    assert closures, "expected at least some rows to be classified as Closure"


def test_ri_messy_count_parsed(ri_sample_xlsx: bytes) -> None:
    """'9,891 Remote Workers (2 from RI)' -> 9891."""
    scraper = get_scraper("RI")
    rows = scraper.parse(ri_sample_xlsx)
    first = rows[0]
    assert first.layoff_count == 9891


def test_ri_validation_passes(ri_sample_xlsx: bytes) -> None:
    scraper = get_scraper("RI")
    rows = scraper.parse(ri_sample_xlsx)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ri_raises_on_bad_xlsx() -> None:
    scraper = get_scraper("RI")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not an xlsx file")
