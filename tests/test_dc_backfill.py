"""DC 2002 - Jan 2012 backfill: the old CWP "Monthly WARN Notification Log".

Fixtures are two of the three pinned Wayback captures, unmodified:

* ``log_2012-05.html`` (20120514073024) is the latest version: 147 notices,
  2005-01 → 2012-01, with month-divider rows and month-only dates.
* ``log_2005-04.html`` (20050408160035) is an early version whose 2002-2003
  rows the later log dropped, and whose organization cells end in a "WARN"
  link label.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.dc import _LOG_CAPTURES, dc_log_urls, parse_dc_log

_FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "dc"


def _read(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def test_latest_log_capture() -> None:
    rows = parse_dc_log(_read("log_2012-05.html"), "u")
    assert len(rows) == 147
    years = Counter(r.notice_date.year for r in rows)
    assert min(years) == 2005 and max(years) == 2012
    assert years[2009] == 37
    first = rows[0]
    assert (first.employer, first.notice_date, first.layoff_count, first.closure_type) == (
        "DC Department of Health",
        date(2012, 1, 11),
        18,
        "Permanent Closures",
    )
    assert all(r.state == "DC" and r.source_url == "u" for r in rows)


def test_month_only_dates_become_first_of_month() -> None:
    rows = parse_dc_log(_read("log_2012-05.html"), "u")
    gsa = next(r for r in rows if r.employer == "US General Services Administration")
    assert gsa.notice_date == date(2008, 12, 1)  # printed "12/2008"
    assert gsa.effective_date == date(2008, 12, 18)


def test_early_capture_strips_warn_label_and_keeps_leading_counts() -> None:
    rows = parse_dc_log(_read("log_2005-04.html"), "u")
    assert len(rows) == 9
    assert not [r for r in rows if r.employer.endswith("WARN")]
    united = {r.notice_date: r.layoff_count for r in rows if r.employer == "United Airlines"}
    assert united == {
        date(2003, 3, 17): 94,
        date(2003, 1, 8): 8,  # "8 ALPA Employees"
        date(2002, 12, 30): None,  # "Unspecified Number"
    }


def test_pinned_captures_newest_first() -> None:
    assert _LOG_CAPTURES == ("20120514073024", "20051208073424", "20050408160035")
    urls = dc_log_urls()
    assert all(u.startswith("https://web.archive.org/web/") and "id_/" in u for u in urls)
    assert all(u.endswith("/does/cwp/view,a,1232,q,572897.asp") for u in urls)


def test_backfill_spec_routes_to_log_parser() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["DC"]
    assert spec.discover_urls is not None
    url = dc_log_urls()[0]
    rows = spec.parse_for_url(url)(_read("log_2012-05.html"))
    assert len(rows) == 147
    assert rows[0].source_url == url


def test_parse_failed_without_rows() -> None:
    with pytest.raises(ParseFailed):
        parse_dc_log(b"<html><table><tr><td>nothing</td></tr></table></html>", "u")


def test_footnoted_type_codes_map_by_digit() -> None:
    rows = parse_dc_log(_read("log_2012-05.html"), "u")
    assert {r.closure_type for r in rows} == {"Layoff", "Permanent Closures"}


def test_missing_cell_realigns_instead_of_eating_the_next_notice() -> None:
    # Record 1 lacks its effective-date cell; record 2 must still parse.
    cells = ["01/05/10", "Acme", "50", "1", "02/01/10", "Beta Corp", "60", "03/01/10", "2"]
    html = "<table><tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr></table>"
    rows = parse_dc_log(html.encode(), "u")
    assert [r.employer for r in rows] == ["Beta Corp"]
    assert rows[0].closure_type == "Permanent Closures"
