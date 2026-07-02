"""Tests for backfill_ny_layoff_counts — fill NULL NY counts from WARN UNIT PDFs."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import respx

from warn_v2.db.models import Notice
from warn_v2.pdf_extract import _extract_text
from warn_v2.scripts.backfill_ny_layoff_counts import (
    backfill_ny_layoff_counts,
    extract_affected_workers,
)

# Real NY DOL WARN UNIT summary PDF (Plug Power, notice date 2025-03-25):
# three impacted sites, "Total Number of Affected Workers: 261".
PDF_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "warn_v2"
    / "scrapers"
    / "fixtures"
    / "ny"
    / "warn_unit_sample.pdf"
)

_NY_URL = "https://dol.ny.gov/warn-acme-region-capital-date-posted-1152025"


def _notice(
    db,
    *,
    notice_id: str,
    state: str = "NY",
    layoff_count: int | None = None,
    raw_notice_url: str | None = _NY_URL,
    pdf_path: str | None = None,
) -> Notice:
    n = Notice(
        notice_id=notice_id,
        state=state,
        employer="Acme Corp",
        notice_date=date(2025, 1, 15),
        layoff_count=layoff_count,
        raw_notice_url=raw_notice_url,
        pdf_path=pdf_path,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# extract_affected_workers — pure text parsing
# ---------------------------------------------------------------------------


def test_extract_count_from_fixture_pdf() -> None:
    text = _extract_text(PDF_FIXTURE.read_bytes())
    assert extract_affected_workers(text) == 261


def test_total_line_wins_over_site_sum() -> None:
    # Amended notices can disagree; the notice-level total is authoritative.
    text = (
        "Total Number of Affected Workers: 99\n"
        "Number of Affected Employees at Site: 105\n"
    )
    assert extract_affected_workers(text) == 99


def test_total_with_thousands_separator() -> None:
    assert extract_affected_workers("Total Number of Affected Workers: 1,380") == 1380


def test_site_sum_fallback_when_no_total() -> None:
    text = (
        "Number of Affected Employees at Site: 180\n"
        "Number of Affected Workers at Site: 79\n"
    )
    assert extract_affected_workers(text) == 259


def test_no_count_returns_none() -> None:
    assert extract_affected_workers("Dear Commissioner, we regret to inform...") is None
    assert extract_affected_workers("") is None


def test_insane_counts_rejected() -> None:
    assert extract_affected_workers("Total Number of Affected Workers: 0") is None
    assert extract_affected_workers("Total Number of Affected Workers: 999,999") is None


# ---------------------------------------------------------------------------
# backfill_ny_layoff_counts — DB behaviour
# ---------------------------------------------------------------------------


def test_fills_from_stored_pdf(db, tmp_path) -> None:
    """A notice whose PDF is already on the PVC is filled without any network."""
    (tmp_path / "ny").mkdir()
    (tmp_path / "ny" / "n1.pdf").write_bytes(PDF_FIXTURE.read_bytes())
    _notice(db, notice_id="n1", pdf_path="ny/n1.pdf")
    db.commit()

    stats = backfill_ny_layoff_counts(pdf_dir=tmp_path)

    assert stats == {"considered": 1, "filled": 1, "no_count": 0, "errors": 0}
    db.expire_all()
    assert db.get(Notice, "n1").layoff_count == 261


@respx.mock
def test_fetches_url_when_no_stored_pdf(db, tmp_path) -> None:
    _notice(db, notice_id="n2", pdf_path=None)
    db.commit()

    respx.get(_NY_URL).mock(
        return_value=httpx.Response(200, content=PDF_FIXTURE.read_bytes())
    )

    stats = backfill_ny_layoff_counts(pdf_dir=tmp_path)

    assert stats["filled"] == 1
    db.expire_all()
    assert db.get(Notice, "n2").layoff_count == 261


def test_never_touches_non_null_counts(db, tmp_path) -> None:
    """Fill-only: a notice that already has a count is not in the candidate set."""
    (tmp_path / "ny").mkdir()
    (tmp_path / "ny" / "n3.pdf").write_bytes(PDF_FIXTURE.read_bytes())
    _notice(db, notice_id="n3", layoff_count=42, pdf_path="ny/n3.pdf")
    db.commit()

    stats = backfill_ny_layoff_counts(pdf_dir=tmp_path)

    assert stats["considered"] == 0
    db.expire_all()
    assert db.get(Notice, "n3").layoff_count == 42


def test_only_ny_notices_considered(db, tmp_path) -> None:
    _notice(db, notice_id="ca-1", state="CA")
    _notice(db, notice_id="no-url", raw_notice_url=None)
    db.commit()

    stats = backfill_ny_layoff_counts(pdf_dir=tmp_path)
    assert stats["considered"] == 0


def test_dry_run_writes_nothing(db, tmp_path) -> None:
    (tmp_path / "ny").mkdir()
    (tmp_path / "ny" / "n4.pdf").write_bytes(PDF_FIXTURE.read_bytes())
    _notice(db, notice_id="n4", pdf_path="ny/n4.pdf")
    db.commit()

    stats = backfill_ny_layoff_counts(dry_run=True, pdf_dir=tmp_path)

    assert stats["filled"] == 1  # counted
    db.expire_all()
    assert db.get(Notice, "n4").layoff_count is None  # unchanged


@respx.mock
def test_countless_pdf_counted_not_errored(db, tmp_path) -> None:
    """A PDF without the WARN UNIT fields is reported as no_count, not filled."""
    _notice(db, notice_id="n5")
    db.commit()

    respx.get(_NY_URL).mock(
        return_value=httpx.Response(200, content=b"%PDF-1.4 no text layer")
    )

    stats = backfill_ny_layoff_counts(pdf_dir=tmp_path)

    assert stats == {"considered": 1, "filled": 0, "no_count": 1, "errors": 0}
    db.expire_all()
    assert db.get(Notice, "n5").layoff_count is None


@respx.mock
def test_fetch_failure_counts_error_and_continues(db, tmp_path) -> None:
    """One dead URL doesn't stop the run; the stored-PDF notice still fills."""
    _notice(db, notice_id="dead", raw_notice_url="https://dol.ny.gov/warn-dead")
    (tmp_path / "ny").mkdir()
    (tmp_path / "ny" / "ok.pdf").write_bytes(PDF_FIXTURE.read_bytes())
    _notice(db, notice_id="ok", pdf_path="ny/ok.pdf")
    db.commit()

    respx.get("https://dol.ny.gov/warn-dead").mock(
        return_value=httpx.Response(404)
    )

    stats = backfill_ny_layoff_counts(pdf_dir=tmp_path)

    assert stats["errors"] == 1
    assert stats["filled"] == 1
    db.expire_all()
    assert db.get(Notice, "ok").layoff_count == 261


@respx.mock
def test_html_response_counts_error(db, tmp_path) -> None:
    """A URL that resolves to an HTML page (not a PDF) is an error, not a fill."""
    _notice(db, notice_id="html")
    db.commit()

    respx.get(_NY_URL).mock(
        return_value=httpx.Response(
            200, content=b"<html>...</html>", headers={"content-type": "text/html"}
        )
    )

    stats = backfill_ny_layoff_counts(pdf_dir=tmp_path)
    assert stats == {"considered": 1, "filled": 0, "no_count": 0, "errors": 1}
