"""Illinois WARN scraper tests."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from warn_v2.db.models import Company
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.il import parse_il_pdf

_FIXTURES = Path(__file__).resolve().parents[1] / "warn_v2" / "scrapers" / "fixtures" / "il"


def _pdf(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()

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
# Archive-format files (2020 through mid-2025)
# ---------------------------------------------------------------------------

# Real archive header layout (e.g. "September 2024 Monthly WARN Report.xlsx"):
# colon-suffixed, extra COMPANY CONTACT / PHONE columns, and the workers
# column titled "# WORKERS AFFECTED:".
_ARCHIVE_COLS = [
    "COMPANY NAME:", "DBA:", "COMPANY ADDRESS:", "CITY, STATE, ZIP:",
    "COMPANY CONTACT:", "PHONE:", "UNION:", "BUMPING RIGHTS:",
    "LOCAL WORKFORCE AREA:", "REGION NUMBER:", "TYPE OF COMPANY:",
    "TYPE OF EVENT:", "WARN RECEIVED DATE:", "FIRST LAYOFF DATE:",
    "ENDING LAYOFF DATE:", "LAYOFF SCHEDULE:", "# WORKERS AFFECTED:",
    "TYPE OF LAYOFF:", "EVENT CAUSES:       ", "COUNTY:", "COMPANY NAICS:",
]

_ARCHIVE_ROWS = [
    ("Amazon", None, "1111 N Cherry Ave.", "Chicago, IL 60642",
     "Jane Doe", "202-555-0100", "No", "No", 7, "Northeast 4",
     "Warehousing and Storage", "Closing",
     date(2024, 9, 16), date(2024, 11, 13), None, None,
     211, "Permanent", "Relocation", "Cook", "493110"),
    # Multi-worksite filing: one whitespace-padded number per site in the
    # workers cell (mirrors the address cell), as in "Sep 2025" for
    # Carolina Therapeutic Services.
    ("Carolina Therapeutic Services", "CTS Health, Inc.",
     "2715 N. Central Ave.                   56 E. 47th",
     "Chicago, IL 60639", "T. McKeiver", "704-555-0147", "No", "No",
     7, "Northeast 4", "Health Care and Social Assistance", "Temp. layoff",
     date(2025, 9, 26), date(2025, 9, 26), None, None,
     "27                                      4                                        2",
     "Temporary", "Financial", "Cook", 621330),
    # Blank workers cell stays None.
    ("No Count Co", None, "1 Main St", "Springfield, IL 62701",
     None, None, "No", "No", 3, "Central", "Retail", "Layoff",
     date(2024, 9, 3), date(2024, 10, 31), None, None,
     None, "Permanent", None, "Sangamon", None),
    # Shifted row (as in "February 2021"): an extra layoff date sits in the
    # workers cell and the true count in TYPE OF LAYOFF. Digit-summing the
    # date fabricated counts (4/14/2021 -> 2039, prod's "Gallatin IL 379%").
    ("Flying Food Group, LLC", None, "4330 N. Transworld Road",
     "Schiller Park, IL 60176", "Roger Keirn", "847-555-0726", "Yes", "Yes",
     7, 4, "Caterers", "Mass Layoff",
     date(2020, 8, 3), date(2021, 2, 16), date(2021, 4, 1), None,
     "4/14/2021", 80, "COVID-19", "Cook", "722320"),
    # Shifted row where the next column holds no numeric count either.
    ("Peabody Midwest Management Services, LLC", None, "420 Long Lane Road",
     "Equality, Illinois 62934", None, None, "Yes", "No", 25, 5,
     "Mining", "Layoff",
     date(2019, 10, 14), date(2020, 5, 1), None, None,
     date(2020, 5, 14), "Permanent", None, "Gallatin", None),
    # Month-name date in the workers cell.
    ("Month Name Co", None, "2 Main St", "Springfield, IL 62701",
     None, None, "No", "No", 3, "Central", "Retail", "Layoff",
     date(2021, 1, 5), date(2021, 3, 1), None, None,
     "Feb 16, 2021", "Permanent", None, "Sangamon", None),
]


def _build_archive_xlsx(rows: list[tuple] = _ARCHIVE_ROWS) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(_ARCHIVE_COLS)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_il_archive_hash_workers_header_parsed() -> None:
    """'# WORKERS AFFECTED:' header variant must yield counts (was dropped)."""
    scraper = get_scraper("IL")
    rows = scraper.parse(_build_archive_xlsx())
    assert rows[0].layoff_count == 211
    assert rows[0].employer == "Amazon"
    assert rows[0].notice_date == date(2024, 9, 16)


def test_il_multi_worksite_workers_cell_summed() -> None:
    """Whitespace-packed per-site numbers ('27   4   2') sum to one count."""
    scraper = get_scraper("IL")
    rows = scraper.parse(_build_archive_xlsx())
    assert rows[1].layoff_count == 27 + 4 + 2


def test_il_archive_blank_workers_cell_is_none() -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(_build_archive_xlsx())
    assert rows[2].layoff_count is None


def test_il_shifted_row_recovers_count_from_type_of_layoff() -> None:
    """Date in the workers cell + count in TYPE OF LAYOFF -> count recovered."""
    scraper = get_scraper("IL")
    rows = scraper.parse(_build_archive_xlsx())
    assert rows[3].layoff_count == 80
    # TYPE OF LAYOFF held the count, not a real layoff type.
    assert rows[3].extra.get("layoff_type") is None


def test_il_date_workers_cell_without_shifted_count_is_none() -> None:
    """A datetime workers cell must never be digit-summed into a count."""
    scraper = get_scraper("IL")
    rows = scraper.parse(_build_archive_xlsx())
    assert rows[4].layoff_count is None  # was 2+16+2021-style garbage before
    assert rows[4].extra.get("layoff_type") == "Permanent"


def test_il_month_name_workers_cell_is_none() -> None:
    scraper = get_scraper("IL")
    rows = scraper.parse(_build_archive_xlsx())
    assert rows[5].layoff_count is None


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


# ---------------------------------------------------------------------------
# Historical PDF era (1999-2019) — parse_il_pdf
# ---------------------------------------------------------------------------
#
# Fixtures are real monthly archive PDFs, one per format era:
#   1999 — COMPANY SIC, PRIMARY EVENT COUNTY section headers, no ENDING date
#   2005 — CITY, STATE (no ZIP), SIC, per-notice COUNTY
#   2010 — COMPANY NAICS, UNION/BUMPING/Permanent-or-Temporary
#   2019 — NAICS, "Monthly WARN Report" naming, wrapped company name


def _first(rows: list[NoticeRow], employer: str) -> NoticeRow:
    return next(r for r in rows if r.employer == employer)


def test_il_pdf_2019_first_row_fields() -> None:
    rows = parse_il_pdf(_pdf("sample_pdf_2019.pdf"), "http://x/dec2019.pdf")
    r = rows[0]
    assert r.state == "IL"
    # wrapped company name is joined across the two form lines
    assert r.employer == "The GSI Group (Grain Systems, Inc.)"
    assert r.notice_date == date(2019, 12, 2)
    assert r.effective_date == date(2020, 1, 31)
    assert r.layoff_count == 89
    assert r.city == "Flora"
    assert r.zip == "62839"
    assert r.county == "Clay"
    assert r.closure_type == "Closing"
    assert r.naics_code == "332311"
    assert r.address == "1051 W. North Ave., Flora, IL 62839"
    assert r.source_url == "http://x/dec2019.pdf"
    assert r.extra["layoff_type"] == "Permanent"
    assert r.extra["event_causes"] == "Consolidation"
    assert "sic_code" not in r.extra


def test_il_pdf_1999_sic_kept_out_of_naics() -> None:
    """1999 reports carry SIC (not NAICS): naics_code stays None, SIC → extra."""
    rows = parse_il_pdf(_pdf("sample_pdf_1999.pdf"))
    r = _first(rows, "Newark Electronics Distribution Cntr")
    assert r.notice_date == date(1999, 12, 3)
    assert r.effective_date == date(2000, 1, 31)
    assert r.layoff_count == 60
    assert r.city == "Chicago"
    assert r.zip == "60624"
    assert r.naics_code is None
    assert r.extra["sic_code"] == "5065"
    # 1999 has no per-notice county — it comes from the PRIMARY EVENT COUNTY header
    assert r.county == "Cook"


def test_il_pdf_1999_legend_block_dropped() -> None:
    """The 1999 field-legend block parses as a dateless pseudo-notice → dropped."""
    rows = parse_il_pdf(_pdf("sample_pdf_1999.pdf"))
    assert all(r.notice_date is not None for r in rows)
    assert not any("event company" in r.employer.lower() for r in rows)


def test_il_pdf_2005_city_state_without_zip() -> None:
    """2005 uses 'CITY, STATE' (no ZIP): city parses, zip is None."""
    rows = parse_il_pdf(_pdf("sample_pdf_2005.pdf"))
    r = _first(rows, "Delta Air Lines")
    assert r.notice_date == date(2005, 12, 12)
    assert r.city == "Chicago"
    assert r.zip is None
    assert r.county == "Cook"
    assert r.extra["sic_code"] == "4512"


def test_il_pdf_2010_naics_and_layoff_type() -> None:
    rows = parse_il_pdf(_pdf("sample_pdf_2010.pdf"))
    r = _first(rows, "Kaplan University")
    assert r.notice_date == date(2010, 12, 10)
    assert r.effective_date == date(2011, 2, 6)
    assert r.layoff_count == 192
    assert r.naics_code == "611699"
    assert "sic_code" not in r.extra
    assert r.extra["layoff_type"] == "Permanent"


def test_il_pdf_not_provided_count_is_none() -> None:
    """'# WORKERS AFFECTED: Not Provided' yields no count, not a fabricated one."""
    rows = parse_il_pdf(_pdf("sample_pdf_2005.pdf"))
    r = _first(rows, "Doumak, Inc.")
    assert r.layoff_count is None


def test_il_pdf_all_rows_have_employer_and_date() -> None:
    for name in (
        "sample_pdf_1999.pdf",
        "sample_pdf_2005.pdf",
        "sample_pdf_2010.pdf",
        "sample_pdf_2019.pdf",
    ):
        rows = parse_il_pdf(_pdf(name))
        assert rows, name
        assert all(r.employer and r.notice_date for r in rows), name


def test_il_pdf_raises_on_non_pdf() -> None:
    with pytest.raises(ParseFailed):
        parse_il_pdf(b"not a pdf")
