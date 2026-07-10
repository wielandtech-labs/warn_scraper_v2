"""LA historical backfill (2007-2024 Wayback per-year PDFs).

Two real fixtures cover the archive quirks the live-era samples don't:
  * sample_2016.pdf — spaced-header era ("E m p loyees Affected"), plus
    UPDATE rows that pile several dates ("1/13/2016 3/9/2016 ...") or amended
    counts ("8 +1") into one cell.
  * sample_2024.pdf — footnoted counts ("125* *Only one employee ..."),
    en-dash layoff-date ranges ("3/01/24" to "4/30/24" in one cell).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ScrapeFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states import la
from warn_v2.scrapers.states.la import _fetch_la_year, _source_url, parse_la_pdf

FIXTURES = Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures" / "la"


@pytest.fixture
def y2016() -> bytes:
    return (FIXTURES / "sample_2016.pdf").read_bytes()


@pytest.fixture
def y2024() -> bytes:
    return (FIXTURES / "sample_2024.pdf").read_bytes()


def _find(rows, needle: str):
    return next(r for r in rows if needle in r.employer)


# ---------------------------------------------------------------------------
# 2016 — spaced header + UPDATE cells
# ---------------------------------------------------------------------------


def test_2016_spaced_header_parses_all_rows(y2016: bytes) -> None:
    rows = parse_la_pdf(y2016, "x")
    # 10 data rows on the trimmed page; the header reads "E m p loyees
    # Affected" and must still be recognised.
    assert len(rows) == 10
    assert all(r.state == "LA" for r in rows)
    assert all(r.notice_date is not None for r in rows)


def test_2016_update_row_uses_original_dates(y2016: bytes) -> None:
    # Noranda's notice cell holds six dates (original + five UPDATEs) and the
    # layoff cell five — the first of each is the original filing.
    noranda = _find(parse_la_pdf(y2016, "x"), "Noranda")
    assert noranda.notice_date == date(2016, 1, 13)
    assert noranda.effective_date == date(2016, 3, 14)
    assert noranda.layoff_count == 444
    assert noranda.city == "Gramercy"
    assert noranda.zip == "70052"


def test_2016_amended_count_uses_original(y2016: bytes) -> None:
    # "8 +1" → the originally noticed 8.
    garden = _find(parse_la_pdf(y2016, "x"), "Garden City")
    assert garden.layoff_count == 8
    assert garden.notice_date == date(2016, 1, 13)


def test_2016_validates(y2016: bytes) -> None:
    result = validate(get_scraper("LA"), parse_la_pdf(y2016, "x"))
    assert result.ok, result.reason


# ---------------------------------------------------------------------------
# 2024 — footnoted counts, en-dash ranges
# ---------------------------------------------------------------------------


def test_2024_parses_all_rows(y2024: bytes) -> None:
    rows = parse_la_pdf(y2024, "x")
    assert len(rows) == 7
    assert all(r.notice_date is not None for r in rows)


def test_2024_footnoted_counts(y2024: bytes) -> None:
    rows = parse_la_pdf(y2024, "x")
    # "125* *Only one employee affected..." and "*292 *Only forty (40)..."
    assert _find(rows, "Lost Boys").layoff_count == 125
    assert _find(rows, "ADT Solar").layoff_count == 292


def test_2024_endash_range_uses_start(y2024: bytes) -> None:
    # Layoff Date cell holds the en-dash range "3/01/24" .. "4/30/24".
    diamond = _find(parse_la_pdf(y2024, "x"), "Diamond Offshore Auriga")
    assert diamond.effective_date == date(2024, 3, 1)
    assert diamond.city == "Houma"
    assert diamond.zip == "70363"


def test_2024_validates(y2024: bytes) -> None:
    result = validate(get_scraper("LA"), parse_la_pdf(y2024, "x"))
    assert result.ok, result.reason


# ---------------------------------------------------------------------------
# Fetch routing + registry
# ---------------------------------------------------------------------------


def test_source_url_wayback_for_pruned_years() -> None:
    url = _source_url(2014)
    assert url == (
        "https://web.archive.org/web/20231011190400id_/"
        "https://www.laworks.net/Downloads/WFD/WarnNotices2014.pdf"
    )


def test_source_url_live_for_2025_plus() -> None:
    assert _source_url(2025) == "https://www.laworks.net/Downloads/WFD/WarnNotices2025.pdf"
    assert _source_url(2026) == "https://www.laworks.net/Downloads/WFD/WarnNotices2026.pdf"


def test_wayback_ts_covers_2007_through_2024() -> None:
    assert sorted(la._WAYBACK_TS) == list(range(2007, 2025))


def test_fetch_pruned_year_uses_wayback(monkeypatch) -> None:
    seen = []

    def fake_fetch(url, **kw):
        seen.append(url)
        return b"%PDF-1.4 fake"

    monkeypatch.setattr(la.wayback, "fetch", fake_fetch)
    assert _fetch_la_year(2014) == b"%PDF-1.4 fake"
    assert seen == [_source_url(2014)]


def test_fetch_pruned_year_rejects_non_pdf_capture(monkeypatch) -> None:
    monkeypatch.setattr(la.wayback, "fetch", lambda url, **kw: b"<html>soft 404")
    with pytest.raises(ScrapeFailed):
        _fetch_la_year(2014)


def test_fetch_live_year_skips_wayback(monkeypatch) -> None:
    def boom(url, **kw):  # pragma: no cover - must not be called
        raise AssertionError("wayback.fetch called for a live year")

    class FakeResponse:
        status_code = 200
        content = b"%PDF-1.7 live"

    monkeypatch.setattr(la.wayback, "fetch", boom)
    monkeypatch.setattr(la.httpx, "get", lambda url, **kw: FakeResponse())
    assert _fetch_la_year(2025) == b"%PDF-1.7 live"


def test_registry_year_start_lowered_to_2007() -> None:
    from warn_v2.scripts.backfill_historical import _BACKFILL

    assert _BACKFILL["LA"].year_start == 2007
