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
    / "hi"
    / "sample.html"
)


@pytest.fixture
def hi_sample_html() -> bytes:
    return FIXTURE.read_bytes()


def test_hi_parses_live_sample(hi_sample_html: bytes) -> None:
    scraper = get_scraper("HI")
    rows = scraper.parse(hi_sample_html)
    assert len(rows) >= 5
    assert all(r.state == "HI" for r in rows)

    first = rows[0]
    assert "Pharmerica" in first.employer
    assert first.notice_date == date(2026, 5, 7)
    assert first.raw_notice_url is not None
    assert first.raw_notice_url.endswith(".pdf")


def test_hi_notice_urls_are_pdfs(hi_sample_html: bytes) -> None:
    scraper = get_scraper("HI")
    rows = scraper.parse(hi_sample_html)
    pdf_rows = [r for r in rows if r.raw_notice_url]
    assert pdf_rows, "expected at least some rows to have a PDF URL"
    assert all(".pdf" in r.raw_notice_url for r in pdf_rows)


def test_hi_conditional_warn_parsed(hi_sample_html: bytes) -> None:
    """'Conditional WARN' entries are still parsed as notices."""
    scraper = get_scraper("HI")
    rows = scraper.parse(hi_sample_html)
    rndc = next(
        (r for r in rows if "RNDC" in (r.employer or "") or "Republic" in (r.employer or "")),
        None,
    )
    assert rndc is not None, "expected to find the Conditional WARN entry for RNDC"
    assert rndc.notice_date == date(2026, 4, 23)


def test_hi_update_prefix_stripped(hi_sample_html: bytes) -> None:
    """'UPDATE - DFS Group L.P.' -> employer is 'DFS Group L.P.'"""
    scraper = get_scraper("HI")
    rows = scraper.parse(hi_sample_html)
    dfs_updates = [r for r in rows if r.employer and "DFS" in r.employer]
    assert dfs_updates, "expected DFS Group entries"
    # The UPDATE entry should not have 'UPDATE' in the employer name
    for r in dfs_updates:
        assert not r.employer.startswith("UPDATE"), f"UPDATE prefix not stripped: {r.employer}"


def test_hi_rescinded_entry_still_parsed(hi_sample_html: bytes) -> None:
    """Rescinded entries still appear (the original notice date is captured)."""
    scraper = get_scraper("HI")
    rows = scraper.parse(hi_sample_html)
    kauai = [r for r in rows if r.employer and "Kauai Coffee" in r.employer]
    assert kauai, "expected Kauai Coffee entries even though they were rescinded"


def test_hi_validation_passes(hi_sample_html: bytes) -> None:
    scraper = get_scraper("HI")
    rows = scraper.parse(hi_sample_html)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_hi_raises_on_bad_html() -> None:
    scraper = get_scraper("HI")
    with pytest.raises(ParseFailed):
        # No <p> elements at all — should raise ParseFailed
        scraper.parse(b"<html><body><div>no paragraphs</div></body></html>")
