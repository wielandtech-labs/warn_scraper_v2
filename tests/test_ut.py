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
    / "ut"
    / "sample.html"
)


@pytest.fixture
def ut_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_ut_parses_live_sample(ut_sample_html: bytes) -> None:
    scraper = get_scraper("UT")
    rows = scraper.parse(ut_sample_html)
    assert len(rows) >= 5
    assert all(r.state == "UT" for r in rows)

    first = rows[0]
    assert "Milestone" in first.employer
    assert first.notice_date == date(2026, 4, 29)
    assert first.layoff_count == 50
    assert first.city == "Eagle Mountain"


def test_ut_validation_passes(ut_sample_html: bytes) -> None:
    scraper = get_scraper("UT")
    rows = scraper.parse(ut_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ut_raises_without_table() -> None:
    scraper = get_scraper("UT")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")


ARCHIVE_FIXTURE = FIXTURE.parent / "archive_all_years.html"
# The live page trimmed to three of its 18 per-year sections (2026, 2022,
# 2010) — the older two carry the real hand-typed date typos.


def test_ut_parses_all_year_sections() -> None:
    """The page holds one table per year back to 2009; parse() must read
    every section, not just the newest."""
    scraper = get_scraper("UT")
    rows = scraper.parse(ARCHIVE_FIXTURE.read_bytes())
    assert len(rows) == 34
    years = {r.notice_date.year for r in rows}
    assert years == {2026, 2022, 2010}
    assert sum(1 for r in rows if r.notice_date.year == 2010) == 15


def test_ut_date_typo_repairs() -> None:
    from warn_v2.scrapers.states.ut import _ut_date

    assert _ut_date("08/31//2022") == date(2022, 8, 31)  # doubled slash
    assert _ut_date("03/09/2020&") == date(2020, 3, 9)  # trailing junk
    assert _ut_date("03/05/14 Updated") == date(2014, 3, 5)
    assert _ut_date("09/31/10") == date(2010, 9, 30)  # day clamped
    assert _ut_date("01/07//09") == date(2009, 1, 7)
    assert _ut_date("not a date") is None
