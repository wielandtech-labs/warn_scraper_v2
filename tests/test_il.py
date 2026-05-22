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
    / "il"
    / "sample.xlsx"
)


@pytest.fixture
def il_sample_xlsx() -> bytes:
    return FIXTURE.read_bytes()


def test_il_parses_live_sample(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    assert len(rows) >= 1
    assert all(r.state == "IL" for r in rows)


def test_il_first_row(il_sample_xlsx: bytes) -> None:
    """Aramark Campus LLC (April 2026) is the first notice in the fixture."""
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    first = rows[0]
    assert "Aramark" in first.employer
    assert first.notice_date == date(2026, 4, 7)
    assert first.layoff_count == 170
    assert first.city == "Plainfield"
    assert first.county == "Will"


def test_il_effective_date(il_sample_xlsx: bytes) -> None:
    """First Layoff Date (effective date) is parsed from Excel datetime cells."""
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    first = rows[0]
    assert first.effective_date == date(2026, 5, 22)


def test_il_closure_type(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    # Type of Event: 'Closing', 'Layoff', etc.
    with_type = [r for r in rows if r.closure_type]
    assert with_type


def test_il_extra_fields(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    first = rows[0]
    assert first.extra.get("layoff_type") == "Permanent"
    assert first.extra.get("event_causes") == "Lost Contract"
    assert first.extra.get("naics") == "722310"


def test_il_city_parsed(il_sample_xlsx: bytes) -> None:
    """City is extracted from 'City, IL ZIP' formatted column."""
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    assert all(r.city is not None for r in rows if r.city)
    # No city should contain a comma or state abbreviation
    for r in rows:
        if r.city:
            assert "," not in r.city, f"comma in city: {r.city!r}"


def test_il_validation_passes(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_il_raises_on_bad_xlsx() -> None:
    scraper = get_scraper("IL")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not an excel file at all")
