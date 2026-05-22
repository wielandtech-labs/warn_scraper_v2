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
    / "nv"
    / "sample.pdf"
)


@pytest.fixture
def nv_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_nv_parses_live_sample(nv_sample_pdf: bytes) -> None:
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    assert len(rows) >= 5
    assert all(r.state == "NV" for r in rows)

    # Spirit Airlines: received 1/22/2026, 1 employee, Las Vegas, Clark
    spirit = next((r for r in rows if "Spirit" in (r.employer or "")), None)
    assert spirit is not None, "expected Spirit Airlines entry"
    assert spirit.notice_date == date(2026, 1, 22)
    assert spirit.layoff_count == 1
    assert spirit.city == "Las Vegas"
    assert spirit.county == "Clark"
    assert spirit.closure_type == "Layoff"


def test_nv_merged_count_employer_split(nv_sample_pdf: bytes) -> None:
    """'209SK' in raw PDF -> count=209, employer='SK Food Group, Inc.'"""
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    sk = next((r for r in rows if "SK Food" in (r.employer or "")), None)
    assert sk is not None, "expected SK Food Group entry"
    assert sk.layoff_count == 209


def test_nv_merged_date_type_split(nv_sample_pdf: bytes) -> None:
    """'3/15/2026Layoff' raw token -> effective_date 2026-03-15, type Layoff."""
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    spirit = next((r for r in rows if "Spirit" in (r.employer or "")), None)
    assert spirit is not None
    assert spirit.effective_date == date(2026, 3, 15)


def test_nv_notification_in_extra(nv_sample_pdf: bytes) -> None:
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    warn_rows = [r for r in rows if r.extra.get("notification") == "WARN"]
    non_warn_rows = [r for r in rows if r.extra.get("notification") == "Non-WARN"]
    assert warn_rows, "expected at least some WARN entries"
    assert non_warn_rows, "expected at least some Non-WARN entries"


def test_nv_iherb_count(nv_sample_pdf: bytes) -> None:
    """'113iHerb' -> count=113, employer='iHerb'."""
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    iherb = next((r for r in rows if "iHerb" in (r.employer or "")), None)
    assert iherb is not None, "expected iHerb entry"
    assert iherb.layoff_count == 113
    assert iherb.closure_type == "Closure"


def test_nv_validation_passes(nv_sample_pdf: bytes) -> None:
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_nv_raises_on_bad_pdf() -> None:
    scraper = get_scraper("NV")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not a pdf file")
