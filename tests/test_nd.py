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
    / "nd"
    / "sample.pdf"
)


@pytest.fixture
def nd_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_nd_parses_live_sample(nd_sample_pdf: bytes) -> None:
    scraper = get_scraper("ND")
    rows = scraper.parse(nd_sample_pdf)
    # Cumulative PDF 2015-present; expect many rows
    assert len(rows) >= 10
    assert all(r.state == "ND" for r in rows)

    first = rows[0]
    assert "EGS" in first.employer
    assert first.notice_date == date(2015, 7, 31)
    assert first.effective_date == date(2015, 12, 31)
    assert first.layoff_count == 95
    assert first.city == "Fargo"


def test_nd_merged_dates_split(nd_sample_pdf: bytes) -> None:
    """Newer entries pack notice + effective date into one cell: '1/15/2026 1/28/2026'."""
    scraper = get_scraper("ND")
    rows = scraper.parse(nd_sample_pdf)
    noridian = next((r for r in rows if "Noridian" in (r.employer or "")), None)
    assert noridian is not None, "expected Noridian entry"
    assert noridian.notice_date == date(2026, 1, 15)
    assert noridian.effective_date == date(2026, 1, 28)


def test_nd_hess_entry(nd_sample_pdf: bytes) -> None:
    """'7/21/2025beginning 9/26/2025' merged cell parsed correctly."""
    scraper = get_scraper("ND")
    rows = scraper.parse(nd_sample_pdf)
    hess = next((r for r in rows if "Hess" in (r.employer or "")), None)
    assert hess is not None, "expected Hess Corporation entry"
    assert hess.notice_date == date(2025, 7, 21)
    assert hess.effective_date == date(2025, 9, 26)
    assert hess.layoff_count == 111


def test_nd_notes_in_extra(nd_sample_pdf: bytes) -> None:
    scraper = get_scraper("ND")
    rows = scraper.parse(nd_sample_pdf)
    with_notes = [r for r in rows if r.extra.get("notes")]
    assert with_notes, "expected at least some rows to have notes"


def test_nd_validation_passes(nd_sample_pdf: bytes) -> None:
    scraper = get_scraper("ND")
    rows = scraper.parse(nd_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_nd_raises_on_bad_pdf() -> None:
    scraper = get_scraper("ND")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not a pdf file")
