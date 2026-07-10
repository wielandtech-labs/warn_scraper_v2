"""IN historical backfill (DWD listing pages 2000-2007 via Wayback).

Fixtures are real Wayback payloads, one per page generation:

* ``gen1_2000.html`` — per-year table (2000.html, captured 2004-10). SIC
  codes, W-CL/W-LO notice types, and the malformed ``<th ...></TD>`` header
  markup shared by gen1/gen2.
* ``gen2_notices_200410.html`` — rolling notices.html (captured 2004-10),
  the sole source for Jan-Oct 2004.
* ``gen3_warn_notices_200709_trimmed.html`` — the Sep-2007 capture of the
  accumulating warn_notices.html, trimmed to the Sep-Jul 2007 head and the
  Feb-Jan 2005 tail (whole month sections cut in between). Covers the
  NAICS-era 8-column layout, footnote rows, employer "*" markers, and
  staged-layoff wave rows.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.in_ import (
    _archive_closure_type,
    _discover_in_archive_urls,
    parse_in_archive_html,
)

_FIXTURES = (
    Path(__file__).resolve().parent.parent
    / "warn_v2" / "scrapers" / "fixtures" / "in"
)


def _rows(name: str):
    return parse_in_archive_html((_FIXTURES / name).read_bytes(), name)


# ---------------------------------------------------------------------------
# gen1 — per-year tables (2000-2003, SIC era)
# ---------------------------------------------------------------------------

def test_gen1_2000_parses_all_rows() -> None:
    rows = _rows("gen1_2000.html")
    # The archived 2000 page only lists Nov-Dec 2000 (a documented gap).
    assert len(rows) == 14
    assert all(r.notice_date.year == 2000 for r in rows)
    assert {r.notice_date.month for r in rows} == {11, 12}
    # Four same-day Ames closures in different cities stay distinct.
    assert len({notice_id(r) for r in rows}) == 14


def test_gen1_first_row_fields() -> None:
    first = _rows("gen1_2000.html")[0]
    assert first.state == "IN"
    assert first.employer == "FFI Corporation"
    assert first.city == "Indianapolis"
    assert first.notice_date == date(2000, 12, 27)
    assert first.effective_date == date(2001, 2, 25)
    assert first.layoff_count == 109
    assert first.closure_type == "Closure"
    assert first.extra == {"sic_code": "3564", "industry": "Blowers & fans"}
    assert first.source_url == "gen1_2000.html"


# ---------------------------------------------------------------------------
# gen2 — rolling notices.html (2003-2004)
# ---------------------------------------------------------------------------

def test_gen2_2004_capture() -> None:
    rows = _rows("gen2_notices_200410.html")
    assert len(rows) == 45
    assert all(r.notice_date.year == 2004 for r in rows)
    # The Oct-2004 capture covers Jan-Oct (Nov-Dec 2004 is a documented gap).
    assert {r.notice_date.month for r in rows} == set(range(1, 11))
    # Still the SIC era: no 5/6-digit codes on this page.
    assert all("naics" not in r.extra for r in rows)
    assert sum(1 for r in rows if "sic_code" in r.extra) == 45
    assert rows[0].employer == "Evansville Veneer"
    assert rows[0].notice_date == date(2004, 10, 12)


# ---------------------------------------------------------------------------
# gen3 — accumulating warn_notices.html (2005-2007, SIC-or-NAICS era)
# ---------------------------------------------------------------------------

def test_gen3_trimmed_capture() -> None:
    rows = _rows("gen3_warn_notices_200709_trimmed.html")
    assert len(rows) == 41
    years = Counter(r.notice_date.year for r in rows)
    assert years == {2004: 1, 2005: 18, 2007: 22}
    # Mixed code era: 2007 rows carry NAICS, early-2005 rows carry SIC.
    assert sum(1 for r in rows if "naics" in r.extra) == 22
    assert sum(1 for r in rows if "sic_code" in r.extra) == 19


def test_gen3_footnote_marker_stripped_and_footnote_rows_skipped() -> None:
    rows = _rows("gen3_warn_notices_200709_trimmed.html")
    first = rows[0]
    # Rendered as "Visteon Connersville * " with a "*Notice of layoff for one
    # employee..." footnote row after it.
    assert first.employer == "Visteon Connersville"
    assert first.notice_date == date(2007, 9, 18)
    assert first.layoff_count == 1
    assert first.closure_type == "Layoff/Closure"
    assert first.extra["naics"] == "336391"
    assert not [r for r in rows if "*" in r.employer]
    assert not [r for r in rows if "notice of layoff" in r.employer.lower()]


def test_gen3_staged_layoff_waves_parse_as_separate_rows() -> None:
    # INTEC Group filed one notice executed in three waves; the page lists a
    # row per wave (same employer/city/notice date, differing count and
    # effective date). All three parse; notice_id later collapses them.
    rows = _rows("gen3_warn_notices_200709_trimmed.html")
    intec = [r for r in rows if r.employer == "INTEC Group"]
    assert [(r.layoff_count, r.effective_date) for r in intec] == [
        (99, date(2007, 10, 1)),
        (44, date(2007, 11, 1)),
        (27, date(2007, 12, 1)),
    ]
    assert len({notice_id(r) for r in intec}) == 1


# ---------------------------------------------------------------------------
# closure-type normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("W-CL", "Closure"),
        ("W/CL", "Closure"),
        ("PA-CL", "Closure"),
        ("W-LO", "Layoff"),
        ("W/LO", "Layoff"),
        ("W-PermLO", "Layoff"),
        ("W-Temp. LO", "Layoff"),
        ("W-LO-CL", "Layoff/Closure"),
        ("LO/CL", "Layoff/Closure"),
        ("CL-LO", "Layoff/Closure"),
        ("W-L-CL", "Layoff/Closure"),
        ("", None),
        ("XYZ", "XYZ"),
    ],
)
def test_archive_closure_type(raw: str, expected: str | None) -> None:
    assert _archive_closure_type(raw) == expected


# ---------------------------------------------------------------------------
# Backfill wiring
# ---------------------------------------------------------------------------

def test_discovery_is_static_7_pinned_replay_urls() -> None:
    urls = _discover_in_archive_urls()
    assert len(urls) == 7
    assert all(u.startswith("https://web.archive.org/web/") for u in urls)
    assert all("id_/http://www.in.gov/dwd/" in u for u in urls)
    # 4 per-year pages, 2 rolling captures, 1 accumulating capture.
    assert sum(1 for u in urls if "/workforce_stats/warn/2" in u) == 4
    assert sum(1 for u in urls if u.endswith("/notices.html")) == 2
    assert sum(1 for u in urls if u.endswith("/employers/warn_notices.html")) == 1


def test_backfill_spec_dispatch() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["IN"]
    assert spec.discover_urls is not None
    url = "https://web.archive.org/web/20041024235304id_/x.html"
    parse_fn = spec.parse_for_url(url)
    rows = parse_fn((_FIXTURES / "gen1_2000.html").read_bytes())
    assert len(rows) == 14
    assert rows[0].source_url == url


def test_parse_failed_on_page_without_data_rows() -> None:
    with pytest.raises(ParseFailed):
        parse_in_archive_html(b"<html><body><p>nope</p></body></html>", "x")
