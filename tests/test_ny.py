"""NY scraper tests against a fixture HTML page."""
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
    / "ny"
    / "sample.html"
)


@pytest.fixture
def ny_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_ny_parses_all_rows(ny_sample_html: bytes) -> None:
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_html)
    assert len(rows) == 11

    first = rows[0]
    assert first.state == "NY"
    assert first.employer == "Empire Foods Inc."
    assert first.notice_date == date(2026, 5, 15)  # Date Posted preferred when both present
    assert first.raw_notice_url == (
        "https://dol.ny.gov/system/files/documents/2026/05/empire-foods-warn.pdf"
    )
    assert first.layoff_count is None  # filled by enrichment (Phase 4)


def test_ny_passes_validation(ny_sample_html: bytes) -> None:
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ny_absolute_url_passthrough(ny_sample_html: bytes) -> None:
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_html)
    queens = next(r for r in rows if r.employer == "Queens Retail Partners")
    assert queens.raw_notice_url == (
        "https://dol.ny.gov/system/files/documents/2026/03/queens-retail.pdf"
    )


def test_ny_raises_without_table() -> None:
    scraper = get_scraper("NY")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>error</p></body></html>")
