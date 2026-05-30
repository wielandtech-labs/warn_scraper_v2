"""Illinois WARN scraper tests."""
from __future__ import annotations

import io
from datetime import date

import openpyxl
import pytest

from warn_v2.db.models import Company
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.registry import get_scraper

# ---------------------------------------------------------------------------
# Fixture builder
# ---------------------------------------------------------------------------

_COLS = [
    "COMPANY NAME", "DBA", "COMPANY ADDRESS", "CITY, STATE, ZIP",
    "UNION", "BUMPING RIGHTS", "LOCAL WORKFORCE AREA", "REGION NUMBER",
    "TYPE OF COMPANY", "TYPE OF EVENT", "WARN RECEIVED DATE", "FIRST LAYOFF DATE",
    "ENDING LAYOFF DATE", "LAYOFF SCHEDULE", "WORKERS AFFECTED", "TYPE OF LAYOFF",
    "EVENT CAUSES", "CEJA RELATED", "COUNTY", "COMPANY NAICS",
]

# Columns:  NAME, DBA, ADDRESS, CITY_ST_ZIP, UNION, BUMPING, WFA, REGION,
#           TYPE_CO, TYPE_EVENT, WARN_DATE, FIRST_LAYOFF, END_LAYOFF, SCHEDULE,
#           WORKERS, TYPE_LAYOFF, CAUSES, CEJA, COUNTY, NAICS
_ROWS = [
    # 0: full row — closure, NAICS as integer
    ("Acme Steel Works", None, "1 Industrial Blvd", "Chicago, IL 60601",
     "Yes", "No", "Cook County", "1", "Manufacturing", "Plant Closing",
     date(2026, 1, 10), date(2026, 3, 11), date(2026, 4, 30), None,
     280, "Permanent", "Lack of orders", "No", "Cook", 331110),
    # 1: layoff, NAICS as text string
    ("Prairie Logistics LLC", None, "200 Corn Rd", "Peoria, IL 61602",
     "No", "No", "North Central", "2", "Transportation", "Layoff",
     date(2026, 2, 5), date(2026, 4, 6), None, None,
     65, "Permanent", "Restructuring", "No", "Peoria", "484110"),
    # 2: no NAICS
    ("Midway Retail Inc", "MRI", "500 State St", "Springfield, IL 62701",
     "No", "No", "Central", "3", "Retail", "Plant Closing",
     date(2026, 3, 1), date(2026, 4, 30), None, None,
     42, "Permanent", None, "No", "Sangamon", None),
    # 3: amendment (same employer/date/city as row 0, updated worker count)
    ("Acme Steel Works", None, "1 Industrial Blvd", "Chicago, IL 60601",
     "Yes", "No", "Cook County", "1", "Manufacturing", "Plant Closing",
     date(2026, 1, 10), date(2026, 3, 11), date(2026, 4, 30), None,
     310, "Permanent", "Lack of orders", "No", "Cook", 331110),
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
def il_sample_xlsx() -> bytes:
    return _build_xlsx()


# ---------------------------------------------------------------------------
# Core parsing
# ---------------------------------------------------------------------------


def test_il_parses_all_rows(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    assert len(rows) == 4


def test_il_first_row_fields(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    r = rows[0]

    assert r.state == "IL"
    assert r.employer == "Acme Steel Works"
    assert r.notice_date == date(2026, 1, 10)
    assert r.effective_date == date(2026, 3, 11)
    assert r.layoff_count == 280
    assert r.city == "Chicago"
    assert r.zip == "60601"
    assert r.address == "1 Industrial Blvd, Chicago, IL 60601"
    assert r.closure_type == "Plant Closing"
    assert r.county == "Cook"
    assert r.naics_code == "331110"


def test_il_naics_integer_converted_to_string(il_sample_xlsx: bytes) -> None:
    """NAICS stored as an integer in Excel is returned as a string."""
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    assert rows[0].naics_code == "331110"


def test_il_naics_text_passthrough(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    assert rows[1].naics_code == "484110"


def test_il_null_naics_is_none(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    assert rows[2].naics_code is None


def test_il_naics_not_in_extra(il_sample_xlsx: bytes) -> None:
    """NAICS must live on naics_code, not duplicated in extra."""
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    for r in rows:
        assert "naics" not in r.extra


def test_il_extra_fields_present(il_sample_xlsx: bytes) -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(il_sample_xlsx)
    r = rows[0]
    assert r.extra.get("layoff_type") == "Permanent"
    assert r.extra.get("event_causes") == "Lack of orders"
    assert r.extra.get("workforce_area") == "Cook County"


def test_il_raises_on_empty() -> None:
    scraper = get_scraper("IL")
    with pytest.raises(ParseFailed, match="no data rows"):
        scraper.parse(_build_xlsx([]))


# ---------------------------------------------------------------------------
# NAICS storage — Company.naics_code
# ---------------------------------------------------------------------------


def _il_row(**kw) -> NoticeRow:
    base = dict(
        state="IL",
        employer="Acme Steel Works",
        notice_date=date(2026, 1, 10),
        city="Chicago",
        zip="60601",
        naics_code="331110",
    )
    base.update(kw)
    return NoticeRow(**base)


def test_naics_written_to_company_on_insert(db) -> None:
    """NAICS from the WARN row is stored on Company when it is first created."""
    upsert_notices(db, [_il_row()])
    db.commit()
    assert db.query(Company).one().naics_code == "331110"


def test_naics_fills_in_null_on_existing_company(db) -> None:
    """A company created without NAICS gets it filled on the next upsert."""
    upsert_notices(db, [_il_row(naics_code=None)])
    db.commit()
    assert db.query(Company).one().naics_code is None

    upsert_notices(db, [_il_row(naics_code="331110")])
    db.commit()
    assert db.query(Company).one().naics_code == "331110"


def test_naics_does_not_overwrite_existing_code(db) -> None:
    """Existing naics_code on Company is preserved (first-non-null wins)."""
    upsert_notices(db, [_il_row(naics_code="331110")])
    db.commit()

    upsert_notices(db, [_il_row(naics_code="999999")])
    db.commit()
    assert db.query(Company).one().naics_code == "331110"


def test_naics_none_does_not_clear_existing(db) -> None:
    """naics_code=None on re-upsert must not clear an existing value."""
    upsert_notices(db, [_il_row(naics_code="331110")])
    db.commit()

    upsert_notices(db, [_il_row(naics_code=None)])
    db.commit()
    assert db.query(Company).one().naics_code == "331110"
