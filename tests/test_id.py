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
    / "id"
    / "sample.pdf"
)


@pytest.fixture
def id_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_id_parses_live_sample(id_sample_pdf: bytes) -> None:
    scraper = get_scraper("ID")
    rows = scraper.parse(id_sample_pdf)
    # Cumulative PDF with data back to ~2009.
    assert len(rows) >= 50
    assert all(r.state == "ID" for r in rows)

    first = rows[0]
    assert "Idahoan" in first.employer
    assert first.notice_date == date(2026, 4, 21)
    assert first.effective_date == date(2026, 6, 26)
    assert first.layoff_count == 61
    assert first.city == "Rupert"
    assert first.zip == "83350"


def test_id_zip_populated(id_sample_pdf: bytes) -> None:
    scraper = get_scraper("ID")
    rows = scraper.parse(id_sample_pdf)
    with_zip = [r for r in rows if r.zip]
    assert with_zip, "expected at least some rows to have a ZIP code"


def test_id_multi_location_uses_first_city(id_sample_pdf: bytes) -> None:
    """Multi-location notices (newline-separated cities) use first city."""
    scraper = get_scraper("ID")
    rows = scraper.parse(id_sample_pdf)
    idaho_health = next((r for r in rows if "Idaho Health" in (r.employer or "")), None)
    if idaho_health:
        assert idaho_health.city == "Boise"


def test_id_validation_passes(id_sample_pdf: bytes) -> None:
    scraper = get_scraper("ID")
    rows = scraper.parse(id_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_id_raises_on_bad_pdf() -> None:
    scraper = get_scraper("ID")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not a pdf file")
