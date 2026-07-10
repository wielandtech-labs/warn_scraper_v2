"""GA 2022 bundled backfill (Mode 3b) — entry-page parser + hash alignment.

The bundled ``ga_archive.tar.gz`` holds the 31 GA2022* TCSG entry detail
pages plus the GravityView listing JSON captured 2026-07-10. Prod already
holds these notices at listing granularity (employer, notice_date = the
listing's Submitted Date, layoff_count, city/zip = None), so the parsed rows
must hash to the *same* ``notice_id`` — the whole point of the backfill is
COALESCE-filling county/address/closure_type/effective_date, not inserting.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pytest

from warn_v2.db.models import Notice
from warn_v2.pipeline.dedup import notice_id
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.bundled import load_archive
from warn_v2.scrapers.states.ga import (
    _GA_ARCHIVE,
    _LISTING_MEMBER,
    GAScraper,
    _listing_index,
    ga_archive_files,
    parse_ga_entry_page,
)
from warn_v2.scripts.backfill_historical import backfill_historical

ENTRY_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "ga"
    / "entry_sample.html"
)

_MEMBER_RE = re.compile(r"^entry_(\d+)_(GA\d+)\.html$")


def _listing_rows_for_bundled_entries() -> dict[str, NoticeRow]:
    """GA WARN ID → the row GAScraper.parse would store from the live listing.

    Rebuilds the public DataTables view from the bundled listing JSON (cells
    hold the raw HTML the table renders, entities included) and runs the
    *live* parser over it — the strongest offline stand-in for what prod
    actually stored.
    """
    index = _listing_index()
    bundled_ids = {_MEMBER_RE.match(n).group(2) for n, _ in ga_archive_files()}

    raw = next(b for n, b in load_archive(_GA_ARCHIVE) if n == _LISTING_MEMBER)
    html = [
        "<table><tr><th>GA WARN ID</th><th>Company Name</th>"
        "<th>Submitted Date</th><th>Total Number of Affected Employees</th></tr>"
    ]
    for row in json.loads(raw)["data"]:
        cells = [row[str(i)] for i in range(5)] if isinstance(row, dict) else row[:5]
        anchor, company, date_created, count, _entry_id = cells
        ga_id = re.sub(r"<[^>]+>", "", anchor).strip()
        if ga_id not in bundled_ids:
            continue
        html.append(
            f"<tr><td>{anchor}</td><td>{company}</td>"
            f"<td>{date_created}</td><td>{count}</td></tr>"
        )
    html.append("</table>")

    rows = GAScraper().parse("".join(html).encode())
    assert len(rows) == len(bundled_ids) == 31
    # Key by entry URL — the only per-row identifier the live parser carries.
    by_url = {r.raw_notice_url: r for r in rows}
    return {
        ga_id: by_url[index[ga_id].entry_url]
        for ga_id in bundled_ids
    }


# ---------------------------------------------------------------------------
# Archive + parser
# ---------------------------------------------------------------------------

def test_archive_members() -> None:
    members = ga_archive_files()
    assert len(members) == 31
    ids = []
    for name, raw in members:
        m = _MEMBER_RE.match(name)
        assert m, f"unexpected member name {name!r}"
        ids.append(m.group(2))
        assert raw[:100].lstrip().startswith(b"<!DOCTYPE html")
    # GA202200071..103, minus the two pruned at the source (083, 097).
    expected = {
        f"GA2022{n:05d}" for n in range(71, 104) if n not in (83, 97)
    }
    assert set(ids) == expected


def test_listing_index_covers_bundled_entries() -> None:
    index = _listing_index()
    assert len(index) >= 250  # the full 266-row listing, incl. 2023+
    for name, _ in ga_archive_files():
        ga_id = _MEMBER_RE.match(name).group(2)
        entry = index[ga_id]
        assert entry.notice_date is not None
        assert entry.notice_date.year == 2023  # TCSG era began Jan 2023
        assert entry.layoff_count and entry.layoff_count > 0
        assert entry.entry_url.startswith(
            "https://www.tcsg.edu/warn-public-view/entry/"
        )


def test_parse_entry_sample_fixture() -> None:
    """entry_sample.html is entry 41068 = GA202200071 (Dexter Axle Company)."""
    rows = parse_ga_entry_page(ENTRY_FIXTURE.read_bytes())
    assert len(rows) == 1
    r = rows[0]
    assert r.state == "GA"
    assert r.employer == "Dexter Axle Company"
    # Submitted Date from the bundled listing — NOT the page's separation date.
    assert r.notice_date == date(2023, 1, 17)
    assert r.effective_date == date(2023, 1, 9)  # First Date of Separation
    assert r.layoff_count == 67
    assert r.closure_type == "Permanent Closure"
    assert r.county == "Jasper County"
    assert r.address == "199 Perimeter Rd Monticello, Georgia"
    assert r.city is None and r.zip is None  # both feed notice_id — keep unset
    assert r.raw_notice_url == "https://www.tcsg.edu/warn-public-view/entry/41068/"
    assert r.extra == {"ga_warn_id": "GA202200071"}


def test_parse_all_bundled_pages() -> None:
    for name, raw in ga_archive_files():
        ga_id = _MEMBER_RE.match(name).group(2)
        rows = parse_ga_entry_page(raw)
        assert len(rows) == 1, name
        r = rows[0]
        assert r.state == "GA"
        assert r.employer
        assert r.notice_date is not None and r.notice_date.year == 2023
        assert r.effective_date is not None
        assert r.layoff_count and r.layoff_count > 0
        assert r.closure_type
        assert r.city is None and r.zip is None
        assert r.extra == {"ga_warn_id": ga_id}


def test_parse_rejects_page_without_identity() -> None:
    with pytest.raises(ParseFailed):
        parse_ga_entry_page(b"<html><table><tr><td>nope</td></tr></table></html>")


def test_parse_rejects_unknown_ga_warn_id() -> None:
    page = (
        b'<table><tr><th><span class="gv-field-label">GA WARN ID</span></th>'
        b"<td>GA209900001</td></tr>"
        b'<tr><th><span class="gv-field-label">Company Name</span></th>'
        b"<td>Ghost Corp</td></tr></table>"
    )
    with pytest.raises(ParseFailed, match="GA209900001"):
        parse_ga_entry_page(page)


# ---------------------------------------------------------------------------
# Hash alignment with the listing-derived rows prod stored
# ---------------------------------------------------------------------------

def test_notice_id_matches_listing_derived_rows() -> None:
    """Every parsed entry page must hash to the notice_id of the row the live
    scraper produced from the listing — otherwise the backfill would mint 31
    duplicates instead of filling the existing rows."""
    listing_rows = _listing_rows_for_bundled_entries()
    for name, raw in ga_archive_files():
        ga_id = _MEMBER_RE.match(name).group(2)
        mine = parse_ga_entry_page(raw)[0]
        theirs = listing_rows[ga_id]
        assert notice_id(mine) == notice_id(theirs), ga_id
        # The hash inputs themselves line up, not just the digest.
        assert mine.employer == theirs.employer, ga_id
        assert mine.notice_date == theirs.notice_date, ga_id
        # And the non-hashed listing fields agree too.
        assert mine.layoff_count == theirs.layoff_count, ga_id
        assert mine.raw_notice_url == theirs.raw_notice_url, ga_id


# ---------------------------------------------------------------------------
# End-to-end: fills existing rows, inserts nothing
# ---------------------------------------------------------------------------

def test_backfill_fills_without_inserting(db, db_session_factory) -> None:
    # Seed the DB the way prod was populated: listing-granularity rows.
    seeded = list(_listing_rows_for_bundled_entries().values())
    seen, new = upsert_notices(db, seeded)
    db.commit()
    assert (seen, new) == (31, 31)
    assert db.query(Notice).filter(Notice.closure_type.isnot(None)).count() == 0

    stats = backfill_historical("GA")

    assert stats["years_attempted"] == 31  # one per bundled page
    assert stats["rows_seen"] == 31
    assert stats["rows_new"] == 0  # fills only — no duplicates minted

    # The backfill committed through its own session; drop this session's
    # cached attribute state before re-reading.
    db.expire_all()
    notices = db.query(Notice).filter(Notice.state == "GA").all()
    assert len(notices) == 31
    dexter = next(n for n in notices if n.employer == "Dexter Axle Company")
    assert dexter.closure_type == "Permanent Closure"
    assert dexter.address == "199 Perimeter Rd Monticello, Georgia"
    assert dexter.effective_date == date(2023, 1, 9)
    assert dexter.location is not None
    assert dexter.location.county == "Jasper County"
    assert dexter.location.city is None and dexter.location.zip is None
