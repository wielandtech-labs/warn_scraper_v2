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
    / "sc"
    / "sample.pdf"
)


@pytest.fixture
def sc_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_sc_parses_live_sample(sc_sample_pdf: bytes) -> None:
    scraper = get_scraper("SC")
    rows = scraper.parse(sc_sample_pdf)
    assert len(rows) >= 5
    assert all(r.state == "SC" for r in rows)

    first = rows[0]
    assert "Saddle Creek" in first.employer
    assert first.notice_date == date(2026, 1, 2)
    assert first.effective_date == date(2026, 3, 5)
    assert first.layoff_count == 130
    assert first.county == "Spartanburg"
    assert first.city == "Duncan"
    assert first.zip == "29651"


def test_sc_closure_type_populated(sc_sample_pdf: bytes) -> None:
    scraper = get_scraper("SC")
    rows = scraper.parse(sc_sample_pdf)
    with_type = [r for r in rows if r.closure_type]
    assert with_type, "expected at least some rows with a closure type"
    assert all("Layoff" in (r.closure_type or "") or "Closure" in (r.closure_type or "")
               for r in with_type)


def test_sc_garbled_date_extracted(sc_sample_pdf: bytes) -> None:
    """SMBC row has county text merged with notice date; scraper recovers the date."""
    scraper = get_scraper("SC")
    rows = scraper.parse(sc_sample_pdf)
    smbc = next((r for r in rows if "SMBC" in (r.employer or "")), None)
    assert smbc is not None, "expected SMBC entry"
    assert smbc.notice_date == date(2026, 1, 8)


def test_sc_date_range_effective_date(sc_sample_pdf: bytes) -> None:
    """Entries with 'M/D/YYYY - M/D/YYYY' effective date use the first date."""
    scraper = get_scraper("SC")
    rows = scraper.parse(sc_sample_pdf)
    # International Paper has "5/1/2026 - 12/31/2026"
    ip = next((r for r in rows if "International Paper" in (r.employer or "")), None)
    assert ip is not None, "expected International Paper entry"
    assert ip.effective_date == date(2026, 5, 1)


def test_sc_zip_and_city_extracted(sc_sample_pdf: bytes) -> None:
    scraper = get_scraper("SC")
    rows = scraper.parse(sc_sample_pdf)
    with_zip = [r for r in rows if r.zip]
    assert with_zip, "expected at least some rows with a ZIP code"
    assert all(len(r.zip) == 5 for r in with_zip)


def test_sc_validation_passes(sc_sample_pdf: bytes) -> None:
    scraper = get_scraper("SC")
    rows = scraper.parse(sc_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_sc_raises_on_bad_pdf() -> None:
    scraper = get_scraper("SC")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not a pdf file")
