"""GA CICS-era backfill (PY1988 → Oct-2006) — WarnID Listing parser + union.

``ga_cics_archive.tar.gz`` bundles the latest Wayback capture of each of
GDOL's four WR01 forms (2006-10-09). Each page prints a "Total Number
Affected" line per program year, which pins the parser: every year's parsed
counts must sum to GDOL's own total.
"""
from __future__ import annotations

import re
from datetime import date

import pytest

from warn_v2.db.models import Notice
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.bundled import load_archive
from warn_v2.scrapers.states.ga import (
    _GA_CICS_ARCHIVE,
    GA_CICS_MEMBER,
    ga_cics_files,
    parse_ga_cics_archive,
    parse_ga_cics_captures,
)
from warn_v2.scripts.backfill_historical import backfill_historical

_TOTAL_RE = re.compile(
    r"Total Number Affected:(?:&nbsp;|\s)*07/01/(\d{2}).*?:(?:&nbsp;|\s)*([\d,]+)", re.S
)


@pytest.fixture(scope="module")
def rows():
    return parse_ga_cics_archive(ga_cics_files()[0][1])


def test_bundle_members() -> None:
    names = [n for n, _ in load_archive(_GA_CICS_ARCHIVE)]
    assert names == [
        "WR01A_20061009163412.html",
        "WR01B_20061009163433.html",
        "WR01C_20061009163448.html",
        "WR01D_20061009163511.html",
    ]
    assert ga_cics_files()[0][0] == GA_CICS_MEMBER


def test_row_counts_and_ids(rows) -> None:
    ids = [r.extra["ga_warn_id"] for r in rows if "ga_warn_id" in r.extra]
    assert len(ids) == len(set(ids)) == 2455  # the 2026-10 sweep's count
    assert len(rows) == 2455 + 19  # + the ID-less PY2006 current-year page
    years = {int(r.extra["program_year"]) for r in rows}
    assert years == set(range(1988, 2007))
    for r in rows:
        assert r.state == "GA" and r.employer
        if "ga_warn_id" in r.extra:
            assert r.extra["ga_warn_id"].startswith(r.extra["program_year"])


def test_program_year_totals_match_gdol(rows) -> None:
    """Every listed program year sums to the page's own printed total."""
    printed: dict[int, int] = {}
    for _name, raw in load_archive(_GA_CICS_ARCHIVE):
        for yy, total in _TOTAL_RE.findall(raw.decode("latin-1")):
            py = (1900 if int(yy) >= 50 else 2000) + int(yy)
            printed[py] = int(total.replace(",", ""))
    assert set(printed) == set(range(1988, 2007))
    parsed: dict[int, int] = {}
    for r in rows:
        py = int(r.extra["program_year"])
        parsed[py] = parsed.get(py, 0) + (r.layoff_count or 0)
    assert parsed == printed


def test_notice_date_is_event_date_clamped_to_program_year(rows) -> None:
    for r in rows:
        py = int(r.extra["program_year"])
        assert date(py, 7, 1) <= r.notice_date <= date(py + 1, 6, 30)
        if r.effective_date is None:
            assert r.notice_date == date(py, 7, 1)
        elif date(py, 7, 1) <= r.effective_date <= date(py + 1, 6, 30):
            assert r.notice_date == r.effective_date
    assert sum(r.effective_date is None for r in rows) == 3


