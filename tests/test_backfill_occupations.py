"""Tests for extract_occupations + the backfill-occupations command.

The extractor shares the tier-4 table scan with extract_layoff_count (see
test_backfill_layoff_counts.py for the scan's own edge cases); these tests
pin the per-row contract — titles captured, cleaned, and merged, and rows
released only when they sum to the table's accepted total. Fixture PDFs are
the same real WARN letters under ``warn_v2/scrapers/fixtures/``.
"""
from __future__ import annotations

from pathlib import Path

from warn_v2.db.models import Notice, NoticeOccupation
from warn_v2.pdf_extract import _extract_text, extract_occupations
from warn_v2.scripts.backfill_occupations import backfill_occupations

FIXTURES = (
    Path(__file__).resolve().parent.parent / "warn_v2" / "scrapers" / "fixtures"
)


# ---------------------------------------------------------------------------
# extract_occupations — synthetic tables
# ---------------------------------------------------------------------------

def test_simple_table_rows_with_footer():
    text = (
        "Position Titles Number Impacted\n"
        "Customer Experience Associate I 1\n"
        "Supervisor, Delivery 1\n"
        "WARN - RRT/June 2026 Page 2\n"
    )
    assert extract_occupations(text) == [
        ("Customer Experience Associate I", 1),
        ("Supervisor, Delivery", 1),
    ]


def test_table_rows_with_trailing_dates_drop_the_date():
    text = (
        "# Employees Expected Termination\n"
        "Job Title Impacted Date\n"
        "VP Clinical Strat Ops 1 7/3/2026\n"
        "Ramp Agent 64 August 19, 2026\n"
    )
    assert extract_occupations(text) == [
        ("VP Clinical Strat Ops", 1),
        ("Ramp Agent", 64),
    ]


def test_grand_total_matching_rows_keeps_rows():
    text = (
        "Number of Employees Impacted\n"
        "Assembly Machine Operator 32\n"
        "Assembly Setter 19\n"
        "Grand Total 51\n"
    )
    assert extract_occupations(text) == [
        ("Assembly Machine Operator", 32),
        ("Assembly Setter", 19),
    ]


def test_grand_total_mismatch_discards_rows():
    # The stated total is trustworthy (extract_layoff_count returns 300) but
    # the parsed rows clearly missed positions — per-row data is unusable.
    text = (
        "Number of Employees Impacted\n"
        "Assembly Machine Operator 32\n"
        "Assembly Setter 19\n"
        "Grand Total 300\n"
    )
    assert extract_occupations(text) == []


def test_subtotals_without_grand_total_yield_nothing():
    text = (
        "Number of Employees Impacted\n"
        "Assembler 30\n"
        "Subtotal 30\n"
        "Painter 6\n"
    )
    assert extract_occupations(text) == []


def test_poisoned_table_yields_nothing():
    text = (
        "Job Title Number of Affected Individuals\n"
        "Pharmacy Technician 4\n"
        "Pharmacist 3\n"
        "If you have any questions call our office at Building 3 Room 312\n"
    )
    assert extract_occupations(text) == []


def test_single_row_table_yields_nothing():
    text = "Number of Employees Impacted\nAssembler 30\n"
    assert extract_occupations(text) == []


def test_duplicate_titles_merged_summing_counts():
    # Multi-site letters repeat a title per worksite; one row per title with
    # the counts summed, first-seen order (and casing) preserved.
    text = (
        "Position Titles Number Impacted\n"
        "Machinist 12\n"
        "Welder 3\n"
        "MACHINIST 5\n"
    )
    assert extract_occupations(text) == [("Machinist", 17), ("Welder", 3)]


def test_titles_cleaned_of_enumeration_and_separators():
    text = (
        "Position Titles Number Impacted\n"
        "1. Machinist   Grade II 12\n"
        "2) Welder - 3\n"
    )
    assert extract_occupations(text) == [("Machinist Grade II", 12), ("Welder", 3)]


def test_enumeration_trim_keeps_leading_alphanumerics():
    text = (
        "Position Titles Number Impacted\n"
        "3D Printer Operator 4\n"
        "2nd Shift Supervisor 2\n"
    )
    assert extract_occupations(text) == [
        ("3D Printer Operator", 4),
        ("2nd Shift Supervisor", 2),
    ]


def test_no_table_yields_nothing():
    assert extract_occupations("") == []
    assert extract_occupations("This action will affect 205 employees.") == []


# ---------------------------------------------------------------------------
# extract_occupations — real letters (text layer)
# ---------------------------------------------------------------------------

def test_real_table_letter_ct_conduent():
    text = _extract_text((FIXTURES / "ct/conduent_remote_2026.pdf").read_bytes())
    assert extract_occupations(text) == [
        ("Customer Experience Associate I", 1),
        ("Supervisor, Delivery", 1),
    ]


