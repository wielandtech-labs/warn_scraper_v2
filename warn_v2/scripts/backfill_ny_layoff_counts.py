"""Backfill layoff_count for pre-Tableau NY notices from their WARN UNIT PDFs.

NY notices scraped from the old dol.ny.gov HTML listing (before the April 2025
Tableau-dashboard cutover) carry no layoff_count, and the Tableau CSV the
current scraper reads does not cover them — so they never heal on their own.

Each of those notices' ``raw_notice_url`` 301-redirects to the official NY DOL
"WARN UNIT" summary PDF, a structured cover sheet that publishes::

    Total Number of Affected Workers: 261
    ...
    Number of Affected Employees at Site: 180

The generic ``pdf_extract`` regexes ("affecting N employees") don't match that
label:value format, which is why the nightly download-pdfs pass stored these
PDFs without ever extracting a count. This script parses the NY format
directly: the notice-level total when present, else the sum of per-site counts
(amended notices can disagree between the two — the total line wins).

Fill-only: targets ``layoff_count IS NULL`` and never overwrites a non-NULL
value. Reads the already-stored PDF from the PVC when available, fetching
``raw_notice_url`` only as a fallback (dol.ny.gov sits behind Cloudflare, which
resets non-browser user agents — hence the full browser UA).

Usage::

    warn-v2 backfill-ny-layoff-counts --dry-run     # preview
    warn-v2 backfill-ny-layoff-counts               # commit
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import select

from warn_v2.db.models import Notice
from warn_v2.db.session import session_scope
from warn_v2.pdf_extract import _extract_text

log = logging.getLogger(__name__)

_BATCH_COMMIT = 10
_REQUEST_DELAY = 2.0  # seconds between network fetches (Cloudflare-fronted)
# Same sanity bound as the audit's count_outliers rubric item.
_MAX_SANE_COUNT = 50_000

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

_TOTAL_RE = re.compile(
    r"Total\s+Number\s+of\s+Affected\s+Workers\s*:\s*([\d,]+)", re.I
)
_SITE_RE = re.compile(
    r"Number\s+of\s+Affected\s+(?:Workers|Employees)\s+at\s+Site\s*:\s*([\d,]+)",
    re.I,
)


def extract_affected_workers(text: str) -> int | None:
    """Parse the affected-worker count from NY WARN UNIT summary-PDF text.

    Prefers the notice-level "Total Number of Affected Workers" line; falls
    back to summing the per-site lines. Returns None when neither is present
    or the value fails the sanity bound.
    """
    m = _TOTAL_RE.search(text)
    if m:
        count = int(m.group(1).replace(",", ""))
    else:
        sites = _SITE_RE.findall(text)
        if not sites:
            return None
        count = sum(int(s.replace(",", "")) for s in sites)
    if not 0 < count <= _MAX_SANE_COUNT:
        return None
    return count


def backfill_ny_layoff_counts(
    *,
    dry_run: bool = False,
    limit: int | None = None,
    pdf_dir: Path = Path("/var/pdfs"),
) -> dict[str, int]:
    """Fill NULL layoff_count on NY notices from their WARN UNIT PDFs.

    Returns ``{"considered": N, "filled": N, "no_count": N, "errors": N}``.
    """
    stats = {"considered": 0, "filled": 0, "no_count": 0, "errors": 0}

    stmt = (
        select(Notice)
        .where(
            Notice.state == "NY",
            Notice.layoff_count.is_(None),
            Notice.raw_notice_url.is_not(None),
        )
        .order_by(Notice.notice_date.desc().nullslast())
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    with session_scope() as session:
        notices = session.scalars(stmt).all()
        stats["considered"] = len(notices)
        log.info("backfill-ny-layoff-counts: %d notice(s) to process", len(notices))

        pending = 0
        fetched_any = False
        for notice in notices:
            pdf_bytes = _stored_pdf(notice, pdf_dir)
            if pdf_bytes is None:
                if fetched_any:
                    time.sleep(_REQUEST_DELAY)
                fetched_any = True
                pdf_bytes = _fetch_pdf(notice)
            if pdf_bytes is None:
                stats["errors"] += 1
                continue

            count = extract_affected_workers(_pdf_text(pdf_bytes))
            if count is None:
                log.warning(
                    "NY %s: no affected-workers count in PDF (%s)",
                    notice.notice_id[:10], notice.employer[:40],
                )
                stats["no_count"] += 1
                continue

            log.info(
                "NY %s: layoff_count=%d (%s, %s)",
                notice.notice_id[:10], count, notice.employer[:40], notice.notice_date,
            )
            stats["filled"] += 1
            if not dry_run:
                notice.layoff_count = count
                pending += 1
                if pending >= _BATCH_COMMIT:
                    session.commit()
                    pending = 0

        if pending and not dry_run:
            session.commit()

    log.info(
        "backfill-ny-layoff-counts done: considered=%d filled=%d no_count=%d errors=%d",
        stats["considered"], stats["filled"], stats["no_count"], stats["errors"],
    )
    return stats


def _pdf_text(pdf_bytes: bytes) -> str:
    """Best-effort text extraction — a malformed PDF must not abort the run."""
    try:
        return _extract_text(pdf_bytes)
    except Exception as e:
        log.debug("backfill-ny-layoff-counts: unreadable PDF: %s", e)
        return ""


def _stored_pdf(notice: Notice, pdf_dir: Path) -> bytes | None:
    """Read the notice's already-stored PDF from the PVC, or None."""
    if not notice.pdf_path:
        return None
    try:
        data = (pdf_dir / notice.pdf_path).read_bytes()
    except OSError:
        return None
    if data[:4] != b"%PDF":
        return None
    return data


def _fetch_pdf(notice: Notice) -> bytes | None:
    """Fetch the notice's raw_notice_url (301 → PDF), or None on failure."""
    try:
        r = httpx.get(
            notice.raw_notice_url, headers=_UA, timeout=30, follow_redirects=True
        )
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("NY %s: fetch failed: %s", notice.notice_id[:10], e)
        return None
    if r.content[:4] != b"%PDF":
        log.warning(
            "NY %s: %s did not resolve to a PDF (content-type %r)",
            notice.notice_id[:10],
            notice.raw_notice_url,
            r.headers.get("content-type", ""),
        )
        return None
    return r.content
