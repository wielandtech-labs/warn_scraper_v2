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
    / "nm"
    / "sample.pdf"
)


@pytest.fixture
def nm_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_nm_parses_live_sample(nm_sample_pdf: bytes) -> None:
    scraper = get_scraper("NM")
    rows = scraper.parse(nm_sample_pdf)
    assert len(rows) >= 1
    assert all(r.state == "NM" for r in rows)

    first = rows[0]
    assert "Atkore" in first.employer
    assert first.notice_date == date(2026, 4, 27)
    assert first.effective_date == date(2026, 6, 30)
    assert first.layoff_count == 51
    assert first.city == "Albuquerque"
    assert first.county == "Bernalillo"
    assert first.extra.get("wda") == "Central Region"


def test_nm_validation_passes(nm_sample_pdf: bytes) -> None:
    scraper = get_scraper("NM")
    rows = scraper.parse(nm_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_nm_raises_on_bad_pdf() -> None:
    scraper = get_scraper("NM")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not a pdf file")
