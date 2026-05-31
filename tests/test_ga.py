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
    / "ga"
    / "sample.html"
)


@pytest.fixture
def ga_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_ga_parses_fixture(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    assert len(rows) >= 5
    assert all(r.state == "GA" for r in rows)

    first = rows[0]
    assert "Dexter Axle" in first.employer
    assert first.notice_date == date(2023, 1, 17)
    assert first.layoff_count == 67
    assert first.raw_notice_url == "https://www.tcsg.edu/warn-public-view/entry/41068/"


def test_ga_raw_notice_urls_present(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    with_url = [r for r in rows if r.raw_notice_url]
    assert len(with_url) == len(rows), "every GA row should have a raw_notice_url"


def test_ga_layoff_counts_present(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    with_count = [r for r in rows if r.layoff_count is not None]
    assert len(with_count) >= 5, "expected at least some rows to have layoff counts"


def test_ga_validation_passes(ga_sample_html: bytes) -> None:
    scraper = get_scraper("GA")
    rows = scraper.parse(ga_sample_html)
    # The fixture is a 25-row snapshot (one DataTables page); validate against
    # a range that fits the fixture rather than the live expected_row_range.
    import types
    fixture_scraper = types.SimpleNamespace(
        state=scraper.state,
        source_url=scraper.source_url,
        expected_row_range=(5, 50),
        required_fields=scraper.required_fields,
    )
    result = validate(fixture_scraper, rows)
    assert result.ok, result.reason


def test_ga_raises_without_table() -> None:
    scraper = get_scraper("GA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"<html><body><p>no table here</p></body></html>")
