from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed
from warn_v2.scrapers.registry import get_scraper

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "nv"
    / "sample.pdf"
)


@pytest.fixture
def nv_sample_pdf() -> bytes:
    return FIXTURE.read_bytes()


def test_nv_parses_live_sample(nv_sample_pdf: bytes) -> None:
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    assert len(rows) >= 5
    assert all(r.state == "NV" for r in rows)

    # Spirit Airlines: received 1/22/2026, 1 employee, Las Vegas, Clark
    spirit = next((r for r in rows if "Spirit" in (r.employer or "")), None)
    assert spirit is not None, "expected Spirit Airlines entry"
    assert spirit.notice_date == date(2026, 1, 22)
    assert spirit.layoff_count == 1
    assert spirit.city == "Las Vegas"
    assert spirit.county == "Clark"
    assert spirit.closure_type == "Layoff"


def test_nv_merged_count_employer_split(nv_sample_pdf: bytes) -> None:
    """'209SK' in raw PDF -> count=209, employer='SK Food Group, Inc.'"""
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    sk = next((r for r in rows if "SK Food" in (r.employer or "")), None)
    assert sk is not None, "expected SK Food Group entry"
    assert sk.layoff_count == 209


def test_nv_merged_date_type_split(nv_sample_pdf: bytes) -> None:
    """'3/15/2026Layoff' raw token -> effective_date 2026-03-15, type Layoff."""
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    spirit = next((r for r in rows if "Spirit" in (r.employer or "")), None)
    assert spirit is not None
    assert spirit.effective_date == date(2026, 3, 15)


def test_nv_notification_in_extra(nv_sample_pdf: bytes) -> None:
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    warn_rows = [r for r in rows if r.extra.get("notification") == "WARN"]
    non_warn_rows = [r for r in rows if r.extra.get("notification") == "Non-WARN"]
    assert warn_rows, "expected at least some WARN entries"
    assert non_warn_rows, "expected at least some Non-WARN entries"


def test_nv_iherb_count(nv_sample_pdf: bytes) -> None:
    """'113iHerb' -> count=113, employer='iHerb'."""
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    iherb = next((r for r in rows if "iHerb" in (r.employer or "")), None)
    assert iherb is not None, "expected iHerb entry"
    assert iherb.layoff_count == 113
    assert iherb.closure_type == "Closure"


def test_nv_validation_passes(nv_sample_pdf: bytes) -> None:
    scraper = get_scraper("NV")
    rows = scraper.parse(nv_sample_pdf)
    result = validate(scraper, rows)
    assert result.ok, result.reason


def test_nv_raises_on_bad_pdf() -> None:
    scraper = get_scraper("NV")
    with pytest.raises(ParseFailed):
        scraper.parse(b"this is not a pdf file")


# ---------------------------------------------------------------------------
# Per-year archive PDFs (backfill-historical)
# ---------------------------------------------------------------------------


@pytest.fixture
def nv_archive_2017() -> bytes:
    return (FIXTURE.parent / "archive_2017.pdf").read_bytes()


@pytest.fixture
def nv_archive_2025() -> bytes:
    return (FIXTURE.parent / "archive_2025.pdf").read_bytes()


def test_nv_archive_lattice_era(nv_archive_2017: bytes) -> None:
    """2017-2020 files are lattice tables parsed via extract_table."""
    from warn_v2.scrapers.states.nv import parse_nv_archive

    rows = parse_nv_archive(nv_archive_2017, 2017)
    assert len(rows) == 18
    assert all(r.notice_date.year == 2017 for r in rows)
    first = rows[0]
    assert first.employer == "Save-A-Lot"
    assert first.notice_date == date(2017, 1, 19)
    assert first.layoff_count == 64
    assert first.city == "Las Vegas"
    assert first.county == "Clark"
    assert first.closure_type == "Closure"


