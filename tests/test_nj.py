"""NJ scraper tests against a real PDF snapshot of the live source."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "nj"
    / "sample.pdf"
)


@pytest.fixture
def nj_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_nj_extracts_rows_from_pdf(nj_sample_pdf: bytes) -> None:
    scraper = get_scraper("NJ")
    rows = scraper.parse(nj_sample_pdf)
    # The 2026 fixture should have at least the ~10 entries on page 1.
    assert len(rows) >= 10

    by_employer = {r.employer: r for r in rows}
    # Sanity-check known entries from the live 2026 sample.
    assert "The Fresh Market" in by_employer
    fresh = by_employer["The Fresh Market"]
    assert fresh.state == "NJ"
    assert fresh.city == "Montvale"
    assert fresh.layoff_count == 55
    assert fresh.notice_date == date(2026, 1, 1)  # "January" → first of month
    assert fresh.effective_date == date(2026, 4, 12)


def test_nj_passes_validation(nj_sample_pdf: bytes) -> None:
    scraper = get_scraper("NJ")
    rows = scraper.parse(nj_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_nj_preserves_raw_fields(nj_sample_pdf: bytes) -> None:
    scraper = get_scraper("NJ")
    rows = scraper.parse(nj_sample_pdf)
    # At least one row should have multi-date / multi-region complexity preserved
    multi = [r for r in rows if "," in r.extra.get("workforce_affected_raw", "")
             or "," in r.extra.get("effective_date_raw", "")]
    assert multi, "expected at least one row with multi-value raw text"
