"""KY historical backfill (Mode 3b): the bundled 1998-2016 archive workbook.

The tar.gz under warn_v2/scrapers/data/ carries the Wayback capture
(20161222125836) of kcc.ky.gov's 'WARN Report 2016.xlsx' — one sheet per year,
'WARN 1998' ... 'WARN 2016'. These tests parse the committed archive itself,
so they pin exactly what a prod backfill Job would ingest.

Counts were cross-checked offline against an independent Wayback capture of
the same workbook from 2015-09-27 (WARNRecordByYear.xlsx): every overlapping
year 1998-2014 is row-for-row identical, and 2015 differs only by rows filed
after that capture date. The low-count years (2002-2007) are therefore real,
not parse loss.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime

import pytest

from warn_v2.scrapers.states.ky import (
    _repair_year_typo,
    ky_archive_files,
    parse_ky_workbook,
)

# Per-year row counts in the bundled workbook (keyed by notice_date year).
# The raw sheets hold 795 non-empty rows; 9 are unparseable and dropped —
# 7 have no 'Date Received' at all and two carry 'N/A' / 'November'.
_EXPECTED_YEAR_COUNTS = {
    1998: 11,
    1999: 48,
    2000: 51,
    2001: 71,
    2002: 9,
    2003: 3,
    2004: 50,
    2005: 6,
    2006: 9,
    2007: 11,
    2008: 68,
    2009: 89,
    2010: 40,
    2011: 31,
    2012: 77,
    2013: 63,
    2014: 37,
    2015: 74,
    2016: 38,
}


@pytest.fixture(scope="module")
def archive_rows():
    members = ky_archive_files()
    assert [name for name, _ in members] == ["WARN_Report_2016.xlsx"]
    return parse_ky_workbook(members[0][1])


def test_ky_archive_per_year_counts(archive_rows) -> None:
    per_year = Counter(r.notice_date.year for r in archive_rows)
    assert dict(per_year) == _EXPECTED_YEAR_COUNTS
    assert len(archive_rows) == 786
    assert all(r.state == "KY" for r in archive_rows)


def test_ky_archive_first_and_last_rows(archive_rows) -> None:
    first = archive_rows[0]  # top of the 'WARN 1998' sheet
    assert first.employer == "National-Standard Company"
    assert first.notice_date == date(1998, 11, 18)
    assert first.county == "Knox"
    assert first.layoff_count == 104
    assert first.closure_type == "Layoff"

    last = archive_rows[-1]  # bottom of the 'WARN 2016' sheet
    assert last.employer == "SKF USA Inc. Automotive Vehicle Service Market"
    assert last.notice_date == date(2016, 1, 11)
    assert last.county == "Boone"
    assert last.layoff_count == 179


def test_ky_archive_repairs_2106_year_typo(archive_rows) -> None:
    """The 2016 sheet holds one '2106-07-06' cell — a digit-transposed 2016.
    The row must survive with the repaired date, not be dropped."""
    repaired = [r for r in archive_rows if r.notice_date == date(2016, 7, 6)]
    assert len(repaired) == 1
    row = repaired[0]
    assert row.employer == "IPSCO Tubulars (Ky.) Inc."
    assert row.effective_date == date(2016, 8, 31)
    assert row.layoff_count == 1
    assert row.county == "Campbell"


def test_ky_archive_header_aliases(archive_rows) -> None:
    """Old sheets title columns 'Workforce Area'/'Local Area' (→ wda) and
    'Closure/Layoff' (→ closure_type); the alias map must carry them over."""
    hp = next(r for r in archive_rows if r.employer.startswith("Hewlett-Packard"))
    assert hp.notice_date == date(2000, 12, 14)  # 'Local Area' era
    assert hp.extra["wda"] == "Greater Louisville"
    assert hp.closure_type == "Layoff"
    assert hp.county == "Jefferson"


def test_repair_year_typo_only_fires_on_digit_transpositions() -> None:
    assert _repair_year_typo(datetime(2106, 7, 6), 2016) == date(2016, 7, 6)
    # Same year, different year digits, or non-datetime values: no repair.
    assert _repair_year_typo(datetime(2016, 7, 6), 2016) is None
    assert _repair_year_typo(datetime(2107, 7, 6), 2016) is None
    assert _repair_year_typo("2106-07-06", 2016) is None
    assert _repair_year_typo(None, 2016) is None


def test_ky_registry_uses_bundled_archive() -> None:
    """KY backfill is Mode 3b: bundled files parsed by parse_ky_workbook.
    (KY is deliberately absent from the shared fetch_year/discover_urls
    registry-shape test, like NY's bundled entry.)"""
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["KY"]
    assert spec.bundled_files is ky_archive_files
    assert spec.fetch_year is None
    assert spec.discover_urls is None
    assert spec.parse_for_url("WARN_Report_2016.xlsx") is parse_ky_workbook