def test_nv_archive_word_era(nv_archive_2025: bytes) -> None:
    """2022+ files have no grid lines; per-era x-boundaries assign columns."""
    from warn_v2.scrapers.states.nv import parse_nv_archive

    rows = parse_nv_archive(nv_archive_2025, 2025)
    assert len(rows) >= 15
    assert all(r.notice_date.year == 2025 for r in rows)
    # Count column is right-aligned; the digit-leading employer "7 BEARS, LLC"
    # must not be folded into the count.
    bears = next(r for r in rows if "BEARS" in r.employer)
    assert bears.employer.startswith("7 BEARS")
    assert bears.layoff_count == 25
    assert bears.extra["notification"] == "Non-WARN"
    luxor = next(r for r in rows if "Luxor" in r.employer)
    assert luxor.layoff_count == 25
    assert luxor.city == "Las Vegas"
    assert luxor.county == "Clark"


def test_nv_fetch_year_skips_unpublished_years() -> None:
    """2016-and-earlier have no usable archive; 2021 (scanned) now has a source."""
    from warn_v2.scrapers.states.nv import _ARCHIVE_SOURCES, _fetch_nv_year

    # No source URL -> _fetch_nv_year returns None without any network call.
    assert _fetch_nv_year(2016) is None
    assert 2016 not in _ARCHIVE_SOURCES
    # 2021 is a scanned-image PDF but is now published + OCR-parsed, so it has
    # an archive source (fetched + OCR'd rather than skipped).
    assert 2021 in _ARCHIVE_SOURCES


# ---------------------------------------------------------------------------
# 2021 scanned-image year — OCR archive route
# ---------------------------------------------------------------------------


def test_nv_rows_from_words_2021_bounds() -> None:
    """The 2021 x-bounds assign OCR word boxes to the right columns.

    Runs without OCR: feeds synthetic point-space words (as ocr_word_boxes would
    emit) through the pure row-assembly function. Guards the column layout in CI,
    where the real tesseract path is unavailable.
    """
    from warn_v2.scrapers.states.nv import _ARCHIVE_XBOUNDS, _rows_from_words

    def w(text: str, x0: float, top: float) -> dict:
        return {"text": text, "x0": x0, "top": top}

    # One data row: Food Source, Reno, Washoe (bounds 129/186/239/291/454/526).
    words = [
        w("1/12/2021", 80, 100),   # < 129   -> received date
        w("3/31/2021", 135, 100),  # < 186   -> effective date
        w("Closure", 195, 100),    # < 239   -> type
        w("33", 245, 100),         # < 291   -> count
        w("Food", 300, 100),       # < 454   -> employer
        w("Source", 330, 100),     # < 454   -> employer (continuation)
        w("Reno", 460, 100),       # < 526   -> city
        w("Washoe", 530, 100),     # >= 526  -> county (no notification column)
    ]
    rows = _rows_from_words(words, _ARCHIVE_XBOUNDS[2021])
    assert len(rows) == 1
    r = rows[0]
    assert r["rcv_date"] == "1/12/2021"
    assert r["eff_date"] == "3/31/2021"
    assert r["action_type"] == "Closure"
    assert r["count"] == "33"
    assert r["employer"] == "Food Source"
    assert r["city"] == "Reno"
    assert r["county"] == "Washoe"
    assert r["notification"] is None


