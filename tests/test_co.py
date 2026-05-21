from __future__ import annotations

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
    / "co"
    / "sample.csv"
)


@pytest.fixture
def co_sample_csv() -> bytes:
    return FIXTURE.read_bytes()


def test_co_parses_csv(co_sample_csv: bytes) -> None:
    scraper = get_scraper("CO")
    rows = scraper.parse(co_sample_csv)
    # The form has accumulated ~40+ submissions since 2019.
    assert len(rows) >= 10
    assert all(r.state == "CO" for r in rows)
    assert all(r.employer for r in rows)
    assert all(r.notice_date is not None for r in rows)


def test_co_preserves_breakdown_in_extra(co_sample_csv: bytes) -> None:
    scraper = get_scraper("CO")
    rows = scraper.parse(co_sample_csv)
    # At least one row should carry NAICS / workforce_area / reason in extras
    has_naics = any("naics" in r.extra for r in rows)
    has_area = any("workforce_area" in r.extra for r in rows)
    assert has_naics, "expected some rows to populate NAICS"
    assert has_area, "expected some rows to populate workforce_area"


def test_co_validation_passes(co_sample_csv: bytes) -> None:
    scraper = get_scraper("CO")
    rows = scraper.parse(co_sample_csv)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_co_raises_on_empty_csv() -> None:
    scraper = get_scraper("CO")
    with pytest.raises(ParseFailed):
        scraper.parse(b"")
