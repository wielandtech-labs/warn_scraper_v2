"""Tests for the CT historical backfill (1998-2018 Wayback archive pages).

Fixtures under ``fixtures/ct/archive/`` are real captured pages (warn2010 is
trimmed to its header, two plain rows, and the rowspan blocks):

* ``warn-0198.htm``          — monthly era, 1998 filename variant, 7 columns.
* ``warnreports2009-8.htm``  — monthly era, 2009 variant with Closing Y/N and
                               cp1252 smart-quote "Rec'd" artifacts.
* ``warn2010-trimmed.htm``   — yearly era with rowspan multi-batch/multi-town
                               notices (Electric Boat, Shaw's Supermarkets).
* ``warnreports2008-09.htm`` — a zero-notice month ("None received.").
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.states.ct import (
    _CT_ARCHIVE_CAPTURES,
    _discover_ct_archive_urls,
    parse_ct_archive,
)
from warn_v2.scripts import backfill_historical as bh

FIXTURES = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "ct"
    / "archive"
)


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---------------------------------------------------------------------------
# URL discovery (static pinned Wayback capture list)
# ---------------------------------------------------------------------------


def test_discover_urls_shape() -> None:
    urls = _discover_ct_archive_urls()
    assert len(urls) == 142
    assert len(set(urls)) == 142
    for u in urls:
        assert u.startswith("https://web.archive.org/web/")
        assert "id_/http://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports/" in u


def test_discover_urls_covers_both_eras_and_excludes_live_years() -> None:
    urls = "\n".join(_discover_ct_archive_urls())
    # Monthly-era filename variants, one per naming scheme.
    assert "warn-0198.htm" in urls
    assert "warn-99-01.htm" in urls
    assert "warn2000-01.htm" in urls
    assert "warnreports2005-02.htm" in urls
    # Yearly era.
    for year in (2010, 2011, 2012, 2014, 2015, 2016, 2017, 2018):
        assert f"warn{year}.htm" in urls
    # 2013 was never captured; 2019+ belong to the live Azure-blob route.
    assert "warn2013.htm" not in urls
    for year in range(2019, 2026):
        assert f"warn{year}.htm" not in urls
    # Jan 2005 was published under two filenames; only one is pinned.
    assert "warnreports2005-01.htm" in urls
    assert urls.count("2005-01") == 1


def test_capture_timestamps_are_wayback_style() -> None:
    for ts, tail in _CT_ARCHIVE_CAPTURES:
        assert ts.isdigit() and len(ts) == 14
        assert tail.endswith(".htm")


# ---------------------------------------------------------------------------
# Monthly era (1998 variant)
# ---------------------------------------------------------------------------


def test_parse_1998_monthly_page() -> None:
    rows = parse_ct_archive(_load("warn-0198.htm"), "warn-0198")
    assert len(rows) == 9
    first = rows[0]
    assert first.state == "CT"
    assert first.employer == "Allied Signal Aerospace"
    assert first.notice_date == date(1998, 1, 6)
    assert first.city == "Stratford"
    assert first.layoff_count == 3
    # Effective cell is "3/1398 to 3/27/98" — the typo'd first date is
    # unparseable, so the parser falls through to the range end.
    assert first.effective_date == date(1998, 3, 27)


def test_parse_1998_amended_notice_note() -> None:
    rows = parse_ct_archive(_load("warn-0198.htm"), "warn-0198")
    amended = [r for r in rows if r.extra.get("note")]
    assert len(amended) == 1
    assert amended[0].employer == "Allied Signal Aerospace"
    assert amended[0].notice_date == date(1998, 1, 7)
    assert "Amended Notice" in amended[0].extra["note"]


def test_parse_1998_glued_recd_date() -> None:
    rows = parse_ct_archive(_load("warn-0198.htm"), "warn-0198")
    norwich = next(r for r in rows if "Norwich Savings" in r.employer)
    # Cell reads "1/16/98 <br>Rec'd <br>1/20/98": WARN date wins, received kept.
    assert norwich.notice_date == date(1998, 1, 16)
    assert norwich.extra["received"] == "1998-01-20"
    assert norwich.employer == "Norwich Savings Society & People's Bank"


# ---------------------------------------------------------------------------
# Monthly era (2009 variant: Closing Y/N column, cp1252 artifacts)
# ---------------------------------------------------------------------------


def test_parse_2009_monthly_page() -> None:
    rows = parse_ct_archive(_load("warnreports2009-8.htm"), "warnreports2009-8")
    assert len(rows) == 5
    exxon = rows[0]
    # Word-split inline spans must not inject spaces mid-name.
    assert exxon.employer == "Station Operations Inc. d/b/a ExxonMobil CORS"
    assert exxon.notice_date == date(2009, 7, 30)
    assert exxon.extra["received"] == "2009-08-04"
    assert exxon.layoff_count == 268
    assert exxon.closure_type == "Closure"
    assert exxon.city is not None and exxon.city.startswith("Branford;")

    smurfit = rows[1]
    assert smurfit.employer == "Smurfit-Stone Container Corporation"

    # "10/12/09 <en dash> 12/31/09" in the source — first date wins.
    iseli = next(r for r in rows if "Iseli" in r.employer)
    assert iseli.effective_date == date(2009, 10, 12)

    # "8/09 - 12/09" has no parseable M/D/Y — kept verbatim.
    blakeslee = next(r for r in rows if "Blakeslee" in r.employer)
    assert blakeslee.effective_date is None
    assert blakeslee.extra["effective_raw"] == "8/09 - 12/09"
    assert blakeslee.closure_type == "Layoff"


# ---------------------------------------------------------------------------
# Yearly era (2010+: Date(s) of Layoffs, rowspan continuation rows)
# ---------------------------------------------------------------------------


def test_parse_yearly_page_basics() -> None:
    rows = parse_ct_archive(_load("warn2010-trimmed.htm"), "warn2010")
    stanadyne = rows[0]
    assert stanadyne.employer == "Stanadyne Corporation"
    assert stanadyne.notice_date == date(2010, 12, 21)
    assert stanadyne.extra["received"] == "2010-12-22"
    assert stanadyne.extra["note"] == "Update to 10/29/10 notice"
    assert stanadyne.layoff_count == 2
    assert stanadyne.effective_date == date(2011, 1, 15)
    assert stanadyne.closure_type == "Closure"


def test_parse_yearly_rowspan_batches() -> None:
    """A rowspan=8 notice (Electric Boat) yields one row per batch, each
    inheriting the spanned WARN date / employer / location cells."""
    rows = parse_ct_archive(_load("warn2010-trimmed.htm"), "warn2010")
    eb = [
        r
        for r in rows
        if r.employer == "Electric Boat" and r.notice_date == date(2010, 2, 26)
    ]
    assert len(eb) == 8
    assert {r.layoff_count for r in eb} == {39, 87, 10, 22, 140, 38, 72, 26}
    assert all(r.city == "Groton" for r in eb)
    # The "canceled" batch keeps its prose in extra and no effective date.
    canceled = next(r for r in eb if r.layoff_count == 39)
    assert canceled.effective_date is None
    assert canceled.extra["effective_raw"] == "canceled"


def test_parse_yearly_rowspan_towns() -> None:
    """A rowspan multi-town notice (Shaw's) yields one row per town."""
    rows = parse_ct_archive(_load("warn2010-trimmed.htm"), "warn2010")
    shaws = [r for r in rows if "Shaw" in r.employer]
    assert len(shaws) == 8
    cities = {r.city for r in shaws}
    assert "Clinton" in cities and "East Hartford" in cities
    assert len(cities) == 8
    assert all(r.notice_date == date(2010, 2, 12) for r in shaws)


# ---------------------------------------------------------------------------
# Edge pages and defensive behavior
# ---------------------------------------------------------------------------


def test_zero_notice_month_returns_empty() -> None:
    rows = parse_ct_archive(_load("warnreports2008-09.htm"), "warnreports2008-09")
    assert rows == []


def test_unrelated_html_raises_parsefailed() -> None:
    with pytest.raises(ParseFailed):
        parse_ct_archive(b"<html><body><p>The URL is invalid</p></body></html>", "x")


def test_exact_duplicate_rows_collapse() -> None:
    """Identical rows in one page collapse — storage's worksite merge would
    otherwise SUM their counts and double-count the notice."""
    page = """
    <table>
      <tr><td>WARN Date</td><td>Affected Company</td>
          <td>Location(s) of Layoffs</td><td>Number Affected</td>
          <td>Effective Date</td></tr>
      <tr><td>1/5/98</td><td>Acme Co.</td><td>Hartford</td><td>10</td>
          <td>2/1/98</td></tr>
      <tr><td>1/5/98</td><td>Acme Co.</td><td>Hartford</td><td>10</td>
          <td>2/1/98</td></tr>
    </table>
    """
    rows = parse_ct_archive(page.encode(), "dupes")
    assert len(rows) == 1


def test_dash_dates_and_free_text_counts() -> None:
    """1999 pages write dash dates ("8-11-99"); counts are free text."""
    page = """
    <table>
      <tr><td>WARN Date</td><td>Affected Company</td>
          <td>Location(s) of Layoffs</td><td>Number Affected</td>
          <td>Effective Date</td></tr>
      <tr><td>8-11-99 Rec'd 8-13-99</td><td>Dash Co.</td><td>Norwalk</td>
          <td>Approx. 100</td><td>Mid-1999</td></tr>
      <tr><td>9-1-99</td><td>Blank Co.</td><td>Norwich</td><td>?</td>
          <td>10-1-99</td></tr>
    </table>
    """
    rows = parse_ct_archive(page.encode(), "dash")
    assert len(rows) == 2
    dash = rows[0]
    assert dash.notice_date == date(1999, 8, 11)
    assert dash.extra["received"] == "1999-08-13"
    assert dash.layoff_count == 100
    assert dash.extra["layoff_count_raw"] == "Approx. 100"
    assert dash.effective_date is None
    assert dash.extra["effective_raw"] == "Mid-1999"
    blank = rows[1]
    assert blank.layoff_count is None
    assert blank.extra["layoff_count_raw"] == "?"
    assert blank.effective_date == date(1999, 10, 1)


def test_rows_without_date_or_employer_are_skipped() -> None:
    page = """
    <table>
      <tr><td>WARN Date</td><td>Affected Company</td>
          <td>Location(s) of Layoffs</td><td>Number Affected</td>
          <td>Effective Date</td></tr>
      <tr><td>TOTAL</td><td></td><td></td><td>1234</td><td></td></tr>
      <tr><td>1/5/98</td><td></td><td>Hartford</td><td>10</td><td></td></tr>
    </table>
    """
    assert parse_ct_archive(page.encode(), "furniture") == []


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


def test_backfill_registry_has_ct_spec() -> None:
    spec = bh._BACKFILL["CT"]
    assert spec.discover_urls is not None
    assert spec.parse_for_url is not None
    urls = spec.discover_urls()
    assert len(urls) == 142
    parse_fn = spec.parse_for_url(urls[0])
    assert parse_fn is not None
    rows = parse_fn(_load("warn-0198.htm"))
    assert len(rows) == 9
    # source_url must be the per-page replay URL, not the live source.
    assert rows[0].source_url == urls[0]
