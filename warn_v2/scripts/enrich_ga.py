"""Enrich GA notices by scraping TCSG entry detail pages.

The TCSG GravityView entry detail pages (raw_notice_url) are server-side
rendered — no Playwright needed.  Each page contains fields absent from the
public list view: Company Address, County, Zip Code, Type of Layoff or
Closure, First Date of Separation, and an optional gk-download PDF link.

For each GA notice not yet processed that still has a missing field
(effective_date, closure_type, address, pdf_path, county):
  1. Fetch the entry detail page with httpx.
  2. Parse field labels/values from the GravityView <table>.
  3. Download the gk-download attachment if present: store it when it's a PDF,
     otherwise extract WARN fields from the Word/Excel/HTML/CSV/text document in
     memory (see warn_v2.attachment_extract).
  4. Apply page fields: closure_type, effective_date, address, zip, county.
  5. Stamp attachment_fetched_at so a processed notice leaves the candidate set
     even when the source supplies no further geocodable data.

Run via:
  warn-v2 enrich-ga
  warn-v2 enrich-ga --limit 10 --dry-run
"""
from __future__ import annotations

import logging
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import or_, select

from warn_v2.attachment_extract import extract_attachment_fields
from warn_v2.closure import normalize_closure_category
from warn_v2.db.models import Location, Notice
from warn_v2.db.session import session_scope
from warn_v2.pipeline.storage import enrich_notice_location
from warn_v2.scripts.download_pdfs import _apply_fields

log = logging.getLogger(__name__)

