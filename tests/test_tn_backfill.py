"""Tests for the TN historical backfill (bundled 2025-01-16 Wayback capture).

The bundle member is the real capture of the live reports page taken while
its archive section still held the full 2017-2024 history, so these tests
exercise the parser on the exact bytes prod will ingest.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from warn_v2.db.models import Notice
from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.states.tn import parse_tn_archive, tn_archive_files
from warn_v2.scripts.backfill_historical import backfill_historical


@pytest.fixture(scope="module")
def archive() -> dict[str, bytes]:
    return dict(tn_archive_files())


@pytest.fixture(scope="module")
def rows(archive):
    return parse_tn_archive(archive["reports_20250116.html"])


def test_archive_members(archive):
    assert sorted(archive) == ["reports_20250116.html"]


def test_row_count_and_years(rows):
    # 514 labeled entries merge to 507 rows (5 same-day multi-filing groups
    # collapse: GDI 2024, Enterprise Holdings x2 2020, Kmart 2019, Sam's Club
    # 2018). Every id is unique after the merge.
    assert len(rows) == 507
    years = {}
    for r in rows:
        years[r.notice_date.year] = years.get(r.notice_date.year, 0) + 1
    assert years == {
        2017: 7,
        2018: 35,
        2019: 58,
        2020: 265,
        2021: 22,
        2022: 12,
        2023: 54,
        2024: 54,
    }
    assert len({notice_id(r) for r in rows}) == 507
    assert sum(r.layoff_count or 0 for r in rows) == 67705


def test_plain_entry_fields(rows):
    gh = next(r for r in rows if r.employer.startswith("GH Armor"))
    assert gh.notice_date == date(2024, 1, 2)
    assert gh.effective_date == date(2024, 2, 20)
    assert gh.layoff_count == 40
    assert gh.county == "Stewart"
    assert gh.extra == {"notice_number": "#202400026"}
    # The letter PDFs are pruned from live tn.gov — links are Wayback-wrapped.
    assert gh.raw_notice_url == (
        "https://web.archive.org/web/20250116/https://www.tn.gov/content/dam/tn/"
        "workforce/documents/majorpublications/reports-02/"
        "GH-Armor-Systems-TDLWD-WARN-LETTER.pdf"
    )


def test_collision_merge_sums_counts_and_joins_counties(rows):
    """Four distinct Enterprise Holdings filings share (employer, posted date)
    and would collide on notice_id — the merge keeps all 148 workers."""
    ent = next(
        r
        for r in rows
        if r.employer == "Enterprise Holdings, LLC" and r.notice_date == date(2020, 5, 7)
    )
    assert ent.layoff_count == 148  # 6 + 122 + 18 + 2
    assert ent.county == "Blount; Knox; Shelby"
    assert ent.effective_date == date(2020, 3, 23)  # earliest of the filings
    assert ent.extra["notice_number"] == "#202000160; #202000161; #202000159; #202000158"

    kmart = next(r for r in rows if r.employer == "Kmart Corporation")
    assert kmart.layoff_count == 88  # Sevier 46 + Sullivan 42


def test_label_variants(rows):
    # "Notice Type:" (no slash) — Hotel Preston.
    preston = next(r for r in rows if "Hotel Preston" in r.employer)
    assert preston.extra == {"notice_number": "#202000047"}
    # "Company :" (space before colon) — Strike King.
    strike = next(r for r in rows if "Strike King" in r.employer)
    assert strike.notice_date == date(2019, 10, 8)
    # "Counties:" (plural) keeps the full multi-county string.
    bridal = next(r for r in rows if "Bridal" in r.employer)
    assert bridal.county == (
        "Williamson, Shelby, Knox, Davidson, Hamilton, Washington, Rutherford"
    )


def test_freetext_effective_dates(rows):
    # Range takes the first dated token.
    strike = next(r for r in rows if "Strike King" in r.employer)
    assert strike.effective_date == date(2019, 12, 1)  # "Dec 1 until Dec 31, 2019"
    # Missing comma-space: "March 20,2020".
    benihana = next(r for r in rows if "Benihana" in r.employer)
    assert benihana.effective_date == date(2020, 3, 20)
    # Month-year only: "beginning February 2020".
    flex = next(r for r in rows if r.employer == "Flex")
    assert flex.effective_date == date(2020, 2, 1)
    # Source typos stay None: a stray worker count ("124") and "Apri 1, 2020".
    no_eff = {r.employer for r in rows if r.effective_date is None}
    assert no_eff == {"L&W, Inc., dba Southtec, LLC", "Logistics Insight Corp"}


def test_posted_date_with_internal_space(rows):
    """One 2018 entry reads 'Date Notice Posted: 2018/4/ 27'."""
    ti = next(
        r for r in rows if "TI Group" in r.employer and r.notice_date.year == 2018
    )
    assert ti.notice_date == date(2018, 4, 27)
    assert ti.county == "Greene"


def test_out_of_state_worksite_kept(rows):
    # TN filing for a Mississippi worksite; count "147 (69 Tennessee
    # residents)" keeps the leading total.
    view = next(r for r in rows if r.employer == "View")
    assert view.layoff_count == 147
    assert view.county == "DeSoto County, Mississippi"


def test_backfill_tn_ingests_bundle(db):
    stats = backfill_historical("TN")

    assert stats["years_attempted"] == 1
    assert stats["years_ok"] == 1
    assert stats["rows_seen"] == 507
    assert stats["rows_new"] == 507
    assert db.execute(select(func.count(Notice.notice_id))).scalar_one() == 507

    # Idempotent re-run: nothing new.
    stats2 = backfill_historical("TN")
    assert stats2["rows_new"] == 0
