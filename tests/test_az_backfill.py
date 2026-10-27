"""AZ Jul 2003 - 2007 backfill: AZ DES "Dislocated Worker Program" PDFs.

Fixtures are three of the pinned Wayback captures, unmodified:

* ``des_2003-09.pdf``: a monthly report with one multi-site notice (Chevron
  USA) whose later sites are address-only rows, three of them in Phoenix.
* ``des_2004-09.pdf``: stacked dates/counts in one row and a month-only
  "08/2004" layoff date.
* ``des_2007.pdf``: the 2007 annual file, with "Prior Layoffs" re-listings,
  NEW rows repeated month after month, and A rows duplicating W rows.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.states.az import (
    _ARCHIVE_PDFS,
    ARCHIVE_LAST_YEAR,
    _source_url,
    parse_az_archive_pdf,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "az"


def _parse(name: str, year: int):
    return parse_az_archive_pdf((_FIXTURES / name).read_bytes(), year)


def test_monthly_report_multisite_notice():
    rows = _parse("des_2003-09.pdf", 2003)
    assert {r.notice_date for r in rows} == {date(2003, 9, 1)}  # report month
    radio = rows[0]
    assert (radio.employer, radio.city, radio.layoff_count) == ("Radio Frequency", "Phoenix", 19)
    assert radio.effective_date == date(2003, 11, 19)
    chevron = {r.city: r.layoff_count for r in rows if r.employer == "Chevron USA"}
    # Address-only rows inherit the employer; same-city sites merge.
    assert chevron == {
        "Scottsdale": 8,
        "Phoenix": 22,
        "Apache Junction": 8,
        "Mesa": 33,
        "Gilbert": 9,
        "Tempe": 24,
    }
    assert sum(r.layoff_count or 0 for r in rows) == 123
    assert all(r.source_url.endswith("/wia/warn/September%202003.pdf") for r in rows)


def test_only_warn_typed_rows_and_stacked_values():
    rows = _parse("des_2004-09.pdf", 2004)
    assert len(rows) == 7  # the A rows (Belden, Alaska Airlines, ...) are skipped
    assert not [r for r in rows if r.employer.startswith(("Belden", "Alaska"))]
    imation = next(r for r in rows if r.employer == "Imation Corporation")
    assert imation.effective_date == date(2004, 8, 1)  # "08/2004 thru 12/31/2005"
    learjet = next(r for r in rows if r.employer.startswith("Bombardier"))
    assert learjet.layoff_count == 40  # "12 / 12 / 16" stacked in one row
    assert learjet.effective_date == date(2004, 10, 17)


def test_annual_file_drops_relistings():
    rows = _parse("des_2007.pdf", 2007)
    assert len(rows) == 99
    assert len({notice_id(r) for r in rows}) == 99
    # Watson Laboratories (Phoenix, 32) is printed in six months; kept once.
    watson = [r for r in rows if r.employer.startswith("Watson Laboratories")]
    assert len(watson) == 1
    # Qwest's January rows are "Prior Layoffs" carry-overs from 2006.
    assert not [r for r in rows if r.employer.startswith("Qwest")]
    months = Counter(r.notice_date.month for r in rows)
    assert set(months) <= set(range(1, 13)) and months[1] > 0


def test_year_filter_and_source_urls():
    assert _parse("des_2003-09.pdf", 2004) == []  # page month must match the year
    assert ARCHIVE_LAST_YEAR == 2007
    assert _source_url(2005, 5).endswith("/wia/warn/may2005.pdf")
    assert _source_url(2003, 7).endswith("/wia/warn/July%202003.pdf")
    assert _source_url(2007, 11).endswith("/warn_2007.pdf")
    assert sum(len(v) for v in _ARCHIVE_PDFS.values()) == 25


@pytest.mark.parametrize(("year", "archive"), [(2005, True), (2007, True), (2010, False)])
def test_backfill_spec_routes_by_year(year, archive, monkeypatch):
    from warn_v2.scripts import backfill_historical as bf

    calls = []
    monkeypatch.setattr(bf, "fetch_az_archive_year", lambda y: calls.append(("az", y)) or [])
    monkeypatch.setattr(bf, "_joblink_fetch", lambda s, y: calls.append(("joblink", y)) or b"")
    spec = bf._BACKFILL["AZ"]
    assert spec.year_start == 2003
    spec.fetch_year(None, year)
    assert calls == [("az" if archive else "joblink", year)]
