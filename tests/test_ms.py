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
    / "ms"
    / "sample.pdf"
)


@pytest.fixture
def ms_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_ms_parses_live_sample(ms_sample_pdf: bytes) -> None:
    scraper = get_scraper("MS")
    rows = scraper.parse(ms_sample_pdf)
    assert len(rows) >= 1
    assert all(r.state == "MS" for r in rows)

    first = rows[0]
    assert "GXO" in first.employer
    assert first.notice_date == date(2026, 1, 6)
    assert first.effective_date == date(2026, 1, 31)
    assert first.layoff_count == 220
    assert first.city == "Southaven"
    assert first.county == "DeSoto"
    assert first.closure_type == "Closure"


def test_ms_wda_field_populated(ms_sample_pdf: bytes) -> None:
    scraper = get_scraper("MS")
    rows = scraper.parse(ms_sample_pdf)
    with_wda = [r for r in rows if r.extra.get("wda")]
    assert with_wda, "expected at least some rows to have a WDA (workforce area)"


def test_ms_multiline_company_name_joined(ms_sample_pdf: bytes) -> None:
    """'GXO\\nLogistics' should parse as 'GXO Logistics', not 'GXO'."""
    scraper = get_scraper("MS")
    rows = scraper.parse(ms_sample_pdf)
    gxo = next((r for r in rows if "GXO" in (r.employer or "")), None)
    assert gxo is not None
    assert "Logistics" in gxo.employer, "multi-line company name should be joined"


def test_ms_dot_date_separator_handled(ms_sample_pdf: bytes) -> None:
    """'4/3.2026' effective date (dot instead of slash) is parsed correctly."""
    scraper = get_scraper("MS")
    rows = scraper.parse(ms_sample_pdf)
    nike = next((r for r in rows if "NIKE" in (r.employer or "")), None)
    assert nike is not None, "expected NIKE entry"
    assert nike.effective_date == date(2026, 4, 3)


def test_ms_closure_type_populated(ms_sample_pdf: bytes) -> None:
    scraper = get_scraper("MS")
    rows = scraper.parse(ms_sample_pdf)
    with_type = [r for r in rows if r.closure_type]
    assert with_type, "expected at least some rows with a closure type"
    assert all(r.closure_type in ("Closure", "Layoff") for r in with_type)


def test_ms_validation_passes(ms_sample_pdf: bytes) -> None:
    scraper = get_scraper("MS")
    rows = scraper.parse(ms_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ms_raises_on_bad_pdf() -> None:
    scraper = get_scraper("MS")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not a pdf file")
