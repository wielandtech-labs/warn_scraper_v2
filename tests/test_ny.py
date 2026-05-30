"""NY scraper tests against a fixture CSV from the Tableau Public dashboard."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ny import _parse_address

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "ny"
    / "sample.csv"
)


@pytest.fixture
def ny_sample_csv() -> bytes:
    return FIXTURE.read_bytes()


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------

def test_ny_parses_all_rows(ny_sample_csv: bytes) -> None:
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_csv)
    assert len(rows) == 11


def test_ny_first_row_fields(ny_sample_csv: bytes) -> None:
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_csv)
    first = rows[0]

    assert first.state == "NY"
    assert first.employer == "Empire Foods Inc."
    assert first.notice_date == date(2026, 5, 15)
    assert first.effective_date == date(2026, 8, 1)
    assert first.layoff_count == 150
    assert first.closure_type == "Closure"
    assert first.city == "New York"
    assert first.zip == "10016"
    assert first.county == "New York"
    assert first.extra.get("layoff_type") == "Permanent"
    assert first.source_url == "https://dol.ny.gov/warn-dashboard"


def test_ny_passes_validation(ny_sample_csv: bytes) -> None:
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_csv)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_ny_layoff_count_populated(ny_sample_csv: bytes) -> None:
    """New source provides layoff_count inline — no longer deferred to enrichment."""
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_csv)
    assert all(r.layoff_count is not None for r in rows)
    counts = [r.layoff_count for r in rows]
    assert max(counts) == 552  # Long Island Medical Center


def test_ny_multi_site_employer(ny_sample_csv: bytes) -> None:
    """An employer with multiple impacted sites produces one row per site."""
    scraper = get_scraper("NY")
    rows = scraper.parse(ny_sample_csv)
    cayuga = [r for r in rows if r.employer == "Cayuga Home for Children"]
    assert len(cayuga) == 2
    zips = {r.zip for r in cayuga}
    assert "13021" in zips


def test_ny_raises_on_missing_header(ny_sample_csv: bytes) -> None:
    scraper = get_scraper("NY")
    with pytest.raises(ParseFailed, match="missing expected columns"):
        scraper.parse(b"Col A,Col B\nfoo,bar\n")


def test_ny_raises_on_empty_csv() -> None:
    scraper = get_scraper("NY")
    with pytest.raises(ParseFailed, match="no header row"):
        scraper.parse(b"")


# ---------------------------------------------------------------------------
# Address parsing
# ---------------------------------------------------------------------------

def test_parse_address_double_space_separator() -> None:
    _addr, city, zip_ = _parse_address("1440 Broadway  New York City, NY, 10018")
    assert city == "New York City"
    assert zip_ == "10018"


def test_parse_address_standard() -> None:
    _addr, city, zip_ = _parse_address("420 Park Ave S  New York, NY, 10016")
    assert city == "New York"
    assert zip_ == "10016"


def test_parse_address_fallback_no_double_space() -> None:
    """Addresses without double-space separator fall back to last comma split."""
    _addr, city, zip_ = _parse_address("456 Johnson Avenue 420 Brooklyn, NY, 11237")
    assert city == "Brooklyn"
    assert zip_ == "11237"


def test_parse_address_empty() -> None:
    addr, city, zip_ = _parse_address("")
    assert addr is None
    assert city is None
    assert zip_ is None


def test_parse_address_full_address_preserved() -> None:
    raw = "33 Hudson Yards  New York, NY, 10001"
    addr, _, _ = _parse_address(raw)
    assert addr == raw