# Commit frequently: TCSG rate-limits and the run aborts mid-way, so a large
# batch would discard everything fetched before the block. Small batches make
# each nightly run durably bank whatever it managed before TCSG cut it off.
_BATCH_COMMIT = 5
_REQUEST_DELAY = 3.0   # seconds between requests — TCSG rate-limits after ~10 fast requests
_RETRY_STATUS = frozenset({429, 503})  # transient — back off and retry
_MAX_ATTEMPTS = 3
_MAX_CONSECUTIVE_TIMEOUTS = 3   # abort early if TCSG blocks this many fetches in a row
_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header (delta-seconds form) to float seconds, else None."""
    if not value:
        return None
    try:
        return max(0.0, float(value.strip()))
    except (ValueError, AttributeError):
        return None


def _get_with_backoff(
    url: str,
    *,
    timeout: float,
    request_delay: float,
    max_attempts: int = _MAX_ATTEMPTS,
) -> httpx.Response:
    """GET *url*, retrying on 429/503 with exponential backoff.

    Honors a numeric Retry-After header when present; otherwise sleeps
    ``request_delay * 2**attempt``. Non-retryable error statuses raise
    immediately (via ``raise_for_status``), matching prior behavior.
    """
    for attempt in range(1, max_attempts + 1):
        r = httpx.get(url, headers=_UA, timeout=timeout, follow_redirects=True)
        if r.status_code in _RETRY_STATUS and attempt < max_attempts:
            retry_after = _parse_retry_after(r.headers.get("Retry-After"))
            wait = (
                retry_after
                if retry_after is not None
                else request_delay * (2 ** (attempt - 1))
            )
            log.warning(
                "GA: HTTP %s on %s — backing off %.1fs (attempt %d/%d)",
                r.status_code, url, wait, attempt, max_attempts,
            )
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    # Unreachable: the final attempt either returns or raises above.
    raise RuntimeError("backoff loop exited without a response")


def enrich_ga(
    *,
    limit: int | None = None,
    dry_run: bool = False,
    pdf_dir: Path = Path("/var/pdfs"),
    request_delay: float = _REQUEST_DELAY,
) -> dict[str, int]:
    """Enrich GA notices from TCSG entry detail pages. Returns stats dict.

    *request_delay* is the base inter-request sleep (seconds); it also seeds the
    exponential backoff applied on 429/503 responses.
    """
    stats = {
        "considered": 0,
        "enriched": 0,
        "pdf_fetched": 0,
        "skipped": 0,
        "errors": 0,
    }

    stmt = (
        select(Notice)
        .outerjoin(Location, Notice.location_id == Location.id)
        .where(
            Notice.state == "GA",
            Notice.raw_notice_url.isnot(None),
            # Never attempted: a notice is fetched at most once (plus TCSG-timeout
            # retries, which don't set the stamp), so the budget always advances
            # through the backlog instead of re-hitting the same newest notices.
            Notice.attachment_fetched_at.is_(None),
            # ...and still missing something the entry page/attachment can supply,
            # so we skip notices that are already complete.
            or_(
                Notice.effective_date.is_(None),
                Notice.closure_type.is_(None),
                Notice.address.is_(None),
                Notice.pdf_path.is_(None),
                Location.county.is_(None),
            ),
        )
        .order_by(Notice.notice_date.desc().nullslast())
    )
    if limit is not None:
        stmt = stmt.limit(limit)

    with session_scope() as session:
        notices = session.scalars(stmt).all()
        stats["considered"] = len(notices)
        log.info("enrich-ga: %d notice(s) to process", len(notices))

        pending = 0
        consecutive_timeouts = 0
        for i, notice in enumerate(notices):
            if i > 0:
                time.sleep(request_delay)

            try:
                result = _process_one(
                    session, notice, pdf_dir=pdf_dir, dry_run=dry_run,
                    request_delay=request_delay,
                )
            except Exception:  # one bad notice must not lose the whole run
                log.exception(
                    "GA %s: unexpected error; banking progress and stopping",
                    notice.notice_id[:10],
                )
                # Count it: a crash with no prior progress must fail the run
                # (the CLI exits nonzero only on errors with zero work done).
                stats["errors"] += 1
                break

            if result == "timeout":
                # Count as an error but also track the run of consecutive timeouts.
                # A sustained run means TCSG is blocking the pod — abort early rather
                # than burning 30s per remaining notice.
                stats["errors"] += 1
                consecutive_timeouts += 1
                if consecutive_timeouts >= _MAX_CONSECUTIVE_TIMEOUTS:
                    log.error(
                        "enrich-ga: %d consecutive timeouts — TCSG appears to be blocking; "
                        "aborting early (%d/%d notices processed)",
                        consecutive_timeouts, i + 1, stats["considered"],
                    )
                    break
            else:
                consecutive_timeouts = 0
                stats[result] += 1

            # Any successful entry-page fetch stamps attachment_fetched_at (even a
            # no-change "skipped"), so bank it durably before TCSG blocks the run.
            if result in ("enriched", "pdf_fetched", "skipped"):
                pending += 1
                if pending >= _BATCH_COMMIT and not dry_run:
                    session.commit()
                    pending = 0
            log.debug(
                "enrich-ga [%d/%d] %s → %s",
                i + 1, stats["considered"], notice.notice_id[:10], result,
            )

        if pending and not dry_run:
            session.commit()

    log.info(
        "enrich-ga done: enriched=%d pdf_fetched=%d skipped=%d errors=%d total=%d",
        stats["enriched"], stats["pdf_fetched"],
        stats["skipped"], stats["errors"], stats["considered"],
    )
    return stats


def _process_one(
    session, notice: Notice, *, pdf_dir: Path, dry_run: bool,
    request_delay: float = _REQUEST_DELAY,
) -> str:
    """Fetch one entry page, apply page + attachment fields. Returns result key."""
    url = notice.raw_notice_url
    if not url:
        return "skipped"

    try:
        r = _get_with_backoff(url, timeout=30, request_delay=request_delay)
    except httpx.TimeoutException:
        log.warning("GA %s: page fetch timed out", notice.notice_id[:10])
        return "timeout"
    except httpx.HTTPError as e:
        log.warning("GA %s: page fetch failed: %s", notice.notice_id[:10], e)
        return "errors"

    soup = BeautifulSoup(r.text, "html.parser")
    page_fields = _parse_detail_fields(soup)
    attach_url = _find_attachment_url(soup)

    # Process the attachment before the page fields: a non-PDF WARN letter carries
    # the real worksite address, which mints the Location that the page's County
    # then attaches to — and that a page-supplied HQ ZIP would otherwise pin first.
    pdf_stored = False
    attach_changed = False
    if attach_url and not notice.pdf_path:
        pdf_stored, attach_changed = _download_attachment(
            session, notice, attach_url, pdf_dir=pdf_dir, dry_run=dry_run,
            request_delay=request_delay,
        )

    text_changed = _apply_text_fields(session, notice, page_fields, dry_run=dry_run)

    # The entry page was fetched: stamp it so this notice leaves the candidate set
    # even if the source supplied no new geocodable data (otherwise it would be
    # re-fetched every nightly run and starve the rest of the backlog).
    if not dry_run:
        notice.attachment_fetched_at = datetime.now(UTC)

    if pdf_stored:
        return "pdf_fetched"
    if attach_changed or text_changed:
        return "enriched"

    log.debug("GA %s: no new data", notice.notice_id[:10])
    return "skipped"


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

def _parse_detail_fields(soup: BeautifulSoup) -> dict[str, str]:
    """Extract label→value pairs from the GravityView entry table.

    The page renders as rows of:
      <th><span class="gv-field-label">Label</span></th>
      <td>Value (may contain nested tags)</td>

    Only the first occurrence of each label is kept (Zip Code appears twice).
    """
    seen: dict[str, str] = {}
    for tr in soup.find_all("tr"):
        label_el = tr.find("span", class_="gv-field-label")
        td = tr.find("td")
        if not (label_el and td):
            continue
        label = label_el.get_text(strip=True)
        value = td.get_text(" ", strip=True)
        if label and value and label not in seen:
            seen[label] = value
    return seen


def _find_attachment_url(soup: BeautifulSoup) -> str | None:
    """Return the first gk-download href, or None if no attachment is present.

    The attachment may be a PDF, a Word/Excel document, or HTML/CSV/text — the
    downloader classifies it by the response, not the link.
    """
    for a in soup.find_all("a", href=True):
        if "gk-download" in a["href"]:
            return a["href"]
    return None


# ---------------------------------------------------------------------------
# Field application
# ---------------------------------------------------------------------------

def _apply_text_fields(
    session, notice: Notice, fields: dict[str, str], *, dry_run: bool
) -> bool:
    """Apply detail-page fields to a notice. Fill-in semantics. Returns True if changed."""
    changed = False

    # closure_type — fill-in only
    closure = fields.get("Type of Layoff or Closure")
    if closure and not notice.closure_type:
        if not dry_run:
            notice.closure_type = closure
            if not notice.closure_category:
                notice.closure_category = normalize_closure_category(closure)
        changed = True
        log.debug("GA %s: closure_type=%r", notice.notice_id[:10], closure)

    # effective_date — update if NULL or equals the 60-day estimate
    sep_str = fields.get("First Date of Separation")
    if sep_str:
        sep_date = _parse_mdY(sep_str)
        if sep_date is not None:
            estimated = (
                notice.notice_date + timedelta(days=60) if notice.notice_date else None
            )
            if notice.effective_date is None or notice.effective_date == estimated:
                if notice.effective_date != sep_date:
                    if not dry_run:
                        notice.effective_date = sep_date
                    changed = True
                    log.debug(
                        "GA %s: effective_date=%s", notice.notice_id[:10], sep_date
                    )

    # address — strip the "Map It" widget text appended to the field value
    addr_raw = fields.get("Company Address")
    if addr_raw and not notice.address:
        addr = addr_raw.removesuffix("Map It").strip()
        if addr:
            if not dry_run:
                notice.address = addr
            changed = True
            log.debug("GA %s: address=%r", notice.notice_id[:10], addr)

    # zip — first "Zip Code" occurrence is the company zip
    zip_ = fields.get("Zip Code")
    if zip_:
        loc_changed = (
            enrich_notice_location(
                session, notice, city=None, zip_=zip_, address=notice.address
            )
            if not dry_run
            else False
        )
        if loc_changed:
            changed = True

    # county — store on the linked location so the UI can display it
    county_raw = fields.get("County")
    if county_raw and notice.location and not notice.location.county:
        if not dry_run:
            notice.location.county = county_raw
        changed = True
        log.debug("GA %s: county=%r", notice.notice_id[:10], county_raw)

    return changed


def _download_attachment(
    session, notice: Notice, url: str, *, pdf_dir: Path, dry_run: bool,
    request_delay: float = _REQUEST_DELAY,
) -> tuple[bool, bool]:
    """Download a gk-download attachment; store it if a PDF, then extract fields.

    Returns ``(pdf_stored, fields_changed)``. A PDF is written to
    ``pdf_dir/ga/{notice_id}.pdf``; a non-PDF (Word/Excel/HTML/CSV/text) is parsed
    in memory via ``extract_attachment_fields`` and not persisted. Either way the
    extracted WARN fields (worksite city/zip/address, layoff_count, effective_date)
    are applied with the shared fill-in/update semantics.
    """
    try:
        r = _get_with_backoff(url, timeout=60, request_delay=request_delay)
    except httpx.HTTPError as e:
        log.warning("GA %s: attachment download failed: %s", notice.notice_id[:10], e)
        return False, False

    content = r.content
    content_type = r.headers.get("content-type", "")
    is_pdf = "pdf" in content_type.lower() or content[:4] == b"%PDF"

    pdf_stored = False
    if is_pdf:
        rel_path = Path("ga") / f"{notice.notice_id}.pdf"
        if not dry_run:
            abs_path = pdf_dir / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(content)
            notice.pdf_path = str(rel_path)
        pdf_stored = True
        log.info(
            "GA %s: PDF stored %dKB → %s",
            notice.notice_id[:10], len(content) // 1024, rel_path,
        )

    fields = extract_attachment_fields(
        content, content_type, _attachment_filename(r), notice.state
    )
    changed = _apply_fields(session, notice, fields, dry_run=dry_run)
    return pdf_stored, changed


def _attachment_filename(r: httpx.Response) -> str | None:
    """Best-effort filename from a Content-Disposition header (a type hint)."""
    cd = r.headers.get("content-disposition", "")
    m = re.search(r'filename\*?=(?:"([^"]+)"|([^";]+))', cd)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").strip() or None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_mdY(s: str) -> date | None:
    """Parse MM/DD/YYYY → date, or None on failure."""
    try:
        m, d, y = s.strip().split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None
