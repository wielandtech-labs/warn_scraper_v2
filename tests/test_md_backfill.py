"""MD 2000-2009 Wayback backfill (archive pages pruned from dllr.state.md.us).

Fixture: warn_v2/scrapers/fixtures/md/archive_warn2000.shtml — the real
Wayback capture of warn2000.shtml (ts 20160825213318) trimmed to the banner/
legend tables plus the header and first six data rows.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import respx

from warn_v2.scrapers.states.md import (
    MDScraper,
    _fetch_md_year,
    _md_date,
    _md_year_url,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "warn_v2" / "scrapers" / "fixtures" / "md"


def _fixture() -> bytes:
    return (_FIXTURES / "archive_warn2000.shtml").read_bytes()


def test_md_year_url_routes_2000s_to_wayback():
    assert _md_year_url(2000) == (
        "https://web.archive.org/web/20160825213318id_/"
        "https://www.dllr.state.md.us/employment/warn2000.shtml"
    )
    assert _md_year_url(2009).startswith("https://web.archive.org/web/20160825192612id_/")
    assert _md_year_url(2010) == "https://www.dllr.state.md.us/employment/warn2010.shtml"


@respx.mock
def test_md_fetch_year_wayback(monkeypatch):
    monkeypatch.setattr("warn_v2.scrapers.states.md._MD_WAYBACK_DELAY", 0)
    respx.get(
        "https://web.archive.org/web/20160825213318id_/"
        "https://www.dllr.state.md.us/employment/warn2000.shtml"
    ).mock(return_value=httpx.Response(200, content=_fixture()))
    assert _fetch_md_year(2000) == _fixture()


def test_md_parse_archive_2000_page():
    """Banner/legend tables are skipped; numeric type codes and bare-city
    Location cells parse; the SIC-era industry code lands in extra."""
    rows = MDScraper().parse(_fixture())
    assert len(rows) == 6

    first = rows[0]
    assert first.employer == "LONDON FOG"
    assert first.notice_date == date(2000, 1, 6)
    assert first.effective_date == date(2000, 1, 3)
    assert first.layoff_count == 95
    assert first.city == "ELDERSBURG"
    assert first.zip is None
    assert first.closure_type == "Mass Layoff"
    assert first.extra == {"sic_code": "2323"}

    closure = rows[1]
    assert closure.employer == "HARTZ & CO"
    assert closure.closure_type == "Plant Closure"

    # count total across the trimmed rows guards silent cell drift
    assert sum(r.layoff_count for r in rows) == 95 + 81 + 31 + 209 + 110 + 100


def test_md_date_repairs_three_digit_year():
    # real source typo on warn2003.shtml: '11/26/003' means 11/26/2003
    assert _md_date("11/26/003") == date(2003, 11, 26)
    assert _md_date("1/6/00") == date(2000, 1, 6)
    # ambiguous garbage stays dropped
    assert _md_date("5/2720/03") is None


def test_md_naics_kept_for_modern_years():
    html = (
        b"<table>"
        b"<tr><td>Notice Date</td><td>NAICS Code</td><td>Company</td>"
        b"<td>Location</td><td>WIA Code</td><td>Total Employees</td>"
        b"<td>Effective Date</td><td>Type Code</td></tr>"
        b"<tr><td>1/2/2007</td><td>3363</td><td>Collins &amp; Aikman</td>"
        b"<td>Havre de Grace</td><td>10</td><td>250</td><td>3/1/2007</td>"
        b"<td>1</td></tr>"
        b"</table>"
    )
    (row,) = MDScraper().parse(html)
    # 4-digit code in 2007 is a NAICS industry group, not SIC
    assert row.extra == {"naics": "3363"}
    assert row.city == "Havre de Grace"
    assert row.closure_type == "Plant Closure"


def test_md_multi_city_location_leaves_city_none():
    html = (
        b"<table>"
        b"<tr><td>Notice Date</td><td>NAICS Code</td><td>Company</td>"
        b"<td>Location</td><td>WIA Code</td><td>Total Employees</td>"
        b"<td>Effective Date</td><td>Type Code</td></tr>"
        b"<tr><td>3/6/2009</td><td>523110</td><td>RBC Capital Markets</td>"
        b"<td>Baltimore, Silver Spring &amp; White Marsh</td><td>13</td>"
        b"<td>39</td><td>5/8/2009</td><td>2</td></tr>"
        b"</table>"
    )
    (row,) = MDScraper().parse(html)
    assert row.city is None
    assert row.address == "Baltimore, Silver Spring & White Marsh"
