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
    / "ak"
    / "sample.html"
)


@pytest.fixture
def ak_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_ak_parses_live_sample(ak_sample_html: bytes) -> None:
    scraper = get_scraper("AK")
    rows = scraper.parse(ak_sample_html)
    assert len(rows) >= 10
    assert all(r.state == "AK" for r in rows)

    first = rows[0]
    assert "Chugach" in first.employer
    assert first.notice_date == date(2025, 6, 2)
    assert first.effective_date == date(2025, 6, 30)
    assert first.layoff_count == 110
    assert first.city == "Palmer"
    assert first.closure_type == "Loss of Contract"
    assert first.raw_notice_url is not None


def test_ak_notice_url_is_pdf(ak_sample_html: bytes) -> None:
    scraper = get_scraper("AK")
    rows = scraper.parse(ak_sample_html)
    pdf_rows = [r for r in rows if r.raw_notice_url and ".pdf" in r.raw_notice_url]
    assert pdf_rows, "expected at least some rows to link to PDFs"


def test_ak_closure_type_populated(ak_sample_html: bytes) -> None:
    scraper = get_scraper("AK")
    rows = scraper.parse(ak_sample_html)
    typed = [r for r in rows if r.closure_type]
    assert typed, "expected at least some rows to have closure_type"
    types = {r.closure_type for r in typed}
    assert types & {"Closure", "Layoff", "Loss of Contract"}


def test_ak_validation_passes(ak_sample_html: bytes) -> None:
    scraper = get_scraper("AK")
    rows = scraper.parse(ak_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ak_raises_without_table() -> None:
    scraper = get_scraper("AK")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