def test_sample_rows(rows) -> None:
    by_id = {r.extra.get("ga_warn_id"): r for r in rows}
    # Verified in the sweep on WR01B @20051111185719; still listed in 2006-10.
    acuity = by_id["2004131C"]
    assert acuity.employer == "ACUITY LIGHTING"
    assert (acuity.city, acuity.county, acuity.layoff_count) == ("CONYERS", "ROCKDALE", 106)
    assert acuity.closure_type == "Closure"
    assert acuity.effective_date is None  # only a trade-cert date is listed
    assert acuity.notice_date == date(2004, 7, 1)
    assert acuity.extra["trade_cert_date"] == "2005-06-10"
    assert acuity.source_url == (
        "https://web.archive.org/web/20061009163433/"
        "http://www.dol.state.ga.us/WS4-MW5/cics.jsp?TRANSID=WR01&FRMNAME=WR01B"
    )
    # Event date before the program year → clamped to Jul 1.
    schnadig = by_id["2004037C"]
    assert schnadig.effective_date == date(2003, 12, 30)
    assert schnadig.notice_date == date(2004, 7, 1)
    # Event date after the program year → clamped to Jun 30.
    soft_sheen = by_id["2004126C"]
    assert soft_sheen.effective_date == date(2006, 3, 31)
    assert soft_sheen.notice_date == date(2005, 6, 30)
    # Retyped C → S between 2004 and 2006: the latest capture's type wins.
    assert "2004034C" not in by_id
    assert by_id["2004034S"].closure_type == "Substantial Layoff"
    # A reused sequence number is two distinct notices.
    assert by_id["2001219S"].employer == "AMERICAL/PED'S"
    assert by_id["2001219C"].employer == "DENNYS RESTAURANT"
    # N rows (< 100 employees) are kept.
    assert by_id["2004035N"].closure_type == "Non-Substantial Layoff"
    # "STATEWIDE" is not a city.
    census = by_id["2000006S"]
    assert census.city is None and census.layoff_count == 1600
    # The ID-less current-year page (PY2006).
    py2006 = [r for r in rows if r.extra["program_year"] == "2006"]
    assert len(py2006) == 19 and all("ga_warn_id" not in r.extra for r in py2006)
    swift = next(r for r in py2006 if r.employer == "SWIFT GALEY")
    assert (swift.layoff_count, swift.notice_date) == (800, date(2006, 10, 30))


def _page(header: str, *trs: str) -> bytes:
    rows = "".join(
        "<tr>" + "".join(f'<td class="smallblacktext">{c}</td>' for c in tr.split("|")) + "</tr>"
        for tr in trs
    )
    return (
        f'<table><tr><td class="blueboldheader">{header}</td></tr>{rows}</table>'
    ).encode()


def test_union_latest_capture_per_program_year_wins() -> None:
    older = _page(
        "07/01/04&nbsp;-&nbsp;06/30/05",
        "2004001C|ACME|MACON|BIBB|100|09/01/2004|&nbsp;",
        "2004002C|GONE INC|MACON|BIBB|50|10/01/2004|&nbsp;",
    )
    newer = _page(
        "07/01/04&nbsp;-&nbsp;06/30/05",
        "2004001S|ACME|MACON|BIBB|120|09/01/2004|&nbsp;",
    )
    other_year = _page(
        "07/01/03&nbsp;-&nbsp;06/30/04",
        "2003001N|BETA|ROME|FLOYD|20|&nbsp;|&nbsp;",
    )
    # Capture order in the list doesn't matter — the timestamp decides.
    rows = parse_ga_cics_captures([
        ("WR01B_20060101000000.html", newer),
        ("WR01B_20050101000000.html", older),
        ("WR01C_20050101000000.html", other_year),
    ])
    by_id = {r.extra["ga_warn_id"]: r for r in rows}
    assert set(by_id) == {"2004001S", "2003001N"}
    assert by_id["2004001S"].layoff_count == 120
    assert by_id["2003001N"].notice_date == date(2003, 7, 1)


def test_empty_newer_year_listing_keeps_older_rows() -> None:
    older = _page("07/01/06 - 09/04/06", "&nbsp;C|ACME|MACON|BIBB|100|09/01/2006|&nbsp;")
    empty = _page("07/01/06 - 07/20/06")
    rows = parse_ga_cics_captures([
        ("WR01A_20060905024640.html", older),
        ("WR01A_20061001000000.html", empty),
    ])
    assert [r.employer for r in rows] == ["ACME"]


def test_rejects_id_outside_its_program_year() -> None:
    page = _page("07/01/04 - 06/30/05", "2003001C|ACME|MACON|BIBB|100|09/01/2004|&nbsp;")
    with pytest.raises(ParseFailed):
        parse_ga_cics_captures([("WR01B_20060101000000.html", page)])


def test_rejects_unknown_member_name() -> None:
    with pytest.raises(ParseFailed):
        parse_ga_cics_captures([("WR03A_20060101000000.html", b"")])


@pytest.mark.slow  # ~3s: upserts ~2,500 rows
def test_backfill_historical_ga_inserts_cics_rows(db, rows) -> None:
    stats = backfill_historical("GA")
    # 31 bundled 2022 entry pages (their listing rows aren't in this empty
    # DB, so they insert too) + the CICS bundle as one member.
    assert stats["years_attempted"] == 32
    db.expire_all()
    cics = db.query(Notice).filter(
        Notice.state == "GA", Notice.notice_date < date(2007, 1, 1)
    )
    # 2,474 rows; notices sharing employer + date + city merge (counts summed).
    assert cics.count() == 2434
    assert sum(n.layoff_count or 0 for n in cics) == sum(r.layoff_count or 0 for r in rows)
