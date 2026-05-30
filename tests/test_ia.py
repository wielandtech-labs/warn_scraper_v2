"""Iowa WARN scraper tests."""
from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest

from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ia import _dedup_zip_variance

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

_COLS = [
    "Company", "Address Line 1", "City", "County", "St", "ZIP",
    "Notice Type", "Emp #", "Notice Date", "Layoff Date",
    "Local Workforce Area", "Industry",
]

# Each tuple maps 1:1 to _COLS.
_ROWS = [
    # 0: normal row — all fields populated
    ("Seal & Stripe Inc", "425 S Devils Glen Rd", "Bettendorf", "Scott", "IA",
     52722, "Closing", 84, date(2026, 1, 10), date(2026, 3, 11),
     "Eastern Iowa", "Manufacturing"),
    # 1: normal row — different employer/city
    ("Prairie Wind Energy", "900 N Industrial Blvd", "Ames", "Story", "IA",
     50010, "Layoff", 120, date(2026, 2, 5), date(2026, 4, 6),
     "Central Iowa", "Energy"),
    # 2: ZIP-variance pair — same employer/date/city, NO zip/address
    ("Capital Logistics LLC", None, "Des Moines", "Polk", "IA",
     None, "Closing", 55, date(2026, 3, 1), date(2026, 4, 30),
     "Central Iowa", "Logistics"),
    # 3: ZIP-variance pair — same employer/date/city, HAS zip/address
    ("Capital Logistics LLC", "1200 Fleur Dr", "Des Moines", "Polk", "IA",
     50315, "Closing", 55, date(2026, 3, 1), date(2026, 4, 30),
     "Central Iowa", "Logistics"),
    # 4: multi-site employer — same name, same date, different cities → keep both
    ("Hawkeye Foods Corp", "200 Main St", "Davenport", "Scott", "IA",
     52801, "Closing", 40, date(2026, 3, 20), date(2026, 5, 19),
     "Eastern Iowa", "Food Production"),
    # 5: multi-site employer — same name, same date, different city
    ("Hawkeye Foods Corp", "300 River Rd", "Iowa City", "Johnson", "IA",
     52240, "Closing", 30, date(2026, 3, 20), date(2026, 5, 19),
     "Eastern Iowa", "Food Production"),
    # 6: row with no ZIP and no address (county-only geocoding)
    ("Frontier Farm Co", None, "Sioux City", "Woodbury", "IA",
     None, "Layoff", 22, date(2026, 4, 1), date(2026, 5, 31),
     "Western Iowa", "Agriculture"),
    # 7: leading-zero ZIP stored as 4-digit integer
    ("Old Colony Creamery", "10 Cream St", "Decorah", "Winneshiek", "IA",
     5101, "Layoff", 18, date(2026, 4, 15), None,
     "Northeast Iowa", "Dairy"),
]


def _build_xlsx(rows: list[tuple] = _ROWS) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_COLS)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def ia_sample_xlsx() -> bytes:
    return _build_xlsx()


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------


