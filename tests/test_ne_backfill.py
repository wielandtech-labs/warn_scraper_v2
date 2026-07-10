"""NE historical backfill: bundled legacy per-year fragments (Mode 3b).

The frozen endpoint dol.nebraska.gov/LayoffServices/WARNReportData/?year={Y}
served per-year report tables for 2010-2020 (snapshotted 2026-07-10, bundled
as warn_v2/scrapers/data/ne_archive.tar.gz). Unlike the live page, these
fragments prepend banner rows before the header and carry both a City and a
Location column.
"""
from __future__ import annotations

from datetime import date

import pytest

from warn_v2.pipeline.storage import _merge_worksite_rows
from warn_v2.scrapers.states.ne import ne_archive_files, parse_ne_archive

EXPECTED_ROWS = {
    2010: 6,
    2011: 7,
    2012: 9,
    2013: 7,
    2014: 7,
    2015: 15,
    2016: 5,
    2017: 8,
    2018: 7,
    2019: 17,
    2020: 19,
}


@pytest.fixture(scope="module")
def archive() -> dict[str, bytes]:
    return dict(ne_archive_files())


def test_archive_bundles_2010_through_2020(archive: dict[str, bytes]) -> None:
    assert sorted(archive) == [f"warnreportdata_{y}.html" for y in range(2010, 2021)]


def test_per_year_counts_dates_and_source_urls(archive: dict[str, bytes]) -> None:
    for year, expected in EXPECTED_ROWS.items():
        name = f"warnreportdata_{year}.html"
        rows = parse_ne_archive(archive[name], name)
        assert len(rows) == expected, name
        assert all(r.state == "NE" for r in rows)
        assert all(r.notice_date.year == year for r in rows)
        assert all(r.source_url.endswith(f"?year={year}") for r in rows)


def test_total_rows_and_jobs(archive: dict[str, bytes]) -> None:
    """Whole-bundle checksum — guards against bundle regeneration drift."""
    all_rows = [
        row
        for name, raw in archive.items()
        for row in parse_ne_archive(raw, name)
    ]
    assert len(all_rows) == 107
    assert sum(r.layoff_count or 0 for r in all_rows) == 12_599


def test_2015_spot_checks(archive: dict[str, bytes]) -> None:
    name = "warnreportdata_2015.html"
    rows = parse_ne_archive(archive[name], name)

    first = rows[0]
    assert first.employer == "IAC Acoustics"
    assert first.notice_date == date(2015, 11, 17)
    assert first.layoff_count == 160
    assert first.city == "Lincoln"
    assert first.address is None  # Location == City -> no worksite detail

    last = rows[-1]
    assert last.employer == "Land O'Frost"
    assert last.notice_date == date(2015, 2, 27)
    assert last.layoff_count == 125
    assert last.city == "West Point"

    # Blank Jobs Affected stays None, never 0.
    shopko = next(r for r in rows if r.employer == "Shopko Corporate Office")
    assert shopko.layoff_count is None


def test_worksite_detail_lands_in_address(archive: dict[str, bytes]) -> None:
    """A Location that adds detail beyond the City column goes to ``address``
    so same-employer/date/city worksite pairs keep distinct identities."""
    name = "warnreportdata_2015.html"
    rows = parse_ne_archive(archive[name], name)
    michael = [r for r in rows if r.employer == "Michael Foods Egg Products Company"]
    assert {r.address for r in michael} == {
        "Wakefield - Farm Facility",
        "Wakefield - Plant Facility",
    }
    assert all(r.city == "Wakefield" for r in michael)


def test_worksite_pairs_merge_with_summed_counts(archive: dict[str, bytes]) -> None:
    """The storage-layer worksite merge must never lose jobs from the bundle
    (each notice_id collision is a distinct-worksite pair, not a duplicate)."""
    for name, raw in archive.items():
        rows = parse_ne_archive(raw, name)
        merged = _merge_worksite_rows(rows)
        assert sum(r.layoff_count or 0 for r in merged) == sum(
            r.layoff_count or 0 for r in rows
        ), name
