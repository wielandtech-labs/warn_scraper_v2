"""IA historical backfill: the bundled snapshot archive (Mode 3b).

Iowa publishes ONE cumulative WARN log and prunes old rows from it, so the
2005-2021 history is recovered from four archived snapshots of that log
bundled in ``warn_v2/scrapers/data/ia_archive.tar.gz``. The XLSX members
parse via the regular ``IAScraper.parse`` (legacy header labels are aliased
there); the 2005-2015 PDF era has its own ``parse_ia_archive_pdf``.

These tests parse the real bundled members, so the asserted counts are pinned
to the committed archive — they change only if the tar.gz is regenerated.
"""
from __future__ import annotations

from collections import Counter
from datetime import date

import pytest

from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ia import ia_archive_files, parse_ia_archive_pdf
from warn_v2.scripts.backfill_historical import _BACKFILL

_PDF = "WARN_20150722.pdf"
_X17 = "WARN_20171219.xlsx"
_X21 = "WARN_20210105.xlsx"
_X23 = "WARN_20230823.xlsx"


@pytest.fixture(scope="module")
def members() -> dict[str, bytes]:
    return dict(ia_archive_files())


@pytest.fixture(scope="module")
def parsed(members: dict[str, bytes]) -> dict[str, list]:
    scraper = get_scraper("IA")
    return {
        name: (parse_ia_archive_pdf if name.endswith(".pdf") else scraper.parse)(raw)
        for name, raw in members.items()
    }


def test_archive_members(members: dict[str, bytes]) -> None:
    assert sorted(members) == [_PDF, _X17, _X21, _X23]
    assert all(len(raw) > 10_000 for raw in members.values())


# ---------------------------------------------------------------------------
# PDF era (2005-07 .. 2015-07)
# ---------------------------------------------------------------------------

def test_pdf_member_counts_and_span(parsed: dict[str, list]) -> None:
    rows = parsed[_PDF]
    assert len(rows) == 358
    dates = sorted(r.notice_date for r in rows)
    assert dates[0] == date(2005, 7, 6)
    assert dates[-1] == date(2015, 7, 21)
    years = Counter(r.notice_date.year for r in rows)
    assert years[2005] == 12
    assert years[2009] == 59  # recession peak
    assert all(r.state == "IA" for r in rows)


def test_pdf_spot_row_first_notice(parsed: dict[str, list]) -> None:
    saks = next(r for r in parsed[_PDF] if r.employer.startswith("Saks"))
    assert saks.employer == "Saks Incoporated / Younkers"  # source typo kept as-is
    assert saks.notice_date == date(2005, 7, 6)
    assert saks.effective_date == date(2005, 8, 30)
    assert saks.layoff_count == 105
    assert saks.city == "Des Moines"
    assert saks.county == "Polk"
    assert saks.zip == "50309"
    assert saks.closure_type == "Closure"
    assert saks.address == "7th and Walnut"


def test_pdf_unicode_hyphen_normalized(parsed: dict[str, list]) -> None:
    # The PDF font renders hyphens as U+2010; the parser maps them to ASCII
    # "-" so overlap rows hash-collide with the XLSX-era snapshots.
    mcgraw = next(r for r in parsed[_PDF] if "McGraw" in r.employer)
    assert mcgraw.employer == "McGraw-Hill Companies, Inc"
    assert "\u2010" not in mcgraw.employer
    twin = next(r for r in parsed[_X17] if "McGraw" in r.employer)
    assert notice_id(mcgraw) == notice_id(twin)


def test_pdf_source_typo_year_rejected(parsed: dict[str, list]) -> None:
    # Gleason Corp 8/18/2006 has layoff date "10/20/1969" in the source PDF;
    # as_date's year floor rejects it rather than storing a corrupt date.
    gleason = next(
        r for r in parsed[_PDF]
        if r.employer == "Gleason Corporation" and r.notice_date == date(2006, 8, 18)
    )
    assert gleason.effective_date is None


def test_pdf_parse_failed_on_garbage() -> None:
    with pytest.raises(ParseFailed):
        parse_ia_archive_pdf(b"%PDF-1.4 not really a pdf")


# ---------------------------------------------------------------------------
# XLSX era snapshots (reuse IAScraper.parse, legacy labels)
# ---------------------------------------------------------------------------

def test_xlsx_member_counts(parsed: dict[str, list]) -> None:
    # Trailing empty rows/columns (openpyxl read_only unsized-sheet quirk)
    # must not produce rows.
    assert len(parsed[_X17]) == 308
    assert len(parsed[_X21]) == 366
    assert len(parsed[_X23]) == 368


def test_xlsx_spot_row(parsed: dict[str, list]) -> None:
    tyson = next(
        r for r in parsed[_X21]
        if "Tyson" in r.employer and r.notice_date == date(2015, 8, 14)
    )
    assert tyson.layoff_count == 404  # "404.0" float cell coerced
    assert tyson.city == "Denison"
    assert tyson.county == "Crawford"
    assert tyson.zip == "51442"
    assert tyson.closure_type == "Closing"


def test_xlsx_string_dates_parse(parsed: dict[str, list]) -> None:
    # WARN_20230823.xlsx stores Notice Date as "8/27/2018"-style strings.
    pioneer = next(r for r in parsed[_X23] if r.employer.startswith("Pioneer"))
    assert pioneer.notice_date == date(2018, 8, 27)
    assert pioneer.closure_type == "Amendment"


# ---------------------------------------------------------------------------
# Union / overlap dedup
# ---------------------------------------------------------------------------

def test_union_spans_2005_to_2021_without_gaps(parsed: dict[str, list]) -> None:
    union: dict[str, object] = {}
    for rows in parsed.values():
        for r in rows:
            union.setdefault(notice_id(r), r)
    assert len(union) == 956
    years = Counter(r.notice_date.year for r in union.values())
    # Continuous coverage across the whole archive (2005 .. 2023).
    assert sorted(years) == list(range(2005, 2024))
    pre_2021 = sum(c for y, c in years.items() if y < 2021)
    assert pre_2021 == 770


def test_overlapping_snapshots_hash_collide(parsed: dict[str, list]) -> None:
    # The snapshots overlap by design; identical rows must collapse by
    # notice_id (e.g. 122 of the PDF's 358 rows recur in the 2017 XLSX).
    ids_x17 = {notice_id(r) for r in parsed[_X17]}
    colliding = [r for r in parsed[_PDF] if notice_id(r) in ids_x17]
    assert len(colliding) == 122
    assert any(r.employer == "United HR Direct" for r in colliding)


def test_amendment_rows_kept(parsed: dict[str, list]) -> None:
    # "Amendment" rows are kept as-is (the live cumulative log carries the
    # same Notice Type and prod already stores them); superseded originals
    # are a post-ingest mark-superseded concern.
    assert sum(1 for r in parsed[_PDF] if r.closure_type == "Amendment") == 75
    assert sum(1 for r in parsed[_X17] if r.closure_type == "Amendment") == 120


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------

def test_registry_entry_dispatch() -> None:
    spec = _BACKFILL["IA"]
    assert spec.bundled_files is ia_archive_files
    assert spec.parse_for_url(_PDF) is parse_ia_archive_pdf
    assert spec.parse_for_url(_X21) is None  # falls back to IAScraper.parse
