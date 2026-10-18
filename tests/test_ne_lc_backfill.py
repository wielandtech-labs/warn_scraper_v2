"""NE historical backfill: NDOL's Layoff and Closures report (Mode 3b, Non-WARN).

Bundled as warn_v2/scrapers/data/ne_lc_archive.tar.gz: Wayback quarterly pages
of the 2008-2010 layoffreport.cfm (with notified date + notification source)
and the frozen live LayoffAndClosureReportData endpoint for 2011-2020. Rows
are tagged Non-WARN except source-WARN ones, and WARN-report duplicates are
dropped so none can hash onto a WARN row's notice_id.
"""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.states.ne import (
    _parse_lc_table,
    _warn_report_rows,
    is_ne_lc_member,
    ne_lc_files,
    parse_ne_archive,
    parse_ne_lc,
)
from warn_v2.scripts.backfill_historical import _BACKFILL

# member -> (rows on the page, rows kept after dropping WARN-report duplicates)
EXPECTED = {
    "lc_2011.html": (40, 36),
    "lc_2012.html": (44, 37),
    "lc_2013.html": (40, 31),
    "lc_2014.html": (36, 31),
    "lc_2015.html": (102, 92),
    "lc_2016.html": (110, 105),
    "lc_2017.html": (126, 122),
    "lc_2018.html": (133, 128),
    "lc_2019.html": (194, 178),
    "lc_2020.html": (65, 55),
    "lr_2008_q3.html": (10, 10),
    "lr_2008_q4.html": (67, 67),
    "lr_2009_q1.html": (147, 146),
    "lr_2009_q2.html": (49, 49),
    "lr_2009_q3.html": (23, 23),
    "lr_2009_q4.html": (30, 30),
    "lr_2010_q1.html": (20, 19),
    "lr_2010_q2.html": (16, 15),
    "lr_2010_q3.html": (3, 3),
}


@pytest.fixture(scope="module")
def archive() -> dict[str, bytes]:
    return dict(ne_lc_files())


@pytest.fixture(scope="module")
def kept(archive: dict[str, bytes]) -> dict[str, list]:
    return {name: parse_ne_lc(raw, name) for name, raw in archive.items()}


def test_bundle_members(archive: dict[str, bytes]) -> None:
    assert sorted(archive) == sorted(EXPECTED)
    assert all(is_ne_lc_member(n) for n in archive)
    assert not is_ne_lc_member("warnreportdata_2015.html")


def test_per_member_counts(archive: dict[str, bytes], kept: dict[str, list]) -> None:
    for name, (raw_n, kept_n) in EXPECTED.items():
        assert len(_parse_lc_table(archive[name], "x")) == raw_n, name
        assert len(kept[name]) == kept_n, name


def test_tagging_non_warn_except_source_warn(kept: dict[str, list]) -> None:
    rows = [r for rs in kept.values() for r in rs]
    warn_src = [r for r in rows if "non_warn" not in r.extra]
    assert len(warn_src) == 7
    # "WARN" or e.g. "WARN / Trade Certification Pending".
    assert all(r.extra["notification_source"].startswith("WARN") for r in warn_src)
    # Only the 2008-2010 era carries a notification source at all.
    assert all(r.notice_date.year <= 2010 for r in warn_src)


def test_no_row_collides_with_a_warn_report_notice(kept: dict[str, list]) -> None:
    warn_ids = {notice_id(w) for w in _warn_report_rows()}
    assert {notice_id(r) for rs in kept.values() for r in rs}.isdisjoint(warn_ids)


def test_warn_report_duplicate_is_dropped(archive: dict[str, bytes]) -> None:
    """The 2015 WARN row IAC Acoustics (Lincoln, 2015-11-17, 160) is on the
    L&C page under the same date; a second, smaller IAC event stays."""
    page = archive["lc_2015.html"]
    raw = [r for r in _parse_lc_table(page, "x") if r.employer == "IAC Acoustics"]
    kept = [r for r in parse_ne_lc(page, "lc_2015.html") if r.employer == "IAC Acoustics"]
    assert sorted(r.layoff_count for r in raw) == [30, 160]
    assert [r.layoff_count for r in kept] == [30]


def test_source_warn_repeat_listing_is_dropped(kept: dict[str, list]) -> None:
    """Leon Plastics (Alda, 140) is listed as a WARN notice twice, notified
    2008-11-12 (Q4 2008) and 2008-11-17 (Q1 2009); only the first is kept.
    Its later closure entry (Q2 2009, newspaper-sourced) stays Non-WARN."""
    leon = [r for rs in kept.values() for r in rs if r.employer == "Leon Plastics"]
    warn = [r for r in leon if "non_warn" not in r.extra]
    assert [r.notice_date for r in warn] == [date(2008, 11, 12)]
    assert len(leon) == 2


def test_wayback_era_fields(kept: dict[str, list]) -> None:
    row = next(r for r in kept["lr_2009_q1.html"] if r.employer == "Neapco, Inc.")
    assert row.city == "Beatrice"
    assert row.notice_date == date(2009, 2, 12)  # Date NWD-DOL Notified
    assert row.effective_date == date(2009, 2, 13)  # Event Date
    assert row.closure_type == "Layoff"
    assert row.layoff_count == 35
    assert row.extra == {"non_warn": "1", "notification_source": "Omaha World Herald"}
    assert row.source_url == (
        "https://web.archive.org/web/20100601195549/http://www.dol.nebraska.gov/nwd/"
        "employers/dislocated/layoffreport.cfm?report=Qtr1&yr=2009"
    )


def test_live_era_fields(kept: dict[str, list]) -> None:
    row = next(r for r in kept["lc_2016.html"] if r.employer == "McKesson Corporation")
    assert row.notice_date == row.effective_date == date(2016, 12, 31)
    assert row.closure_type == "Closure"
    assert row.layoff_count == 80
    assert row.city == "La Vista"
    assert row.address is None  # Location == City
    assert row.extra == {"non_warn": "1"}
    assert row.source_url.endswith("LayoffAndClosureReportData/?year=2016")


def test_backfill_spec_routes_both_archives() -> None:
    spec = _BACKFILL["NE"]
    names = [n for n, _ in spec.bundled_files()]
    assert "warnreportdata_2015.html" in names and "lc_2015.html" in names
    warn_member = dict(spec.bundled_files())["warnreportdata_2015.html"]
    rows = spec.parse_for_url("warnreportdata_2015.html")(warn_member)
    assert rows == parse_ne_archive(warn_member, "warnreportdata_2015.html")
    lc_rows = spec.parse_for_url("lc_2015.html")(dict(spec.bundled_files())["lc_2015.html"])
    assert len(lc_rows) == 92 and all(r.extra.get("non_warn") for r in lc_rows)
