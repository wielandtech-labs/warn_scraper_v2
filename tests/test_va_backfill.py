"""Tests for the VA historical backfill (bundled archive, PY1999/PY2002/PY2003).

The bundle members under warn_v2/scrapers/data/va_archive.tar.gz are the real
Wayback captures, so these tests exercise the era parsers on the exact bytes
prod will ingest.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from warn_v2.db.models import Notice
from warn_v2.scrapers.states.va import (
    parse_va_archive_member,
    parse_va_excel_html,
    parse_va_py1999_xls,
    parse_va_py2002_pdf,
    va_archive_files,
)
from warn_v2.scripts.backfill_historical import backfill_historical


@pytest.fixture(scope="module")
def archive() -> dict[str, bytes]:
    return dict(va_archive_files())


@pytest.fixture(scope="module")
def xls_rows(archive):
    return parse_va_py1999_xls(archive["warnnot99.xls"])


@pytest.fixture(scope="module")
def pdf_rows(archive):
    return parse_va_py2002_pdf(archive["warnlog03.pdf"])


@pytest.fixture(scope="module")
def html_rows(archive):
    return parse_va_excel_html(archive["warnnot04_statewide.htm"])


# ---------------------------------------------------------------------------
# Bundle + dispatch
# ---------------------------------------------------------------------------

def test_archive_members(archive):
    assert sorted(archive) == [
        "warnlog03.pdf",
        "warnnot04_statewide.htm",
        "warnnot99.xls",
    ]


def test_member_dispatch():
    assert parse_va_archive_member("warnnot99.xls") is parse_va_py1999_xls
    assert parse_va_archive_member("warnlog03.pdf") is parse_va_py2002_pdf
    assert parse_va_archive_member("warnnot04_statewide.htm") is parse_va_excel_html
    assert parse_va_archive_member("something.csv") is None


# ---------------------------------------------------------------------------
# PY1999 xls — 59 numbered notice blocks
# ---------------------------------------------------------------------------

def test_py1999_row_count_and_program_year(xls_rows):
    assert len(xls_rows) == 59
    assert all(
        date(1999, 7, 1) <= r.notice_date <= date(2000, 6, 30) for r in xls_rows
    )
    # Every block resolves a city and both dates in this file.
    assert all(r.city for r in xls_rows)
    assert all(r.effective_date for r in xls_rows)


def test_py1999_first_and_last_notice(xls_rows):
    first = xls_rows[0]
    assert first.employer == "Levi Strauss"
    assert first.notice_date == date(1999, 7, 14)
    assert first.effective_date == date(1999, 10, 21)
    assert first.layoff_count == 338
    assert first.closure_type == "Closing"
    assert first.city == "Warsaw"

    last = xls_rows[-1]
    assert last.employer == "Bunker Hill Foods"
    assert last.layoff_count == 153
    # City comes from the "Bedford, VA" line, not the street line above it.
    assert last.city == "Bedford"


def test_py1999_dates_shifted_below_marker_row(xls_rows):
    """Notices 39/40 carry their dates a row or two below the marker row."""
    motorola = next(r for r in xls_rows if r.employer == "Motorola")
    assert motorola.notice_date == date(2000, 3, 17)
    assert motorola.effective_date == date(2000, 5, 25)
    assert motorola.city == "Leesburg"

    honeywell = next(r for r in xls_rows if r.employer == "Honeywell")
    assert honeywell.notice_date == date(2000, 3, 31)
    assert honeywell.effective_date == date(2000, 7, 30)
    assert honeywell.layoff_count == 200


def test_py1999_blank_counts_stay_none(xls_rows):
    # 7 notices have no EST/Actual value in the source.
    assert sum(1 for r in xls_rows if r.layoff_count is None) == 7
    assert sum(r.layoff_count or 0 for r in xls_rows) == 9110


# ---------------------------------------------------------------------------
# PY2002 pdf — 11-page log
# ---------------------------------------------------------------------------

def test_py2002_row_count_and_program_year(pdf_rows):
    assert len(pdf_rows) == 87
    assert all(
        date(2002, 7, 1) <= r.notice_date <= date(2003, 6, 30) for r in pdf_rows
    )
    assert sum(r.layoff_count or 0 for r in pdf_rows) == 11573


def test_py2002_first_row_fields(pdf_rows):
    first = pdf_rows[0]
    assert first.employer == "APG, Inc"
    assert first.notice_date == date(2002, 7, 9)
    assert first.effective_date == date(2002, 9, 30)
    assert first.layoff_count == 57
    assert first.closure_type == "Closing"
    assert first.address == "8401 Southern Boulevard, Youngstown, OH 44512"


def test_py2002_source_duplicate_kept_but_dedupes_by_id(pdf_rows):
    """The Ericsson 2/24/03 row is printed twice in the source PDF; the parser
    is data-faithful and keeps both — notice_id dedupes them at ingest."""
    from warn_v2.pipeline.dedup import notice_id

    ericsson = [
        r
        for r in pdf_rows
        if r.employer == "Ericsson, Inc" and r.notice_date == date(2003, 2, 24)
    ]
    assert len(ericsson) == 2
    assert notice_id(ericsson[0]) == notice_id(ericsson[1])
    # ... and it is the only exact duplicate in the whole PDF.
    ids = [notice_id(r) for r in pdf_rows]
    assert len(set(ids)) == len(ids) - 1


def test_py2002_wrapped_city_and_glued_row(pdf_rows):
    # "Newport\nNews" is a wrapped single city, not a multi-city list.
    globe = next(r for r in pdf_rows if r.employer == "Globe Aviation")
    assert globe.city == "Newport News"
    # The last row glues the date columns onto the company line; the employer
    # must still come out clean.
    intermet = next(r for r in pdf_rows if "Intermet" in r.employer)
    assert intermet.employer == "Intermet Corporation"
    assert intermet.layoff_count == 346
    assert intermet.city == "Radford"


# ---------------------------------------------------------------------------
# PY2003 Excel-HTML statewide sheet
# ---------------------------------------------------------------------------

def test_py2003_row_count_and_total_anchor(html_rows):
    # The sheet's own TOTAL row says 75 notices / 11,155 employees. The 76th
    # parsed row is the Ericsson 9/22/03 notice recorded on an address line —
    # the TOTAL row's notice count skips it but its 1 employee IS in the sum.
    assert len(html_rows) == 76
    assert sum(r.layoff_count or 0 for r in html_rows) == 11155
    assert all(
        date(2003, 7, 1) <= r.notice_date <= date(2004, 6, 30) for r in html_rows
    )


def test_py2003_first_row_fields(html_rows):
    first = html_rows[0]
    assert first.employer == "Circuit City Stores, Inc."
    assert first.notice_date == date(2004, 6, 28)
    assert first.effective_date == date(2004, 9, 24)
    assert first.layoff_count == 51
    assert first.closure_type == "Layoff"
    assert first.city == "Richmond"
    assert first.address == "9954 Mayland Drive, Richmond, VA 23233"


def test_py2003_address_line_notice_inherits_employer(html_rows):
    """One notice was recorded on an address line ("6300 Legacy Drive"); it
    belongs to the Ericsson entry directly above it."""
    row = next(r for r in html_rows if r.notice_date == date(2003, 9, 22))
    assert row.employer == "Ericsson, Inc."
    assert row.layoff_count == 1


# ---------------------------------------------------------------------------
# End-to-end through the backfill registry
# ---------------------------------------------------------------------------

def test_backfill_va_ingests_all_members(db):
    stats = backfill_historical("VA")

    assert stats["years_attempted"] == 3
    assert stats["years_ok"] == 3
    # 221 unique of 222 parsed: the doubled Ericsson PDF row collapses by
    # notice_id before upsert.
    assert stats["rows_seen"] == 221
    assert stats["rows_new"] == 221
    assert db.execute(select(func.count(Notice.notice_id))).scalar_one() == 221

    # Idempotent re-run: nothing new.
    stats2 = backfill_historical("VA")
    assert stats2["rows_new"] == 0
