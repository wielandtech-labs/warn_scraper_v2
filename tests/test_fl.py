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
    / "fl"
    / "sample.html"
)


@pytest.fixture
def fl_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_fl_parses_live_sample(fl_sample_html: bytes) -> None:
    scraper = get_scraper("FL")
    rows = scraper.parse(fl_sample_html)
    # 100 results per page in the live source.
    assert 50 <= len(rows) <= 100

    first = rows[0]
    assert first.state == "FL"
    assert first.employer == "ACL Roofing"
    assert first.city == "Englewood"
    assert first.zip == "34223"
    assert first.notice_date == date(2026, 5, 16)
    assert first.effective_date == date(2026, 7, 14)
    assert first.layoff_count == 65
    assert first.extra["industry"] == "Construction"
    assert first.raw_notice_url == (
        "https://reactwarn.floridajobs.org/WarnList/DownloadAzureFile?file=ACL+Roofing.pdf"
    )


def test_fl_pdf_url_format(fl_sample_html: bytes) -> None:
    scraper = get_scraper("FL")
    rows = scraper.parse(fl_sample_html)
    pdf_urls = [r.raw_notice_url for r in rows if r.raw_notice_url]
    # Almost every row should have a PDF link.
    assert len(pdf_urls) >= len(rows) * 0.9
    for url in pdf_urls:
        assert url.startswith(
            "https://reactwarn.floridajobs.org/WarnList/DownloadAzureFile?file="
        )


def test_fl_validation_passes(fl_sample_html: bytes) -> None:
    scraper = get_scraper("FL")
    rows = scraper.parse(fl_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_fl_raises_without_table() -> None:
    scraper = get_scraper("FL")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>error</p></body></html>")
