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
    / "tn"
    / "sample.html"
)


@pytest.fixture
def tn_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_tn_parses_live_sample(tn_sample_html: bytes) -> None:
    scraper = get_scraper("TN")
    rows = scraper.parse(tn_sample_html)
    # Two tables (current year + archive) combined.
    assert len(rows) >= 20
    assert all(r.state == "TN" for r in rows)

    first = rows[0]
    assert "Tsubaki" in first.employer
    assert first.notice_date == date(2026, 5, 14)
    assert first.layoff_count == 110
    assert first.county == "Unicoi"
    assert first.raw_notice_url is not None


def test_tn_notice_url_is_pdf(tn_sample_html: bytes) -> None:
    scraper = get_scraper("TN")
    rows = scraper.parse(tn_sample_html)
    pdf_rows = [r for r in rows if r.raw_notice_url and ".pdf" in r.raw_notice_url]
    assert pdf_rows, "expected at least some rows to link to PDFs"


def test_tn_notice_number_in_extra(tn_sample_html: bytes) -> None:
    scraper = get_scraper("TN")
    rows = scraper.parse(tn_sample_html)
    with_num = [r for r in rows if r.extra.get("notice_number")]
    assert with_num, "expected at least some rows to have a notice_number"


def test_tn_validation_passes(tn_sample_html: bytes) -> None:
    scraper = get_scraper("TN")
    rows = scraper.parse(tn_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_tn_raises_without_table() -> None:
    scraper = get_scraper("TN")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
