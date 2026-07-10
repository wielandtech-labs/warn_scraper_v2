"""MI historical archive parsers (milmi.org via Wayback, 2000-2024).

Fixtures are the real Wayback payloads: the /warn/archive page capture
(2016-2024 year tables) and three annual PDFs picked to cover every parser
edge — warn2001 (numeric incident codes, source-truncated company names
glued into the city column, rescinded 0-count rows), warn2007 (the
sub-point top-jitter that splits a row's date/count onto their own line,
and a two-worksite filing), warn2010 (plain text-type era).

Every PDF test asserts the parsed count sum against the report's own
printed "Total Layoffs" figure — a row-count check alone misses a silently
dropped or misparsed count.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.states.mi import (
    _discover_mi_archive_urls,
    parse_mi_archive_html,
    parse_mi_archive_pdf,
)

_FIXTURES = (
    Path(__file__).resolve().parent.parent
    / "warn_v2" / "scrapers" / "fixtures" / "mi" / "archive"
)


def _pdf_rows(name: str):
    return parse_mi_archive_pdf((_FIXTURES / name).read_bytes(), name)


# ---------------------------------------------------------------------------
# HTML archive page (2016-2024 year tables)
# ---------------------------------------------------------------------------

def test_html_parses_all_year_tables() -> None:
    rows = parse_mi_archive_html((_FIXTURES / "archive.html").read_bytes(), "test")
    years = Counter(r.notice_date.year for r in rows)
    assert len(rows) == 676
    assert years == {
        2016: 41, 2017: 55, 2018: 60, 2019: 66, 2020: 252,
        2021: 14, 2022: 35, 2023: 68, 2024: 85,
    }


def test_html_first_row_fields() -> None:
    rows = parse_mi_archive_html((_FIXTURES / "archive.html").read_bytes(), "test")
    first = rows[0]
    assert first.state == "MI"
    assert first.employer == "GDI Services"
    assert first.city == "Caledonia"
    assert first.notice_date == date(2024, 1, 5)
    assert first.layoff_count == 114
    assert first.closure_type == "Layoff"
    assert first.source_url == "test"


def test_html_drops_total_and_summary_rows() -> None:
    rows = parse_mi_archive_html((_FIXTURES / "archive.html").read_bytes(), "test")
    assert not [r for r in rows if "total" in r.employer.lower()]
    # the YTD summary tables ("Number of notices received ...") never leak
    assert not [r for r in rows if r.employer.startswith("Number of")]


# ---------------------------------------------------------------------------
# Annual PDFs (2000-2015)
# ---------------------------------------------------------------------------

def test_pdf_2010_text_type_era() -> None:
    rows = _pdf_rows("warn2010.pdf")
    assert len(rows) == 49
    assert sum(r.layoff_count or 0 for r in rows) == 5_502  # printed total
    assert all(r.notice_date.year == 2010 for r in rows)
    first = rows[0]
    assert first.employer == "Macy's"
    assert first.city == "Waterford"
    assert first.notice_date == date(2010, 1, 6)
    assert first.closure_type == "Plant Closing"
    assert first.layoff_count == 130


def test_pdf_2001_incident_code_era() -> None:
    rows = _pdf_rows("warn2001.pdf")
    assert len(rows) == 141
    assert sum(r.layoff_count or 0 for r in rows) == 19_091  # printed total
    inc = Counter(r.closure_type for r in rows)
    assert inc["Facility Closure"] == 86
    assert inc["Layoff Event"] == 53
    # codes outside the printed legend are kept verbatim, not guessed
    assert inc["3"] == 1 and inc["4"] == 1


def test_pdf_2001_rescinded_rows_keep_zero_count() -> None:
    # The reports' footnote: rescinded incidents stay listed with 0 layoffs.
    rows = _pdf_rows("warn2001.pdf")
    zeros = [r for r in rows if r.layoff_count == 0]
    assert len(zeros) == 8


def test_pdf_2001_glued_company_city_recovered() -> None:
    # The source truncates long company names at the column edge and the
    # glyphs run into the city with no whitespace; the char-split recovers
    # the city ("General Motors Nao Orion AsseOrion" -> city "Orion").
    rows = _pdf_rows("warn2001.pdf")
    gm = next(r for r in rows if r.employer.startswith("General Motors Nao"))
    assert gm.city == "Orion"
    ryder = next(r for r in rows if r.employer.startswith("Ryder Integrated"))
    assert ryder.city == "Detroit"


def test_pdf_2007_jitter_and_multi_worksite() -> None:
    rows = _pdf_rows("warn2007.pdf")
    assert len(rows) == 111
    # warn2007's Synergis Kentwood row prints its date and count ~1pt below
    # the rest of the line; without jitter-tolerant clustering the count sum
    # comes up exactly 25 short of the printed total.
    assert sum(r.layoff_count or 0 for r in rows) == 22_299  # printed total
    synergis = sorted(
        (r for r in rows if r.employer == "Synergis Technologies Group"),
        key=lambda r: r.city or "",
    )
    assert [(r.city, r.layoff_count) for r in synergis] == [
        ("Grand Rapids", 60),
        ("Kentwood", 25),
    ]
    assert all(r.closure_type in ("Plant Closing", "Mass Layoff") for r in rows)


# ---------------------------------------------------------------------------
# Backfill wiring
# ---------------------------------------------------------------------------

def test_discovery_is_static_17_urls() -> None:
    urls = _discover_mi_archive_urls()
    assert len(urls) == 17
    assert urls[0].endswith(
        "?fbclid=IwAR1_xJ4VsYjaBCqzC3LaK38eCwK6R49zTwUnaRlgB3qZmg3vq5ajCf9QANM"
    )
    pdfs = [u for u in urls if u.endswith(".pdf")]
    assert len(pdfs) == 16
    assert pdfs[0].endswith("warn2000.pdf") and pdfs[-1].endswith("warn2015.pdf")
    assert all(u.startswith("https://web.archive.org/web/") for u in urls)


def test_backfill_spec_dispatch() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["MI"]
    assert spec.discover_urls is not None
    pdf_fn = spec.parse_for_url("https://web.archive.org/x/warn2001.pdf")
    html_fn = spec.parse_for_url("https://web.archive.org/x/warn/archive?f=1")
    rows = pdf_fn((_FIXTURES / "warn2001.pdf").read_bytes())
    assert len(rows) == 141
    assert rows[0].source_url == "https://web.archive.org/x/warn2001.pdf"
    hrows = html_fn((_FIXTURES / "archive.html").read_bytes())
    assert len(hrows) == 676


def test_html_parse_failed_when_no_year_tables() -> None:
    from warn_v2.scrapers.base import ParseFailed

    with pytest.raises(ParseFailed):
        parse_mi_archive_html(b"<html><body><p>nope</p></body></html>", "x")
