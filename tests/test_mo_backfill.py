"""MO historical backfill parsers (jobs.mo.gov via Wayback, Jul 2012 - Dec 2018).

Fixtures are trimmed from the real Wayback payloads:

* ``archive_log_2012_2015_excerpt.pdf`` — pages 1, 13, 14 and 17 of the
  17-page consolidated Jul2012-Jun2015 log, picked to cover every layout
  edge: the merged-cell pages pdfplumber reports as 24 physical columns,
  the one clean 8-column page (p13), an amended notice stacking four
  received dates in one cell (Dallas Airmotive, p14), and the final page
  with its "PY 2014 Total YTD" footer.
* ``archive_log_py2015.pdf`` — the whole (tiny) PY2015 log capture.
* ``archive_py2016.html`` / ``py2017`` / ``py2018`` — the PY-page captures
  with scripts/styles stripped, tables intact. The PY2016 capture is the
  Spanish-path URL carrying the English table; the PY2018 capture runs into
  early 2019 and exercises the >= 2019-01-01 cutoff (the regular scraper
  owns 2019+).

PDF/HTML tests assert the layoff-count sum against the source's own printed
Total where one exists — a row-count check alone misses a silently dropped
or misparsed count. (PY2016's printed 1867 exceeds the numeric cell sum by
82: the page's one "Unknown"-count row is evidently included in the
agency's total, so 1785 is the faithful numeric sum.)
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.mo import (
    _discover_mo_archive_urls,
    parse_mo_archive_html,
    parse_mo_log_pdf,
)

_FIXTURES = (
    Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "mo"
)


def _read(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# Consolidated log PDF (Jul 2012 - Jun 2015)
# ---------------------------------------------------------------------------

def test_log_pdf_excerpt_counts() -> None:
    rows = parse_mo_log_pdf(_read("archive_log_2012_2015_excerpt.pdf"), "test")
    assert len(rows) == 41
    years = Counter(r.notice_date.year for r in rows)
    assert years == {2012: 11, 2014: 19, 2015: 11}
    assert sum(r.layoff_count or 0 for r in rows) == 4_909


def test_log_pdf_first_row_fields() -> None:
    rows = parse_mo_log_pdf(_read("archive_log_2012_2015_excerpt.pdf"), "test")
    first = rows[0]
    assert first.state == "MO"
    assert first.employer == "CEVA Logistics"
    assert first.notice_date == date(2012, 7, 16)
    assert first.effective_date == date(2012, 9, 15)
    assert first.layoff_count == 116
    assert first.closure_type == "Layoff"
    assert first.city == "Kansas City"
    assert first.county == "Clay"
    assert first.source_url == "test"


def test_log_pdf_amended_notice_takes_first_received_date() -> None:
    # Dallas Airmotive's cell stacks "9/26/2014; 11/18/14; 2/24/15; 4/16/15" —
    # the first is the original filing.
    rows = parse_mo_log_pdf(_read("archive_log_2012_2015_excerpt.pdf"), "test")
    dallas = next(r for r in rows if "Dallas Airmotive" in r.employer)
    assert dallas.notice_date == date(2014, 9, 26)
    assert dallas.effective_date == date(2014, 11, 9)  # first of the range list
    assert dallas.layoff_count == 68


def test_log_pdf_wrapped_cells_collapse_to_one_line() -> None:
    # Multi-line company / location cells keep their content on one line.
    rows = parse_mo_log_pdf(_read("archive_log_2012_2015_excerpt.pdf"), "test")
    anthem = next(r for r in rows if r.employer == "Anthem College")
    assert anthem.city == "Fenton / Maryland Heights / Kansas City"
    morrison = next(r for r in rows if r.employer.startswith("Morrison"))
    assert morrison.employer == "Morrison Healthcare at Saint Louis University Hospital"


def test_log_pdf_drops_totals_and_unknown_counts() -> None:
    rows = parse_mo_log_pdf(_read("archive_log_2012_2015_excerpt.pdf"), "test")
    # The "PY 2014 Total YTD" / "Program Year Total" footers have no received
    # date and never become rows.
    assert not [r for r in rows if "total" in r.employer.lower()]
    # "unknown" counts parse to None, not 0-or-garbage.
    unknowns = [r for r in rows if r.layoff_count is None]
    assert len(unknowns) == 2


def test_py2015_log_pdf() -> None:
    rows = parse_mo_log_pdf(_read("archive_log_py2015.pdf"), "test")
    assert len(rows) == 6
    assert sum(r.layoff_count or 0 for r in rows) == 594  # printed Total
    assert {r.notice_date.year for r in rows} == {2015}
    novolex = rows[0]
    assert novolex.employer == "Novolex"
    assert novolex.notice_date == date(2015, 9, 1)
    assert novolex.city == "Overland"
    # The one "Unknown"-count row keeps None.
    liberty = next(r for r in rows if r.employer.startswith("Liberty Terrace"))
    assert liberty.layoff_count is None


def test_log_pdf_parse_failed_on_garbage() -> None:
    with pytest.raises(ParseFailed):
        parse_mo_log_pdf(_read("archive_log_2012_2015_excerpt.pdf")[:1], "x")


# ---------------------------------------------------------------------------
# PY-page HTML captures (PY2016-PY2018)
# ---------------------------------------------------------------------------

def test_py2016_html() -> None:
    rows = parse_mo_archive_html(_read("archive_py2016.html"), "test")
    assert len(rows) == 31
    years = Counter(r.notice_date.year for r in rows)
    assert years == {2016: 17, 2017: 14}
    assert sum(r.layoff_count or 0 for r in rows) == 1_785
    first = rows[0]
    assert first.employer == "ConAgra Foods, Inc."
    assert first.notice_date == date(2016, 7, 18)
    assert first.effective_date == date(2016, 9, 30)
    assert first.layoff_count == 69
    assert first.closure_type == "Closing"
    assert first.city == "St. Louis"
    assert first.county == "St. Louis County"
    assert first.source_url == "test"


def test_py2017_html() -> None:
    rows = parse_mo_archive_html(_read("archive_py2017.html"), "test")
    assert len(rows) == 13
    assert sum(r.layoff_count or 0 for r in rows) == 1_441  # printed TOTAL
    assert {r.notice_date.year for r in rows} == {2017}


def test_py2018_html_drops_2019_rows() -> None:
    # The capture holds 18 data rows, 4 of them received in Jan 2019 — the
    # regular scraper owns 2019+, so the cutoff keeps only the 14 2018 rows.
    rows = parse_mo_archive_html(_read("archive_py2018.html"), "test")
    assert len(rows) == 14
    assert max(r.notice_date for r in rows) == date(2018, 12, 20)
    assert all(r.notice_date < date(2019, 1, 1) for r in rows)
    # printed TOTAL 2808 minus the four dropped 2019 rows (81+144+254+131)
    assert sum(r.layoff_count or 0 for r in rows) == 2_198


def test_html_total_footer_never_leaks() -> None:
    for name in ("archive_py2016.html", "archive_py2017.html", "archive_py2018.html"):
        rows = parse_mo_archive_html(_read(name), "test")
        assert not [r for r in rows if "total" in r.employer.lower()]


def test_html_parse_failed_when_no_warn_table() -> None:
    with pytest.raises(ParseFailed):
        parse_mo_archive_html(b"<html><body><table><tr><td>x</td></tr></table></body></html>", "x")


# ---------------------------------------------------------------------------
# Backfill wiring
# ---------------------------------------------------------------------------

def test_discovery_is_static_5_urls() -> None:
    urls = _discover_mo_archive_urls()
    assert len(urls) == 5
    assert all(u.startswith("https://web.archive.org/web/") and "id_/" in u for u in urls)
    pdfs = [u for u in urls if u.endswith(".pdf")]
    assert len(pdfs) == 2
    assert pdfs[0].endswith("warn_log_jul2012_to_present_2015-07-01.pdf")
    assert pdfs[1].endswith("warn-log-py2015.pdf")
    # the 2015-09-12 warn-log-2016.pdf capture is a strict subset of the
    # py2015 capture and stays out of the list
    assert not [u for u in urls if "warn-log-2016" in u]


def test_backfill_spec_dispatch() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["MO"]
    assert spec.discover_urls is not None
    pdf_fn = spec.parse_for_url("https://web.archive.org/x/warn-log-py2015.pdf")
    html_fn = spec.parse_for_url("https://web.archive.org/x/es/warn2016")
    rows = pdf_fn(_read("archive_log_py2015.pdf"))
    assert len(rows) == 6
    assert rows[0].source_url == "https://web.archive.org/x/warn-log-py2015.pdf"
    hrows = html_fn(_read("archive_py2016.html"))
    assert len(hrows) == 31
    assert hrows[0].source_url == "https://web.archive.org/x/es/warn2016"
