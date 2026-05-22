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
    / "ky"
    / "sample.csv"
)


@pytest.fixture
def ky_sample_csv() -> bytes:
    return FIXTURE.read_bytes()


def test_ky_parses_live_sample(ky_sample_csv: bytes) -> None:
    scraper = get_scraper("KY")
    rows = scraper.parse(ky_sample_csv)
    assert len(rows) >= 5
    assert all(r.state == "KY" for r in rows)


def test_ky_first_row(ky_sample_csv: bytes) -> None:
    scraper = get_scraper("KY")
    rows = scraper.parse(ky_sample_csv)
    first = rows[0]
    assert "Battelle" in first.employer
    assert first.notice_date == date(2026, 5, 7)
    assert first.layoff_count == 3
    assert first.county == "Madison"
    assert first.closure_type == "Closure"


def test_ky_extra_fields(ky_sample_csv: bytes) -> None:
    scraper = get_scraper("KY")
    rows = scraper.parse(ky_sample_csv)
    first = rows[0]
    assert first.extra.get("wda") == "Bluegrass"
    assert first.extra.get("notice_number") == "Notice 2804"


def test_ky_notice_url(ky_sample_csv: bytes) -> None:
    """Salesforce-hosted notice URLs are captured in raw_notice_url."""
    scraper = get_scraper("KY")
    rows = scraper.parse(ky_sample_csv)
    with_url = [r for r in rows if r.raw_notice_url]
    assert with_url, "expected at least one row to have a notice URL"
    assert "salesforce.com" in with_url[0].raw_notice_url


def test_ky_large_layoff(ky_sample_csv: bytes) -> None:
    """Blue Oval SK Group notice has 1 514 employees affected."""
    scraper = get_scraper("KY")
    rows = scraper.parse(ky_sample_csv)
    blue_oval = next((r for r in rows if "Blue Oval" in (r.employer or "")), None)
    assert blue_oval is not None, "expected Blue Oval SK Group entry"
    assert blue_oval.layoff_count == 1514


def test_ky_validation_passes(ky_sample_csv: bytes) -> None:
    scraper = get_scraper("KY")
    rows = scraper.parse(ky_sample_csv)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ky_raises_on_bad_csv() -> None:
    scraper = get_scraper("KY")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not csv data \x00\x01\x02")


def test_ky_raises_on_empty_csv() -> None:
    """A CSV with only a header row and no data rows raises ParseFailed."""
    scraper = get_scraper("KY")
    header = (
        b'"Company: Company Name","Notice Type","Notice: Notice Number",'
        b'"Closure or Layoff?","County","Date Received","NAICS","Notice URL",'
        b'"Number of Employees Affected","Projected Date","Trade",'
        b'"Type of Employees Affected","Workforce Board"\n'
    )
    with pytest.raises(ParseFailed):
        scraper.parse(header)