def test_ia_parses_expected_row_count(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    # 8 raw rows → ZIP-variance pair (rows 2+3) collapses to 1 → 7 output rows
    assert len(rows) == 7


def test_ia_first_row_fields(ia_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    first = rows[0]

    assert first.state == "IA"
    assert first.employer == "Seal & Stripe Inc"
    assert first.notice_date == date(2026, 1, 10)
    assert first.effective_date == date(2026, 3, 11)
    assert first.layoff_count == 84
    assert first.city == "Bettendorf"
    assert first.zip == "52722"
    assert first.address == "425 S Devils Glen Rd"
    assert first.closure_type == "Closing"
    assert first.extra.get("industry") == "Manufacturing"
    assert first.extra.get("wda") == "Eastern Iowa"


def test_ia_required_fields_present(ia_sample_xlsx: bytes) -> None:
    """Every parsed row must have the two required fields."""
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    assert all(r.employer for r in rows)
    assert all(r.notice_date is not None for r in rows)


def test_ia_leading_zero_zip(ia_sample_xlsx: bytes) -> None:
    """A 4-digit integer ZIP gets a leading zero restored."""
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    decorah = next(r for r in rows if r.employer == "Old Colony Creamery")
    assert decorah.zip == "05101"


def test_ia_null_effective_date_row(ia_sample_xlsx: bytes) -> None:
    """Rows without a Layoff Date have effective_date=None at parse time
    (the 60-day fallback is applied later by storage, not the scraper)."""
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    decorah = next(r for r in rows if r.employer == "Old Colony Creamery")
    assert decorah.effective_date is None


def test_ia_raises_on_empty() -> None:
    scraper = get_scraper("IA")
    with pytest.raises(ParseFailed, match="no data rows"):
        scraper.parse(_build_xlsx([]))


# ---------------------------------------------------------------------------
# ZIP-variance deduplication
# ---------------------------------------------------------------------------


def test_ia_zip_variance_pair_collapses_to_zip_bearing_row(ia_sample_xlsx: bytes) -> None:
    """Same employer/date/city with and without ZIP → keep the ZIP row."""
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    capital = [r for r in rows if r.employer == "Capital Logistics LLC"]
    assert len(capital) == 1
    assert capital[0].zip == "50315"
    assert capital[0].address == "1200 Fleur Dr"


def test_ia_multi_site_both_kept(ia_sample_xlsx: bytes) -> None:
    """Same employer/date but different cities → both rows kept."""
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    hawkeye = [r for r in rows if r.employer == "Hawkeye Foods Corp"]
    assert len(hawkeye) == 2
    cities = {r.city for r in hawkeye}
    assert cities == {"Davenport", "Iowa City"}


def test_ia_no_zip_row_kept_when_no_sibling(ia_sample_xlsx: bytes) -> None:
    """A row with no ZIP that has no sibling is kept as-is."""
    scraper = get_scraper("IA")
    rows = scraper.parse(ia_sample_xlsx)
    frontier = [r for r in rows if r.employer == "Frontier Farm Co"]
    assert len(frontier) == 1
    assert frontier[0].zip is None


# ---------------------------------------------------------------------------
# _dedup_zip_variance unit tests
# ---------------------------------------------------------------------------


def _row(employer: str, nd: date, city: str, zip_: str | None, **kw) -> NoticeRow:
    return NoticeRow(state="IA", employer=employer, notice_date=nd, city=city, zip=zip_, **kw)


_D = date(2026, 1, 1)


def test_dedup_drops_zipless_when_sibling_has_zip() -> None:
    rows = [_row("Acme", _D, "Ames", None), _row("Acme", _D, "Ames", "50010")]
    result = _dedup_zip_variance(rows)
    assert len(result) == 1
    assert result[0].zip == "50010"


def test_dedup_keeps_all_when_both_have_zip() -> None:
    """Two rows with different ZIPs = different sites → keep both."""
    rows = [_row("Acme", _D, "Ames", "50010"), _row("Acme", _D, "Ames", "50011")]
    result = _dedup_zip_variance(rows)
    assert len(result) == 2


def test_dedup_keeps_zipless_when_no_sibling_has_zip() -> None:
    rows = [_row("Acme", _D, "Ames", None)]
    result = _dedup_zip_variance(rows)
    assert len(result) == 1


def test_dedup_normalises_employer_case() -> None:
    """Employer name differing only in case is treated as the same key."""
    rows = [_row("acme corp", _D, "Ames", None), _row("Acme Corp", _D, "Ames", "50010")]
    result = _dedup_zip_variance(rows)
    assert len(result) == 1
    assert result[0].zip == "50010"


def test_dedup_different_dates_not_collapsed() -> None:
    """Different notice dates → distinct notices, kept separately."""
    rows = [
        _row("Acme", date(2026, 1, 1), "Ames", None),
        _row("Acme", date(2026, 2, 1), "Ames", "50010"),
    ]
    result = _dedup_zip_variance(rows)
    assert len(result) == 2
