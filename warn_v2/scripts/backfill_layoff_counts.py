"""Fill NULL ``layoff_count`` from stored per-notice PDFs.

CT, HI, and WV publish no worker counts on their listing pages — CT is a
per-notice PDF blob library, HI a page of PDF links, WV an employer+date
anchor list. The count exists only inside the letter PDFs, which
``download-pdfs`` already stores on the PVC. This backfill re-reads those
PDFs (pdfplumber text layer, OCR fallback for the scanned HI/WV letters) and
fills ``layoff_count`` via the conservative extractor
(:func:`warn_v2.pdf_extract.extract_layoff_count`): explicit totals
preferred, NULL kept on ambiguity. Fill-only — the query targets NULLs, so
an existing count is never overwritten.

Run via:
  warn-v2 backfill-layoff-counts --dry-run
  warn-v2 backfill-layoff-counts
  warn-v2 backfill-layoff-counts --state CT
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select

from warn_v2.db.models import Notice
from warn_v2.db.session import session_scope
from warn_v2.pdf_extract import _extract_text, extract_layoff_count

log = logging.getLogger(__name__)

# States whose listings publish no counts; their counts live only in the
# stored per-notice PDFs.
PDF_ONLY_COUNT_STATES = ("CT", "HI", "WV")

_BATCH_COMMIT = 50


def backfill_layoff_counts(
    state: str | None = None,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    pdf_dir: Path = Path("/var/pdfs"),
) -> dict[str, int]:
    """Fill NULL layoff_count for notices with a stored PDF; returns stats.

    Returns ``{"considered": N, "filled": N, "no_count": N, "no_text": N,
    "missing": N, "errors": N}``. ``no_text`` counts PDFs where neither the
    text layer nor OCR produced text (OCR needs the tesseract/poppler stack
    in the image); ``no_count`` counts letters where no unambiguous total was
    found (left NULL by design).
    """
    stats = {
        "considered": 0, "filled": 0, "no_count": 0,
        "no_text": 0, "missing": 0, "errors": 0,
    }

    stmt = select(Notice).where(
        Notice.layoff_count.is_(None),
        Notice.pdf_path.isnot(None),
    )
    if state is not None:
        stmt = stmt.where(Notice.state == state.upper())
    else:
        stmt = stmt.where(Notice.state.in_(PDF_ONLY_COUNT_STATES))
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

            count = extract_layoff_count(text)
            if count is None:
                stats["no_count"] += 1
                continue

            log.info(
                "%s %s: layoff_count=%d (%s)",
                notice.state, notice.notice_id[:8], count, notice.employer[:40],
            )
            stats["filled"] += 1
            if not dry_run:
                notice.layoff_count = count
                pending_commit += 1
                if pending_commit >= _BATCH_COMMIT:
                    session.commit()
                    pending_commit = 0

        if pending_commit:
            session.commit()

    log.info(
        "backfill-layoff-counts done: considered=%d filled=%d no_count=%d "
        "no_text=%d missing=%d errors=%d",
        stats["considered"], stats["filled"], stats["no_count"],
        stats["no_text"], stats["missing"], stats["errors"],
    )
    return stats
