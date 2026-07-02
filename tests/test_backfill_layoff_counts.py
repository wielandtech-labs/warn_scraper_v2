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
    # Distinct numbers so a match on the headcount line would fail the test.
    text = (
        "Number of employees at Store: 12\n"
        "Approximate number of\nemployees to be laid off: 8\n"
    )
    assert extract_layoff_count(text) == 8


def test_phone_number_fragment_is_not_a_count():
    # Wahiawa General Hospital (HI, prod dry-run): the HR contact's phone
    # ("808-621-4272") must not beat the labeled total — which itself needs
    # to tolerate a company abbreviation between "affected" and "employees".
    text = (
        "Contact Person: Lori Foster Human Resources Director 808-621-4272\n"
        "Date of position eliminations/closing: April 2, 2024\n"
        "Total number of affected WGH employees: 291"
    )
    assert extract_layoff_count(text) == 291


def test_line_wrapped_phone_number_is_not_a_count():
    # OCR wrapping a phone mid-number leaves "943- 6670" after whitespace
    # flattening — still a fragment, not a count.
    text = (
        "This closure will impact operations. Call the site at 808-943-\n"
        "6670 to reach the affected employees hotline."
    )
    assert extract_layoff_count(text) is None


def test_unicode_hyphen_phone_is_not_a_count():
    # pdfminer's ToUnicode mapping can emit U+2010 HYPHEN inside phones.
    hyphen = chr(0x2010)
    text = (
        f"This closure will impact staffing. Call 808{hyphen}943{hyphen}6670 "
        "to reach the affected employees hotline."
    )
    assert extract_layoff_count(text) is None


def test_em_dash_before_count_still_extracts():
    # En/em dashes punctuate prose right before real counts and never join
    # phone digits — they must not trip the joiner guard.
    text = "As part of the closing—75 employees will be permanently laid off."
    assert extract_layoff_count(text) == 75


def test_affected_and_unaffected_combined_figure_stays_null():
    # The pattern-3 gap must not dilute "affected" with lowercase
    # connectives into a combined/establishment figure.
    text = (
        "The total number of affected and unaffected employees at the site "
        "is 500."
    )
    assert extract_layoff_count(text) is None


def test_letterhead_phone_vs_laid_off_or_terminated():
    # University Health Partners (HI, prod dry-run): letterhead phone
    # "(808) 469-4900" must lose to "to be laid off or terminated: 120";
    # the establishment headcount (480) must not match either.
    text = (
        "677 Ala Moana Boulevard, Suite 1001, Honolulu, HI 96813 (808) 469-4900\n"
        "UHP will be experiencing a reduction in its workforce. As a result "
        "of this action, many of our current employees whose positions will "
        "be impacted by this restructuring will have employment offered to "
        "them through Queen's.\n"
        "Number of employees at covered establishment:\n480\n"
        "Approximate number of employees to be laid off or terminated:\n120"
    )
    assert extract_layoff_count(text) == 120


def test_store_phone_in_attachment_is_not_a_count():
    # Islands Restaurants (HI, prod dry-run): the store phone "808-943-6670"
    # sat three gap-tokens before "Employees" in OCR-flattened text.
    text = (
        "List of Islands Restaurants in Hawaii impacted by Government "
        "mandated shutdown Store # Store Name Address City State Zip County "
        "Store Phone #057 Ala Moana 1450 Ala Moana Blvd., #4230, Honolulu HI "
        "96814 Honolulu 808-943-6670 Exhibit B Furloughed Employees/Restaurant "
        "# of Furloughed Employees Restaurant Location"
    )
    assert extract_layoff_count(text) is None


