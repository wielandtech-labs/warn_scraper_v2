"""Tests for the CA pre-2006 HTML era (2000-2005 Wayback slices).

Fixtures are real captures: one simple slice per format era (4-digit dates in
2000, the 2003 file that needs the Jul-2003 cutoff) and one detailed slice per
markup era (.htm 2003, .asp 2004).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.scrapers.states.ca import (
    _CA_HTML_DETAIL_RE,
    _CA_HTML_SIMPLE_RE,
    _CA_HTML_SLICES,
    ca_html_slice_urls,
    parse_ca_detail_html,
    parse_ca_simple_html,
)

_FIXTURES = Path(__file__).parent.parent / "warn_v2" / "scrapers" / "fixtures" / "ca"


def _fixture(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


def _replay(name: str) -> str:
    ts = _CA_HTML_SLICES[name]
    return f"https://web.archive.org/web/{ts}id_/http://www.edd.ca.gov/warn/{name}"


# ---------------------------------------------------------------------------
# Pinned capture list + dispatch
# ---------------------------------------------------------------------------

def test_slice_urls_are_pinned_replays():
    urls = ca_html_slice_urls()
    assert len(urls) == 29
    assert all(u.startswith("https://web.archive.org/web/") and "id_/" in u for u in urls)
    # Every pinned URL dispatches to exactly one of the two HTML parsers.
    for u in urls:
        assert bool(_CA_HTML_DETAIL_RE.search(u)) != bool(_CA_HTML_SIMPLE_RE.search(u))


def test_simple_re_scope():
    # Simple pages are ingested for 2000-2003 only (2004/2005 are superseded
    # by the detailed files; EDD's cnal04.asp actually serves 2005 content).
    assert _CA_HTML_SIMPLE_RE.search("http://x/eddwarncnal02.htm")
    assert not _CA_HTML_SIMPLE_RE.search("http://x/eddwarncnal04.asp")
    # The PDF-era regex must not swallow the HTML names and vice versa.
    assert not _CA_HTML_DETAIL_RE.search("http://x/eddwarncnda06.pdf")


# ---------------------------------------------------------------------------
# Simple format (2000-2003)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def simple_2000():
    return parse_ca_simple_html(_fixture("eddwarncnal00.htm"), _replay("eddwarncnal00.htm"))


def test_simple_2000_rows(simple_2000):
    assert len(simple_2000) == 225
    first = simple_2000[0]
    assert first.employer == "AAVID Thermal Technologies, Inc."
    assert first.city == "Santa Ana"
    assert first.layoff_count == 68
    # No received date in this format — notice_date is the layoff date (proxy).
    assert first.effective_date == date(2000, 4, 1)
    assert first.notice_date == first.effective_date
    assert first.source_url == _replay("eddwarncnal00.htm")
    assert all(r.effective_date.year == 2000 for r in simple_2000)


def test_simple_2003_applies_july_cutoff():
    rows = parse_ca_simple_html(_fixture("eddwarncnal03.htm"), _replay("eddwarncnal03.htm"))
    assert len(rows) == 234
    assert all(r.effective_date < date(2003, 7, 1) for r in rows)
    # Without the 2003 URL the cutoff must not apply (H2 rows kept).
    uncut = parse_ca_simple_html(_fixture("eddwarncnal03.htm"))
    assert len(uncut) > len(rows)
    assert any(r.effective_date >= date(2003, 7, 1) for r in uncut)


# ---------------------------------------------------------------------------
# Detailed format (2003-2005) — the HTML twin of parse_ca_detail_pdf
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def detail_2003():
    return parse_ca_detail_html(_fixture("eddwarncndab03.htm"), _replay("eddwarncndab03.htm"))


@pytest.fixture(scope="module")
def detail_2004():
    return parse_ca_detail_html(_fixture("eddwarncndab04.asp"), _replay("eddwarncndab04.asp"))


def test_detail_2003_htm_era(detail_2003):
    assert len(detail_2003) == 34
    addus = next(r for r in detail_2003 if r.employer == "Addus HealthCare")
    assert addus.notice_date == date(2003, 8, 6)  # Date Notice Received
    assert addus.effective_date == date(2003, 9, 18)
    assert addus.layoff_count == 75
    assert addus.closure_type == "Layoff"
    assert addus.address == "21 South California Street, Suite 210, Ventura, CA 93001"
    assert addus.city == "Ventura"
    assert addus.zip == "93001"
    # The format debuted mid-2003: this file is Jul-Dec only.
    assert all(r.effective_date >= date(2003, 7, 1) for r in detail_2003 if r.effective_date)


def test_detail_2004_asp_era(detail_2004):
    assert len(detail_2004) == 70
    aai = next(r for r in detail_2004 if r.employer.startswith("AAI ACL"))
    assert aai.notice_date == date(2004, 10, 1)
    assert aai.effective_date == date(2004, 12, 3)
    assert aai.layoff_count == 31
    assert aai.closure_type == "Closure"
    assert aai.city == "Brea"
    assert aai.zip == "92821"


def test_detail_rows_all_carry_received_date_and_zip(detail_2003, detail_2004):
    for rows in (detail_2003, detail_2004):
        assert all(r.notice_date is not None for r in rows)
        assert all(r.zip is not None for r in rows)
        assert all(r.closure_type in ("Layoff", "Closure", None) for r in rows)


# ---------------------------------------------------------------------------
# Registry dispatch
# ---------------------------------------------------------------------------

def test_backfill_spec_routes_html_slices():
    from warn_v2.scripts.backfill_historical import _BACKFILL

    spec = _BACKFILL["CA"]
    detail_fn = spec.parse_for_url(_replay("eddwarncndab04.asp"))
    simple_fn = spec.parse_for_url(_replay("eddwarncnal00.htm"))
    rows = detail_fn(_fixture("eddwarncndab04.asp"))
    assert len(rows) == 70
    assert rows[0].source_url == _replay("eddwarncndab04.asp")
    rows = simple_fn(_fixture("eddwarncnal00.htm"))
    assert len(rows) == 225
    assert rows[0].source_url == _replay("eddwarncnal00.htm")
