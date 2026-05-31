"""Download and store per-notice PDFs; enrich notices with extracted fields.

For each notice with a ``raw_notice_url`` and no ``pdf_path``:
  1. Fetch the PDF.
  2. Save it under ``pdf_dir/{state}/{notice_id}.pdf``.
  3. Extract available fields (layoff_count, effective_date, address, city, zip).
  4. Apply extracted data back to the notice using fill-in / update semantics.

Usage::

    warn-v2 download-pdfs --state AK
    warn-v2 download-pdfs --state CT --limit 200
    warn-v2 download-pdfs --dry-run
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import Notice
from warn_v2.db.session import session_scope
from warn_v2.pdf_extract import extract_warn_fields
from warn_v2.pipeline.storage import enrich_notice_location
from warn_v2.scrapers.registry import all_states, get_scraper

log = logging.getLogger(__name__)

_BATCH_COMMIT = 50

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


def _pdf_states() -> frozenset[str]:
    """Return the set of state codes whose raw_notice_url is a direct PDF link.

    States where raw_notice_url is an HTML intermediary page (e.g. GA, which
    uses a GravityView entry page) are excluded — they have a dedicated
    state-specific enricher (e.g. enrich_ga) that handles both field extraction
    and PDF download.
    """
    result = set()
    for code in all_states():
        try:
            scraper = get_scraper(code)
            if getattr(scraper, "raw_notice_url_is_pdf", True):
                result.add(code)
        except Exception:
            result.add(code)  # unknown → include by default
    return frozenset(result)


def download_pdfs(
    state: str | None = None,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    pdf_dir: Path = Path("/var/pdfs"),
) -> dict[str, int]:
    """Download and enrich PDFs for notices that have ``raw_notice_url`` but no ``pdf_path``.

    Only processes states where ``raw_notice_url`` is a direct PDF link
    (``scraper.raw_notice_url_is_pdf is True``).  States like GA, whose
    ``raw_notice_url`` points to an HTML intermediary page, are skipped here
    and handled by their own enricher (e.g. ``warn-v2 enrich-ga``).

    Returns ``{"fetched": N, "enriched": N, "skipped": N, "errors": N}``.
    """
    stats = {"fetched": 0, "enriched": 0, "skipped": 0, "errors": 0}

    # Determine which states to process.
    if state is not None:
        target_state = state.upper()
        scraper = get_scraper(target_state)
        if not getattr(scraper, "raw_notice_url_is_pdf", True):
            log.warning(
                "download-pdfs: %s raw_notice_url is not a direct PDF link "
                "(raw_notice_url_is_pdf=False) — use the state-specific enricher instead",
                target_state,
            )
            return stats
        state_filter: frozenset[str] | None = frozenset([target_state])
    else:
        state_filter = _pdf_states()
        log.info(
            "download-pdfs: limiting to %d PDF-bearing states: %s",
            len(state_filter),
            ", ".join(sorted(state_filter)),
        )

    stmt = (
        select(Notice)
        .where(
            Notice.raw_notice_url.isnot(None),
            Notice.pdf_path.is_(None),
            Notice.state.in_(state_filter),
        )
        .order_by(Notice.notice_date.desc().nullslast())
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    with session_scope() as session:
        notices = session.scalars(stmt).all()
        log.info(
            "download-pdfs: %d notice(s) to process%s",
            len(notices),
            f" [state={state.upper()}]" if state else "",
        )

        pending_commit = 0
        for notice in notices:
            result = _process_one(session, notice, pdf_dir=pdf_dir, dry_run=dry_run)
            stats[result] += 1
            if result in ("fetched", "enriched"):
                pending_commit += 1
                if pending_commit >= _BATCH_COMMIT:
                    if not dry_run:
                        session.commit()
                    pending_commit = 0

        if pending_commit and not dry_run:
            session.commit()

    log.info(
        "download-pdfs done: fetched=%d enriched=%d skipped=%d errors=%d",
        stats["fetched"], stats["enriched"], stats["skipped"], stats["errors"],
    )
    return stats


def _process_one(
    session: Session, notice: Notice, *, pdf_dir: Path, dry_run: bool
) -> str:
    """Fetch, store, and enrich one notice's PDF. Returns result key for stats."""
    url = notice.raw_notice_url
    if not url:
        return "skipped"

    try:
        r = httpx.get(url, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        pdf_bytes = r.content
    except httpx.HTTPError as e:
        log.warning("%s %s: fetch failed: %s", notice.state, notice.notice_id[:8], e)
        return "errors"

    content_type = r.headers.get("content-type", "")
    if "pdf" not in content_type.lower() and not pdf_bytes[:4] == b"%PDF":
        log.warning(
            "%s %s: unexpected content-type %r — storing anyway",
            notice.state, notice.notice_id[:8], content_type,
        )

    rel_path = Path(notice.state.lower()) / f"{notice.notice_id}.pdf"
    abs_path = pdf_dir / rel_path

    if not dry_run:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(pdf_bytes)
        notice.pdf_path = str(rel_path)

    log.debug(
        "%s %s: stored %dKB at %s",
        notice.state, notice.notice_id[:8], len(pdf_bytes) // 1024, rel_path,
    )

    fields = extract_warn_fields(pdf_bytes)
    enriched = _apply_fields(session, notice, fields, dry_run=dry_run)

    log.info(
        "%s %s: fetched %dKB%s",
        notice.state,
        notice.notice_id[:8],
        len(pdf_bytes) // 1024,
        _format_enriched(fields) if fields else "",
    )

    return "enriched" if enriched else "fetched"


def _apply_fields(
    session: Session, notice: Notice, fields: dict, *, dry_run: bool
) -> bool:
    """Apply PDF-extracted fields to a notice. Returns True if any change was made."""
    if not fields or dry_run:
        return False

    changed = False

    # address: fill-in only (don't overwrite an existing value)
    if not notice.address and fields.get("address"):
        notice.address = fields["address"]
        changed = True

    # layoff_count: PDF is authoritative
    new_count = fields.get("layoff_count")
    if new_count is not None and notice.layoff_count != new_count:
        notice.layoff_count = new_count
        changed = True

    # effective_date: update if NULL or equals the 60-day WARN Act estimate
    new_date = fields.get("effective_date")
    if new_date is not None:
        estimated = (
            notice.notice_date + timedelta(days=60) if notice.notice_date else None
        )
        if notice.effective_date is None or notice.effective_date == estimated:
            if notice.effective_date != new_date:
                notice.effective_date = new_date
                changed = True

    # location: create/upgrade using extracted city/zip
    if fields.get("city") or fields.get("zip"):
        loc_changed = enrich_notice_location(
            session,
            notice,
            city=fields.get("city"),
            zip_=fields.get("zip"),
            address=notice.address,
        )
        if loc_changed:
            changed = True

    return changed


def _format_enriched(fields: dict) -> str:
    parts = []
    if "layoff_count" in fields:
        parts.append(f"layoff_count={fields['layoff_count']}")
    if "effective_date" in fields:
        parts.append(f"effective_date={fields['effective_date']}")
    if "address" in fields:
        parts.append("address=<set>")
    if "zip" in fields:
        parts.append(f"zip={fields['zip']}")
    return " [" + ", ".join(parts) + "]" if parts else ""
