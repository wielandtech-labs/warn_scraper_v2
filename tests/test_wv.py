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
    / "wv"
    / "sample.html"
)


@pytest.fixture
def wv_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_wv_parses_fixture(wv_sample_html: bytes) -> None:
    scraper = get_scraper("WV")
    rows = scraper.parse(wv_sample_html)
    assert len(rows) >= 5
    assert all(r.state == "WV" for r in rows)

    first = rows[0]
    assert first.employer
    assert first.notice_date is not None
    # First entry on the captured fixture: Mettiki (2026 notice)
    assert "Mettiki" in first.employer
    assert first.notice_date.year == 2026
    assert first.raw_notice_url is not None
    assert first.raw_notice_url.endswith(".pdf")


def test_wv_employers_and_dates(wv_sample_html: bytes) -> None:
    scraper = get_scraper("WV")
    rows = scraper.parse(wv_sample_html)
    # All rows must have non-empty employer and a notice date
    assert all(r.employer for r in rows)
    assert all(r.notice_date is not None for r in rows)
    # Should span multiple years (fixture has 2021-2026)
    years = {r.notice_date.year for r in rows}
    assert len(years) >= 3


def test_wv_validation_passes(wv_sample_html: bytes) -> None:
    scraper = get_scraper("WV")
    rows = scraper.parse(wv_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_wv_raises_on_no_pdf_links() -> None:
    scraper = get_scraper("WV")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no links here</p></body></html>")
