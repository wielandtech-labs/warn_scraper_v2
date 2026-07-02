"""Tests for extract_layoff_count + the backfill-layoff-counts command.

Fixture PDFs under ``warn_v2/scrapers/fixtures/{ct,hi,wv}/`` are real WARN
letters pulled from the state sources — the same documents ``download-pdfs``
stores in prod. The CT (and one WV) letters carry a text layer; the
``*_scanned.pdf`` HI/WV fixtures are scanned images with no text layer, so
they exercise the OCR-fallback branch. tesseract is not installed in the
test env, so OCR output is mocked with the letter's transcribed text; the
scanned fixtures still prove the pdfplumber→OCR handoff on real bytes.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from warn_v2.db.models import Notice
from warn_v2.pdf_extract import _extract_text, extract_layoff_count
from warn_v2.scripts.backfill_layoff_counts import backfill_layoff_counts

FIXTURES = (
    Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures"
)


# ---------------------------------------------------------------------------
# extract_layoff_count — explicit totals (tier 1)
# ---------------------------------------------------------------------------

def test_total_separation_of_n_employees():
    text = "This will result in the total separation of 73 employees at the facility."
    assert extract_layoff_count(text) == 73


def test_in_total_will_affect_n():
    text = "In total, this action will affect 205 employees at the New Britain Facility."
    assert extract_layoff_count(text) == 205


def test_total_number_of_affected_employees_is_word_number():
    # Multi-state letter: the in-state total is prose, spelled out.
    text = "The total number of affected employees in West Virginia is one."
    assert extract_layoff_count(text) == 1


def test_labeled_number_of_employees_affected():
    text = (
        "Total number of employees at the establishment: 7\n"
        "Approximate number of employees affected: 4\n"
    )
    assert extract_layoff_count(text) == 4


def test_labeled_number_to_be_laid_off_ignores_store_headcount():
    text = (
        "Number of employees at Store: 8\n"
        "Approximate number of\nemployees to be laid off: 8\n"
    )
    assert extract_layoff_count(text) == 8


def test_establishment_headcount_alone_is_not_a_count():
    # JINYA (HI): headcount + "all positions eliminated" but no affected total.
    text = (
        "The number of employees employed by the establishment is 86.\n"
        "All employee positions at this location will be eliminated upon the "
        "restaurant's closing.\n"
    )
    assert extract_layoff_count(text) is None


# ---------------------------------------------------------------------------
# extract_layoff_count — action-adjacent (tier 2)
# ---------------------------------------------------------------------------

def test_will_affect_n_employees():
    text = "This action will affect 205 employees at the facility."
    assert extract_layoff_count(text) == 205


def test_n_workers_will_be_affected():
    text = "We anticipate that approximately 300 workers will be affected by this action."
    assert extract_layoff_count(text) == 300


def test_filler_words_between_count_and_noun():
    text = "Approximately 100 full- and part-time positions will be eliminated."
    assert extract_layoff_count(text) == 100


def test_laying_off_approximately_n():
    text = (
        "Greenbrier Minerals will begin permanently laying off approximately "
        "530 Greenbrier Minerals employees at the Mine."
    )
    assert extract_layoff_count(text) == 530


def test_all_n_employees():
    text = "All 10 employees have been notified of their separation date."
    assert extract_layoff_count(text) == 10


def test_conflicting_counts_are_ambiguous():
    text = (
        "This action will affect 50 employees at Site A. "
        "This action will affect 30 employees at Site B."
    )
    assert extract_layoff_count(text) is None


# ---------------------------------------------------------------------------
# extract_layoff_count — sentence scope (tier 3) and guards
# ---------------------------------------------------------------------------

def test_count_in_layoff_sentence():
    # WVURC (WV): the number is not adjacent to the action verb.
    text = (
        "This mass layoff will affect every employe of WVURC, which at the "
        "time of the submission of this notice is 507 employees."
    )
    assert extract_layoff_count(text) == 507


def test_dates_and_day_numbers_are_not_counts():
    text = (
        "On July 3 2026 all employees will be terminated. "
        "Employees were notified within 60 days."
    )
    assert extract_layoff_count(text) is None


def test_no_number_returns_none():
    # Parkhurst (WV): "all Company employees", never quantified.
    text = (
        "The cessation of Company operations at the site will result in the "
        "termination of all Company employees at the site."
    )
    assert extract_layoff_count(text) is None


def test_year_like_count_rejected():
    text = "This action will affect 2026 employees."
    assert extract_layoff_count(text) is None


def test_empty_text_returns_none():
    assert extract_layoff_count("") is None


# ---------------------------------------------------------------------------
# extract_layoff_count — position tables (tier 4)
# ---------------------------------------------------------------------------

def test_table_sum_with_page_footer_excluded():
    text = (
        "Position Titles Number Impacted\n"
        "Customer Experience Associate I 1\n"
        "Supervisor, Delivery 1\n"
        "WARN - RRT/June 2026 Page 2\n"
    )
    assert extract_layoff_count(text) == 2


def test_table_rows_with_trailing_dates():
    text = (
        "# Employees Expected Termination\n"
        "Job Title Impacted Date\n"
        "VP Clinical Strat Ops 1 7/3/2026\n"
        "Sr. Analyst, Project Mgt 2 7/3/2026\n"
        "Ramp Agent 64 August 19, 2026\n"
    )
    assert extract_layoff_count(text) == 67


def test_table_grand_total_beats_row_sum():
    text = (
        "Department Classification Total\n"
        "Number of Employees\n"
        "Assembly Machine Operator 32\n"
        "Assembly Setter 19\n"
        "Grand Total 300\n"
    )
    assert extract_layoff_count(text) == 300


def test_table_subtotals_without_grand_total_are_ambiguous():
    text = (
        "Number of Employees\n"
        "Assembly Machine Operator 32\n"
        "Assembly Total 57\n"
        "Molding Setter 6\n"
    )
    assert extract_layoff_count(text) is None


def test_redacted_table_returns_none():
    # Sodexo (HI): count column blacked out before publication.
    text = (
        "Job Title Number of Employees\n"
        "Cashier/Food Service Worker\n"
        "Chef Manager\n"
        "Cook I\n"
    )
    assert extract_layoff_count(text) is None


def test_prose_total_beats_nationwide_table():
    # JeniusBank (WV): the table spans every state; prose has the WV total.
    text = (
        "The total number of affected employees in West Virginia is one.\n"
        "Job Title Number of Affected Individuals\n"
        "Fraud Support Representative 15\n"
        "Operations Specialist 9\n"
    )
    assert extract_layoff_count(text) == 1


# ---------------------------------------------------------------------------
# Real letters, text layer (CT + WV)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("ct/guida_seibert_2026.pdf", 205),      # prose: "will affect 205 employees"
        ("ct/g2_secure_staffing_2026.pdf", 100),  # prose: "100 ... positions eliminated"
        ("ct/conduent_remote_2026.pdf", 2),       # table-only letter
        ("ct/cvs_health_2026.pdf", 6),            # table rows with trailing dates
        ("wv/conduent_2026.pdf", 6),              # WV variant of the table letter
    ],
)
def test_real_text_layer_letters(fixture: str, expected: int):
    text = _extract_text((FIXTURES / fixture).read_bytes())
    assert text.strip(), f"{fixture} should have a text layer"
    assert extract_layoff_count(text) == expected


# ---------------------------------------------------------------------------
# Real scanned letters (HI + WV) — no text layer, OCR branch
# ---------------------------------------------------------------------------

_SCANNED = [
    # (fixture, transcribed letter text fed back as the OCR result, expected)
    (
        "wv/greenbrier_minerals_2026_scanned.pdf",
        "Greenbrier Minerals will begin permanently laying off approximately "
        "530 Greenbrier Minerals employees at the Mine.",
        530,
    ),
    (
        "wv/wvu_research_2025_scanned.pdf",
        "This mass layoff will affect every employe of WVURC, which at the "
        "time of the submission of this notice is 507 employees.",
        507,
    ),
    (
        "hi/ben_bridge_2026_scanned.pdf",
        "Number of employees at Store: 8\n"
        "Approximate number of\nemployees to be laid off: 8",
        8,
    ),
    (
        "hi/jinya_2025_scanned.pdf",
        "The number of employees employed by the establishment is 86.\n"
        "All employee positions at this location will be eliminated upon the "
        "restaurant's closing.",
        None,  # headcount only — conservatively left NULL
    ),
]


@pytest.mark.parametrize(("fixture", "ocr_text", "expected"), _SCANNED)
def test_real_scanned_letters_take_ocr_path(
    fixture: str, ocr_text: str, expected: int | None
):
    pdf_bytes = (FIXTURES / fixture).read_bytes()
    with patch(
        "warn_v2.pdf_extract._ocr_text", return_value=ocr_text
    ) as mock_ocr:
        text = _extract_text(pdf_bytes)
    # The scanned fixture must genuinely lack a text layer, so extraction
    # reached OCR — the branch prod relies on for these states.
    mock_ocr.assert_called_once()
    assert extract_layoff_count(text) == expected


# ---------------------------------------------------------------------------
# backfill_layoff_counts
# ---------------------------------------------------------------------------

def _notice(
    db,
    *,
    notice_id: str,
    state: str = "CT",
    layoff_count: int | None = None,
    pdf_path: str | None = None,
) -> Notice:
    n = Notice(
        notice_id=notice_id,
        state=state,
        employer="Acme",
        layoff_count=layoff_count,
        pdf_path=pdf_path,
    )
    db.add(n)
    db.flush()
    return n


def _stage_pdf(pdf_dir: Path, rel: str, fixture: str) -> str:
    """Copy a fixture into the fake PVC layout; returns the relative pdf_path."""
    dest = pdf_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes((FIXTURES / fixture).read_bytes())
    return rel


def _no_count_pdf(pdf_dir: Path, rel: str) -> str:
    """A real text-layer PDF whose letter states no count."""
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "This closure will result in the termination of all Company "
        "employees at the site.",
    )
    dest = pdf_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(dest))
    doc.close()
    return rel


def test_backfill_fills_null_count_from_pdf(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ct/guida.pdf", "ct/guida_seibert_2026.pdf")
    _notice(db, notice_id="ct-1", pdf_path=rel)
    db.commit()

    stats = backfill_layoff_counts(pdf_dir=tmp_path)
    assert stats == {
        "considered": 1, "filled": 1, "no_count": 0,
        "no_text": 0, "missing": 0, "errors": 0,
    }

    db.expire_all()
    assert db.get(Notice, "ct-1").layoff_count == 205


def test_backfill_never_overwrites_existing_count(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ct/guida.pdf", "ct/guida_seibert_2026.pdf")
    _notice(db, notice_id="ct-has-count", layoff_count=42, pdf_path=rel)
    db.commit()

    stats = backfill_layoff_counts(pdf_dir=tmp_path)
    assert stats["considered"] == 0  # NULL-only query never sees it

    db.expire_all()
    assert db.get(Notice, "ct-has-count").layoff_count == 42


def test_backfill_dry_run_writes_nothing(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ct/guida.pdf", "ct/guida_seibert_2026.pdf")
    _notice(db, notice_id="ct-dry", pdf_path=rel)
    db.commit()

    stats = backfill_layoff_counts(dry_run=True, pdf_dir=tmp_path)
    assert stats["filled"] == 1  # counted

    db.expire_all()
    assert db.get(Notice, "ct-dry").layoff_count is None  # unchanged


def test_backfill_defaults_to_pdf_only_states(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ca/some.pdf", "ct/guida_seibert_2026.pdf")
    _notice(db, notice_id="ca-1", state="CA", pdf_path=rel)
    db.commit()

    stats = backfill_layoff_counts(pdf_dir=tmp_path)
    assert stats["considered"] == 0

    # But an explicit --state widens the scope.
    stats = backfill_layoff_counts("CA", pdf_dir=tmp_path)
    assert stats["filled"] == 1


def test_backfill_state_filter(db, tmp_path: Path):
    ct_rel = _stage_pdf(tmp_path, "ct/guida.pdf", "ct/guida_seibert_2026.pdf")
    wv_rel = _stage_pdf(tmp_path, "wv/conduent.pdf", "wv/conduent_2026.pdf")
    _notice(db, notice_id="ct-2", state="CT", pdf_path=ct_rel)
    _notice(db, notice_id="wv-2", state="WV", pdf_path=wv_rel)
    db.commit()

    stats = backfill_layoff_counts("WV", pdf_dir=tmp_path)
    assert stats == {
        "considered": 1, "filled": 1, "no_count": 0,
        "no_text": 0, "missing": 0, "errors": 0,
    }

    db.expire_all()
    assert db.get(Notice, "wv-2").layoff_count == 6
    assert db.get(Notice, "ct-2").layoff_count is None


def test_backfill_skips_notices_without_pdf(db, tmp_path: Path):
    _notice(db, notice_id="ct-no-pdf", pdf_path=None)
    db.commit()

    stats = backfill_layoff_counts(pdf_dir=tmp_path)
    assert stats["considered"] == 0


def test_backfill_missing_file_counted_not_fatal(db, tmp_path: Path):
    _notice(db, notice_id="ct-gone", pdf_path="ct/vanished.pdf")
    db.commit()

    stats = backfill_layoff_counts(pdf_dir=tmp_path)
    assert stats["missing"] == 1
    assert stats["filled"] == 0


def test_backfill_ambiguous_letter_stays_null(db, tmp_path: Path):
    rel = _no_count_pdf(tmp_path, "wv/parkhurst_like.pdf")
    _notice(db, notice_id="wv-null", state="WV", pdf_path=rel)
    db.commit()

    stats = backfill_layoff_counts(pdf_dir=tmp_path)
    assert stats["no_count"] == 1

    db.expire_all()
    assert db.get(Notice, "wv-null").layoff_count is None


def test_backfill_scanned_pdf_without_ocr_stack_counts_no_text(db, tmp_path: Path):
    # In the test env tesseract/pdf2image are absent, so a scanned PDF yields
    # no text — the notice is skipped (and stays NULL) rather than erroring.
    rel = _stage_pdf(tmp_path, "hi/jinya.pdf", "hi/jinya_2025_scanned.pdf")
    _notice(db, notice_id="hi-1", state="HI", pdf_path=rel)
    db.commit()

    stats = backfill_layoff_counts(pdf_dir=tmp_path)
    assert stats["no_text"] == 1

    db.expire_all()
    assert db.get(Notice, "hi-1").layoff_count is None