def test_contact_phone_before_positions_table_loses_to_table():
    # Durham School Services (CT, prod dry-run): "203-269-4171" directly
    # preceded "The following positions are affected:" — the phone must be
    # rejected so the position table (sum 27) wins.
    text = (
        "990 Northrup Rd, Wallingford, CT 06492\n"
        "203-269-4171\n"
        "The following positions are affected:\n"
        "Position # of affected Employees First Date of Anticipated\n"
        "Bus Assistant 17 June 15, 2022\n"
        "Casual Driver 6 June 15, 2022\n"
        "Driver In Training 4 June 15, 2022\n"
    )
    assert extract_layoff_count(text) == 27


def test_roughly_n_positions_laid_off():
    # Kyoya Ohana (HI, prod dry-run): verified-legitimate large count.
    text = (
        "Roughly 3000 positions have been or will be temporarily laid off "
        "starting March 12, 2020."
    )
    assert extract_layoff_count(text) == 3000


def test_employs_a_total_of_is_headcount_not_layoff():
    text = (
        "The facility currently employs a total of 500 employees. "
        "Approximately 25 employees will be laid off."
    )
    assert extract_layoff_count(text) == 25


def test_total_workforce_of_is_headcount_not_layoff():
    text = (
        "The site has a total workforce of 500 employees. "
        "Approximately 25 employees will be affected."
    )
    assert extract_layoff_count(text) == 25


def test_employs_total_with_unquantified_action_stays_null():
    text = (
        "The Company employs a total of 86 employees at the restaurant. "
        "All positions will be eliminated."
    )
    assert extract_layoff_count(text) is None


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


def test_day_first_date_is_not_a_count():
    assert extract_layoff_count("On 3 July all employees will be terminated.") is None


def test_notice_period_boilerplate_is_not_a_count():
    text = (
        "The Company is providing 60 days' notice to employees affected by "
        "this closure. A list of positions is attached."
    )
    assert extract_layoff_count(text) is None


def test_dollar_amount_is_not_a_count():
    text = (
        "Each employee will receive a $500 payment to employees who will "
        "be terminated."
    )
    assert extract_layoff_count(text) is None


def test_comma_thousands_count_is_not_a_year():
    text = "This action will affect approximately 1,900 employees at the plant."
    assert extract_layoff_count(text) == 1900


def test_word_tail_is_not_an_is_verb():
    # "th-is 3" must not satisfy the "... is N" total pattern.
    text = (
        "The total number of affected employees for this 3 facility closure "
        "has not been determined."
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


def test_subtotal_word_variant_also_ambiguous():
    text = (
        "Number of Employees Impacted\n"
        "Assembler 30\n"
        "Welder 27\n"
        "Subtotal 57\n"
        "Painter 6\n"
    )
    assert extract_layoff_count(text) is None


def test_prose_mention_of_count_column_is_not_a_table_header():
    # A sentence about the count must not open a table scan that then sums
    # a later address line ("Suite 200").
    text = (
        "The number of employees affected by this action cannot yet be "
        "determined.\n"
        "Please contact Jane Doe, 100 Main Plaza, Suite 200\n"
    )
    assert extract_layoff_count(text) is None


def test_contact_line_after_table_poisons_sum():
    text = (
        "Job Title Number of Affected Individuals\n"
        "Pharmacy Technician 4\n"
        "Pharmacist 3\n"
        "If you have any questions call our office at Building 3 Room 312\n"
    )
    assert extract_layoff_count(text) is None


def test_four_digit_row_poisons_table():
    text = (
        "Number of Employees Impacted\n"
        "Assembler 1200\n"
        "Setter 30\n"
    )
    assert extract_layoff_count(text) is None


def test_wrapped_row_fragment_poisons_table():
    # A wrapped row ("... Associate" / "I 1") must yield None, not an
    # undersum that silently drops the wrapped position.
    text = (
        "Position Titles Number Impacted\n"
        "Customer Experience Associate I 1\n"
        "Customer Experience Associate II 1\n"
        "Customer Experience Associate\n"
        "I 1\n"
    )
    assert extract_layoff_count(text) is None


def test_single_row_table_not_trusted():
    text = "Number of Employees Impacted\nAssembler 30\n"
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
