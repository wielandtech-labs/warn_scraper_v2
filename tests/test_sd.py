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
    / "sd"
    / "sample.html"
)


@pytest.fixture
def sd_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_sd_parses_live_sample(sd_sample_html: bytes) -> None:
    scraper = get_scraper("SD")
    rows = scraper.parse(sd_sample_html)
    assert len(rows) >= 10
    assert all(r.state == "SD" for r in rows)

    first = rows[0]
    assert "Republic National" in first.employer
    assert first.notice_date == date(2026, 5, 19)
    assert first.layoff_count == 53
    assert first.city == "Rapid City"
    assert first.raw_notice_url is not None


def test_sd_notice_url_is_pdf(sd_sample_html: bytes) -> None:
    scraper = get_scraper("SD")
    rows = scraper.parse(sd_sample_html)
    pdf_rows = [r for r in rows if r.raw_notice_url and ".pdf" in r.raw_notice_url]
    assert pdf_rows, "expected at least some rows to link to PDFs"


def test_sd_multi_city_location_uses_first(sd_sample_html: bytes) -> None:
    """'Rapid City, Sioux Falls' → city should be 'Rapid City'."""
    scraper = get_scraper("SD")
    rows = scraper.parse(sd_sample_html)
    first = rows[0]
    assert first.city == "Rapid City"


def test_sd_non_numeric_count_stripped(sd_sample_html: bytes) -> None:
    """'173 (nationwide)' → layoff_count 173."""
    scraper = get_scraper("SD")
    rows = scraper.parse(sd_sample_html)
    # JeniusBank row has "(nationwide)" suffix
    jb = next((r for r in rows if "Jenius" in r.employer), None)
    if jb:
        assert jb.layoff_count == 173


def test_sd_validation_passes(sd_sample_html: bytes) -> None:
    scraper = get_scraper("SD")
    rows = scraper.parse(sd_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_sd_raises_without_table() -> None:
    scraper = get_scraper("SD")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
