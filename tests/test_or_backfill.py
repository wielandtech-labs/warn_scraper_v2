"""OR historical backfill: Socrata dataset parser + bundled HECC capture union.

Fixtures are real data:
  * socrata_sample.json — 18 rows from data.oregon.gov/resource/ijbz-jpx8
    covering the shapes the aggregator must handle: same-site phased layoffs
    (warn 8281, Sulzer x6), one notice split across worksites (warn 4762,
    Phoenix Inn x8), a missing laid_off (6692), a missing city (9446), and a
    plain single row whose company_name is a facility label (9507).
  * hecc_capture_page.html — trimmed Wayback capture of the HECC list app
    (page=20&SortOrder=EstDate, 20250611180235): 10 dateless 1990s rows +
    10 dated rows, exercising the union build's dateless-drop path.
  * warn_v2/scrapers/data/or_archive.tar.gz — the real bundled union snapshot
    (461 dated master rows, 1989-2026).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from warn_v2.db.models import Notice
from warn_v2.scrapers.base import ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import load_archive
from warn_v2.scrapers.states import or_
from warn_v2.scrapers.states.or_ import (
    _ARCHIVE_TGZ,
    SOCRATA_MEMBER,
    or_backfill_files,
    parse_hecc_list_page,
    parse_or_archive_csv,
    parse_or_socrata,
)

FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "or"


@pytest.fixture
def socrata_sample() -> bytes:
    return (FIXTURES / "socrata_sample.json").read_bytes()


@pytest.fixture
def capture_page() -> str:
    return (FIXTURES / "hecc_capture_page.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Socrata parser
# ---------------------------------------------------------------------------

def test_socrata_aggregates_same_site_phases(socrata_sample: bytes) -> None:
    """Six phased Sulzer rows share (warn, company, city) -> one notice with
    the summed count and the earliest phase as effective_date."""
    rows = parse_or_socrata(socrata_sample)
    sulzer = [r for r in rows if r.employer == "Sulzer"]
    assert len(sulzer) == 1
    r = sulzer[0]
    assert r.layoff_count == 63  # 14+12+6+5+16+10
    assert r.notice_date == date(2021, 9, 10)  # received_date
    assert r.effective_date == date(2021, 11, 12)  # earliest layoff_date
    assert r.closure_type == "Permanent closure"
    assert r.extra["track_number"] == "8281"


def test_socrata_keeps_distinct_worksites(socrata_sample: bytes) -> None:
    """warn 4762 lists eight worksites of one hotel group — they stay
    separate rows (distinct company_name/city -> distinct notice_ids)."""
    rows = parse_or_socrata(socrata_sample)
    sites = [r for r in rows if r.extra["track_number"] == "4762"]
    assert len(sites) == 8
    assert all(r.notice_date == date(2020, 4, 8) for r in sites)
    grill = next(r for r in sites if r.employer == "Bentley's Grill")
    assert grill.layoff_count == 40
    assert grill.city == "Salem"


def test_socrata_missing_fields(socrata_sample: bytes) -> None:
    rows = parse_or_socrata(socrata_sample)
    no_count = next(r for r in rows if r.extra["track_number"] == "6692")
    assert no_count.layoff_count is None
    assert no_count.effective_date is None
    no_city = next(r for r in rows if r.employer == "Oregon - Remote Employees")
    assert no_city.city is None


def test_socrata_row_total(socrata_sample: bytes) -> None:
    """18 raw rows -> 13 notices after phase aggregation."""
    rows = parse_or_socrata(socrata_sample)
    assert len(rows) == 13
    assert all(r.state == "OR" for r in rows)
    assert all(r.notice_date is not None for r in rows)


def test_socrata_parse_failures() -> None:
    with pytest.raises(ParseFailed):
        parse_or_socrata(b"not json")
    with pytest.raises(ParseFailed):
        parse_or_socrata(b"[]")


def test_socrata_fetch_paginates(monkeypatch) -> None:
    """$offset advances by page size until a short page arrives."""
    monkeypatch.setattr(or_, "_SOCRATA_PAGE_SIZE", 2)
    pages = [
        [{"warn": "1"}, {"warn": "2"}],
        [{"warn": "3"}, {"warn": "4"}],
        [{"warn": "5"}],
    ]
    offsets: list[int] = []

    def fake_get(url, params=None, **kwargs):
        offsets.append(params["$offset"])
        resp = MagicMock()
        resp.json.return_value = pages[len(offsets) - 1]
        resp.raise_for_status.return_value = None
        return resp

    monkeypatch.setattr(or_.httpx, "get", fake_get)
    raw = or_._fetch_or_socrata()
    assert offsets == [0, 2, 4]
    assert [r["warn"] for r in json.loads(raw)] == ["1", "2", "3", "4", "5"]


def test_socrata_fetch_failure_raises(monkeypatch) -> None:
    def boom(url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(or_.httpx, "get", boom)
    with pytest.raises(ScrapeFailed):
        or_._fetch_or_socrata()


# ---------------------------------------------------------------------------
# HECC list-page extraction (union regeneration tooling)
# ---------------------------------------------------------------------------

def test_capture_page_rows(capture_page: str) -> None:
    rows = parse_hecc_list_page(capture_page)
    assert len(rows) == 20
    dateless = [r for r in rows if not r["date"]]
    assert len(dateless) == 10  # 1990s-era rows: empty Notification Date cells
    cadre = next(r for r in rows if r["employer"] == "CADRE TECHNOLOGIES INC.")
    assert cadre["track"] == "0191"
    assert cadre["date"].startswith("11/24/1993")
    assert cadre["count"] == "50"
    assert cadre["city"] == "Beaverton"
    assert cadre["notice_path"] == "/Layoff/WARN/UploadIndex/191"


# ---------------------------------------------------------------------------
# Bundled union snapshot (the real committed artifact)
# ---------------------------------------------------------------------------

def test_bundled_union_snapshot() -> None:
    members = load_archive(_ARCHIVE_TGZ)
    assert [name for name, _ in members] == ["or_hecc_union.csv"]
    rows = parse_or_archive_csv(members[0][1])
    assert len(rows) == 461
    assert all(r.state == "OR" and r.employer and r.notice_date for r in rows)
    # Every row carries its HECC track number; tracks are unique (the union
    # key), spanning the full dated history.
    tracks = [r.extra["track_number"] for r in rows]
    assert len(set(tracks)) == len(tracks)
    years = sorted({r.notice_date.year for r in rows})
    assert years[0] == 1989 and years[-1] == 2026
    # 2009 (recession peak) is the largest pre-2020 year in the source.
    assert sum(1 for r in rows if r.notice_date.year == 2009) == 50
    # Dateless 1990s rows were dropped at build time — never bundled.
    salem = next(r for r in rows if r.extra["track_number"] == "1930")
    assert salem.employer == "Salem Hospital"
    assert salem.notice_date == date(2012, 6, 15)
    assert salem.layoff_count == 52
    assert salem.closure_type == "Permanent closure"
    assert salem.raw_notice_url == "https://ccwd.hecc.oregon.gov/Layoff/WARN/UploadIndex/1930"


def test_archive_csv_parse_failures() -> None:
    with pytest.raises(ParseFailed):
        parse_or_archive_csv(b"")


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------

def test_or_backfill_spec_dispatch() -> None:
    from warn_v2.scripts import backfill_historical as bh

    spec = bh._BACKFILL["OR"]
    assert spec.bundled_files is not None
    assert spec.parse_for_url(SOCRATA_MEMBER) is parse_or_socrata
    assert spec.parse_for_url("or_hecc_union.csv") is parse_or_archive_csv


def test_or_backfill_files_members(monkeypatch, socrata_sample: bytes) -> None:
    monkeypatch.setattr(or_, "_fetch_or_socrata", lambda: socrata_sample)
    members = or_backfill_files()
    assert [name for name, _ in members] == ["or_hecc_union.csv", SOCRATA_MEMBER]
    assert members[1][1] == socrata_sample


def test_or_backfill_end_to_end(db, monkeypatch, socrata_sample: bytes) -> None:
    """Full Mode-3b run: both members ingest; union + socrata never share a
    track, so the row count is exactly the sum of the two parsers' outputs."""
    from warn_v2.scripts import backfill_historical as bh

    monkeypatch.setattr(or_, "_fetch_or_socrata", lambda: socrata_sample)
    with patch.object(bh, "session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = lambda _: db
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        stats = bh.backfill_historical("OR")

    assert stats["years_attempted"] == 2
    # Four union pairs share (employer, date, city) across distinct tracks
    # (e.g. two Stanford's sites noticed the same day) and merge into one
    # notice each with summed counts before the upsert counts them — see
    # storage._merge_worksite_rows.
    assert stats["rows_seen"] == 461 + 13 - 4
    assert db.query(Notice).filter(Notice.state == "OR").count() == 461 + 13 - 4