def test_real_table_letter_ct_cvs_health():
    text = _extract_text((FIXTURES / "ct/cvs_health_2026.pdf").read_bytes())
    occs = extract_occupations(text)
    assert len(occs) == 6
    assert sum(c for _, c in occs) == 6
    assert occs[0] == ("VP Clinical Strat Ops", 1)


def test_real_table_letter_wv_conduent():
    text = _extract_text((FIXTURES / "wv/conduent_2026.pdf").read_bytes())
    assert extract_occupations(text) == [
        ("Customer Experience Associate I", 3),
        ("Customer Experience Associate II", 3),
    ]


def test_real_prose_letter_yields_nothing():
    # Prose-only letter: a count exists but no positions table.
    text = _extract_text((FIXTURES / "ct/guida_seibert_2026.pdf").read_bytes())
    assert extract_occupations(text) == []


# ---------------------------------------------------------------------------
# backfill_occupations
# ---------------------------------------------------------------------------

def _notice(
    db,
    *,
    notice_id: str,
    state: str = "CT",
    pdf_path: str | None = None,
) -> Notice:
    n = Notice(
        notice_id=notice_id,
        state=state,
        employer="Acme",
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


def _rows(db, notice_id: str) -> list[tuple[str, int]]:
    n = db.get(Notice, notice_id)
    return [(o.job_title, o.count) for o in n.occupations]


def test_backfill_fills_rows_from_pdf(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ct/conduent.pdf", "ct/conduent_remote_2026.pdf")
    _notice(db, notice_id="ct-1", pdf_path=rel)
    db.commit()

    stats = backfill_occupations(pdf_dir=tmp_path)
    assert stats == {
        "considered": 1, "filled": 1, "no_table": 0,
        "no_text": 0, "missing": 0, "errors": 0,
    }

    db.expire_all()
    assert _rows(db, "ct-1") == [
        ("Customer Experience Associate I", 1),
        ("Supervisor, Delivery", 1),
    ]


def test_backfill_skips_notices_with_existing_rows(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ct/conduent.pdf", "ct/conduent_remote_2026.pdf")
    n = _notice(db, notice_id="ct-has-rows", pdf_path=rel)
    n.occupations = [NoticeOccupation(job_title="Existing Role", count=9)]
    db.commit()

    stats = backfill_occupations(pdf_dir=tmp_path)
    assert stats["considered"] == 0  # fill-only query never sees it

    db.expire_all()
    assert _rows(db, "ct-has-rows") == [("Existing Role", 9)]


def test_backfill_dry_run_writes_nothing(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ct/conduent.pdf", "ct/conduent_remote_2026.pdf")
    _notice(db, notice_id="ct-dry", pdf_path=rel)
    db.commit()

    stats = backfill_occupations(dry_run=True, pdf_dir=tmp_path)
    assert stats["filled"] == 1  # counted

    db.expire_all()
    assert _rows(db, "ct-dry") == []  # unchanged


def test_backfill_state_filter(db, tmp_path: Path):
    ct_rel = _stage_pdf(tmp_path, "ct/conduent.pdf", "ct/conduent_remote_2026.pdf")
    wv_rel = _stage_pdf(tmp_path, "wv/conduent.pdf", "wv/conduent_2026.pdf")
    _notice(db, notice_id="ct-2", state="CT", pdf_path=ct_rel)
    _notice(db, notice_id="wv-2", state="WV", pdf_path=wv_rel)
    db.commit()

    stats = backfill_occupations("WV", pdf_dir=tmp_path)
    assert stats["considered"] == 1
    assert stats["filled"] == 1

    db.expire_all()
    assert _rows(db, "wv-2") == [
        ("Customer Experience Associate I", 3),
        ("Customer Experience Associate II", 3),
    ]
    assert _rows(db, "ct-2") == []


def test_backfill_counts_tableless_letters(db, tmp_path: Path):
    rel = _stage_pdf(tmp_path, "ct/guida.pdf", "ct/guida_seibert_2026.pdf")
    _notice(db, notice_id="ct-prose", pdf_path=rel)
    db.commit()

    stats = backfill_occupations(pdf_dir=tmp_path)
    assert stats == {
        "considered": 1, "filled": 0, "no_table": 1,
        "no_text": 0, "missing": 0, "errors": 0,
    }


def test_backfill_missing_file(db, tmp_path: Path):
    _notice(db, notice_id="ct-gone", pdf_path="ct/vanished.pdf")
    db.commit()

    stats = backfill_occupations(pdf_dir=tmp_path)
    assert stats["missing"] == 1
    assert stats["filled"] == 0
