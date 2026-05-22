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
    / "pa"
    / "sample.html"
)


@pytest.fixture
def pa_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_pa_parses_live_sample(pa_sample_html: bytes) -> None:
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    assert len(rows) >= 100
    assert all(r.state == "PA" for r in rows)


def test_pa_first_row(pa_sample_html: bytes) -> None:
    """Calfrac Well Services Corp. is the first entry in the fixture."""
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    first = rows[0]
    assert "Calfrac" in first.employer
    assert first.notice_date == date(2026, 5, 21)
    assert first.county == "Fayette"
    assert first.layoff_count == 75
    assert first.city == "Smithfield"


def test_pa_effective_date_plain(pa_sample_html: bytes) -> None:
    """EFFECTIVE DATE field is parsed as effective_date."""
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    first = rows[0]
    # Calfrac: "beginning 7/20/2026; ending 9/30/2027" -> start date
    assert first.effective_date == date(2026, 7, 20)


def test_pa_effective_date_range(pa_sample_html: bytes) -> None:
    """'beginning M/D/YYYY; ending M/D/YYYY' uses the start date."""
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    ranges = [r for r in rows if r.effective_date and r.effective_date.year >= 2026]
    assert ranges, "expected rows with 2026+ effective dates"


def test_pa_two_digit_year(pa_sample_html: bytes) -> None:
    """Effective dates like '7/6/26' are parsed as 2026, not 1926."""
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    assert not any(r.effective_date and r.effective_date.year < 2000 for r in rows)


def test_pa_multi_location(pa_sample_html: bytes) -> None:
    """The GIANT Company files cover multiple PA locations -- each gets its own row."""
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    giant_rows = [r for r in rows if "GIANT" in (r.employer or "")]
    assert len(giant_rows) >= 2, "expected multiple rows for The GIANT Company"
    counties = {r.county for r in giant_rows if r.county}
    assert len(counties) >= 2, "expected rows spanning multiple counties"


def test_pa_closure_type(pa_sample_html: bytes) -> None:
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    with_type = [r for r in rows if r.closure_type]
    assert with_type
    types = {r.closure_type for r in with_type}
    assert any(t in types for t in ("Closure", "Closing", "Layoff", "Layoffs"))


def test_pa_city_extracted(pa_sample_html: bytes) -> None:
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    with_city = [r for r in rows if r.city]
    assert len(with_city) > len(rows) // 2, "expected most rows to have a city"


def test_pa_validation_passes(pa_sample_html: bytes) -> None:
    scraper = get_scraper("PA")
    rows = scraper.parse(pa_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_pa_raises_on_bad_html() -> None:
    scraper = get_scraper("PA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body>no accordion here</body></html>")
