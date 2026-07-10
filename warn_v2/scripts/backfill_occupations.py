"""Fill ``notice_occupations`` from stored per-notice PDFs.

Many WARN letter PDFs carry a "Position Titles / Number Impacted" table
naming the actual eliminated roles with per-title counts (empirically most
of OH/FL/WI/CT/NE/AK stored PDFs, some GA/IN; scanned VA/HI/WV letters go
through the OCR fallback). ``download-pdfs`` persists these for newly
fetched PDFs; this backfill sweeps the PDFs already stored on the PVC
through the same conservative table parser
(:func:`warn_v2.pdf_extract.extract_occupations`) and writes the rows.
Fill-only — notices that already have occupation rows drop out of the
candidate set, so re-runs are cheap and idempotent.

Run via:
  warn-v2 backfill-occupations --dry-run
  warn-v2 backfill-occupations
  warn-v2 backfill-occupations --state OH
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from warn_v2.db.models import Notice, NoticeOccupation
from warn_v2.db.session import session_scope
from warn_v2.pdf_extract import _extract_text, extract_occupations

log = logging.getLogger(__name__)

_BATCH_COMMIT = 50


def backfill_occupations(
    state: str | None = None,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    pdf_dir: Path = Path("/var/pdfs"),
) -> dict[str, int]:
    """Fill occupation rows for stored-PDF notices that have none; returns stats.

    Returns ``{"considered": N, "filled": N, "no_table": N, "no_text": N,
    "missing": N, "errors": N}``. ``no_text`` counts PDFs where neither the
    text layer nor OCR produced text; ``no_table`` counts letters with no
    clean positions table (absent, poisoned, or rows inconsistent with the
    stated total — skipped by design).
    """
    stats = {
        "considered": 0, "filled": 0, "no_table": 0,
        "no_text": 0, "missing": 0, "errors": 0,
    }

    stmt = select(Notice).where(
        Notice.pdf_path.isnot(None),
        ~Notice.occupations.any(),
    )
    if state is not None:
        stmt = stmt.where(Notice.state == state.upper())
    stmt = stmt.order_by(Notice.notice_date.desc().nullslast())
    if limit is not None:
        stmt = stmt.limit(limit)

    with session_scope() as session:
        pending_commit = 0
        for notice in session.scalars(stmt):
            stats["considered"] += 1
            abs_path = pdf_dir / notice.pdf_path
            try:
                pdf_bytes = abs_path.read_bytes()
            except OSError:
                log.warning(
                    "%s %s: stored file %s missing — skipping",
                    notice.state, notice.notice_id[:8], notice.pdf_path,
                )
                stats["missing"] += 1
                continue

            try:
                text = _extract_text(pdf_bytes)
            except Exception as e:
                log.warning(
                    "%s %s: text extraction failed: %s",
                    notice.state, notice.notice_id[:8], e,
                )
                stats["errors"] += 1
                continue

            if not text.strip():
                stats["no_text"] += 1
                continue

            occupations = extract_occupations(text)
            if not occupations:
                stats["no_table"] += 1
                continue

            log.info(
                "%s %s: %d occupation row(s), sum=%d (%s)",
                notice.state, notice.notice_id[:8], len(occupations),
                sum(c for _, c in occupations), notice.employer[:40],
            )
            stats["filled"] += 1
            if not dry_run:
                notice.occupations = [
                    NoticeOccupation(job_title=title, count=count)
                    for title, count in occupations
                ]
                pending_commit += 1
                if pending_commit >= _BATCH_COMMIT:
                    session.commit()
                    pending_commit = 0

        if pending_commit:
            session.commit()

    log.info(
        "backfill-occupations done: considered=%d filled=%d no_table=%d "
        "no_text=%d missing=%d errors=%d",
        stats["considered"], stats["filled"], stats["no_table"],
        stats["no_text"], stats["missing"], stats["errors"],
    )
    return stats
