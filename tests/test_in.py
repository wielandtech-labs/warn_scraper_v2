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
    / "in"
    / "sample.html"
)


@pytest.fixture
def in_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_in_parses_live_sample(in_sample_html: bytes) -> None:
    scraper = get_scraper("IN")
    rows = scraper.parse(in_sample_html)
    # Cumulative table — 1000+ rows expected.
    assert len(rows) >= 100
    assert all(r.state == "IN" for r in rows)

    first = rows[0]
    assert "CICOA" in first.employer
    assert first.notice_date == date(2026, 4, 30)
    assert first.effective_date == date(2026, 5, 15)
    assert first.layoff_count == 90
    assert first.city == "Indianapolis"
    assert first.closure_type == "Layoff"


def test_in_notice_type_mapped(in_sample_html: bytes) -> None:
    scraper = get_scraper("IN")
    rows = scraper.parse(in_sample_html)
    types = {r.closure_type for r in rows if r.closure_type}
    assert "Layoff" in types or "Closure" in types


def test_in_has_naics_in_extra(in_sample_html: bytes) -> None:
    scraper = get_scraper("IN")
    rows = scraper.parse(in_sample_html)
    rows_with_naics = [r for r in rows if r.extra.get("naics")]
    assert rows_with_naics, "expected some rows to have NAICS codes"


def test_in_validation_passes(in_sample_html: bytes) -> None:
    scraper = get_scraper("IN")
    rows = scraper.parse(in_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_in_raises_without_table() -> None:
    scraper = get_scraper("IN")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table</p></body></html>")
