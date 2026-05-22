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
    / "ia"
    / "sample.xlsx"
)


@pytest.fixture
def ia_sample_xlsx() -> bytes:
    return FIXTURE.read_bytes()


def test_ia_parses_live_sample(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    assert len(rows) >= 50
    assert all(r.state == "IA" for r in rows)


def test_ia_first_row(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    first = rows[0]
    assert "Seal and Stripe" in first.employer
    assert first.notice_date == date(2021, 5, 14)
    assert first.layoff_count == 10
    assert first.city == "Bettendorf"
    assert first.county == "Scott"


def test_ia_effective_date(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    first = rows[0]
    assert first.effective_date == date(2021, 6, 13)


def test_ia_closure_type(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    with_type = [r for r in rows if r.closure_type]
    assert with_type
    types = {r.closure_type for r in with_type}
    assert any(t in types for t in ("Closing", "Layoff", "Amendment"))


def test_ia_extra_fields(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    first = rows[0]
    assert first.extra.get("wda") == "Mississippi Valley"
    assert first.extra.get("industry") == "Construction"


def test_ia_validation_passes(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ia_raises_on_bad_xlsx() -> None:
    scraper = get_scraper("IA")
    with pytest.raises(ParseFailed):
        scraper.parse(b"not an excel file")