def test_nv_rows_from_words_straddling_tops() -> None:
    """A row whose word tops straddle a bucket boundary stays intact.

    Regression for the OCR 13/20 drop: with the old fixed-grid
    ``round(top / _ROW_BUCKET)``, tops like 136.3 and 138.0 round to different
    buckets (135 vs 140), so the employer split into a continuation bucket that
    failed the date gate and the row lost its employer. Proximity clustering
    keeps them together. The next row (top 147.4) must not merge in.
    """
    from warn_v2.scrapers.states.nv import _ARCHIVE_XBOUNDS, _rows_from_words

    def w(text: str, x0: float, top: float) -> dict:
        return {"text": text, "x0": x0, "top": top}

    words = [
        # Row A — date at 136.3, but count/employer/city jitter to 138.0.
        w("1/14/2021", 74, 136.3), w("12/18/2020", 130, 136.3), w("Layoff", 187, 137.0),
        w("4", 240, 138.0), w("Wyndham", 293, 138.0), w("Grand", 328, 138.0),
        w("Las", 456, 138.0), w("Vegas", 468, 138.0), w("Clark", 528, 138.0),
        # Row B — a distinct row ~9pt below; must not fold into row A.
        w("1/26/2021", 74, 147.4), w("1/7/2021", 130, 147.4), w("Layoff", 187, 147.4),
        w("13", 239, 147.4), w("Sykes", 293, 147.4), w("Reno", 456, 147.4),
        w("Washoe", 528, 147.4),
    ]
    rows = _rows_from_words(words, _ARCHIVE_XBOUNDS[2021])
    assert len(rows) == 2
    a, b = rows
    assert a["rcv_date"] == "1/14/2021"
    assert a["count"] == "4"
    assert a["employer"] == "Wyndham Grand"  # not dropped into a split bucket
    assert a["city"] == "Las Vegas"
    assert b["rcv_date"] == "1/26/2021"
    assert b["employer"] == "Sykes"


@pytest.fixture
def nv_archive_2021() -> bytes:
    return (FIXTURE.parent / "archive_2021.pdf").read_bytes()


@pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract binary unavailable (installed only in the Docker image)",
)
def test_nv_archive_2021_ocr(nv_archive_2021: bytes) -> None:
    """The 2021 scanned image OCRs into the 20 known notices.

    Skipped wherever the OCR stack is missing (CI, local dev); runs in the
    Docker image / in-cluster, and is the automated form of the prod-run
    ground-truth check.
    """
    pytest.importorskip("pytesseract")
    pytest.importorskip("pdf2image")
    from warn_v2.scrapers.states.nv import parse_nv_archive

    rows = parse_nv_archive(nv_archive_2021, 2021)
    assert len(rows) == 20  # all 20 data rows recovered (proximity clustering)
    assert all(r.notice_date.year == 2021 for r in rows)
    # 2021 has no Notification column.
    assert all(r.extra.get("notification") == "" for r in rows)

    def find(needle: str):
        return next((r for r in rows if needle in (r.employer or "")), None)

    food = find("Food Source")
    assert food is not None
    assert food.notice_date == date(2021, 1, 12)
    assert food.layoff_count == 33
    assert food.city == "Reno"
    assert food.county == "Washoe"
    assert food.closure_type == "Closure"

    sykes = find("Sykes")
    assert sykes is not None and sykes.layoff_count == 242

    # Rows that the pre-fix fixed-grid bucketing dropped (employer landed in a
    # split continuation bucket) — the clustering regression guard under real OCR.
    for needle, count in [("Silverton", 45), ("Aerion", 99), ("West Hills", 116)]:
        row = find(needle)
        assert row is not None, f"expected {needle} entry"
        assert row.layoff_count == count

    hycroft = find("Hycroft")
    assert hycroft is not None
    assert hycroft.city == "Winnemucca"
    assert hycroft.county == "Humboldt"

    food = next((r for r in rows if "Food Source" in (r.employer or "")), None)
    assert food is not None, "expected Food Source entry"
    assert food.notice_date == date(2021, 1, 12)
    assert food.layoff_count == 33
    assert food.city == "Reno"
    assert food.county == "Washoe"
    assert food.closure_type == "Closure"

    sykes = next((r for r in rows if "Sykes" in (r.employer or "")), None)
    assert sykes is not None and sykes.layoff_count == 242

    hycroft = next((r for r in rows if "Hycroft" in (r.employer or "")), None)
    assert hycroft is not None
    assert hycroft.city == "Winnemucca"
    assert hycroft.county == "Humboldt"
