"""End-to-end run for one state: fetch → parse → validate → upsert → log."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from warn_v2.db.models import Notice, ScraperRun
from warn_v2.db.session import session_scope
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.pipeline.validate import validate
from warn_v2.scrapers import http_cache
from warn_v2.scrapers.base import (
    DetailSkipping,
    NotModified,
    ParseFailed,
    ScrapeFailed,
    StateScraper,
)

log = logging.getLogger(__name__)

# Notices younger than this stay in the detail-fetch set even when complete,
# so in-place amendments (updated layoff_count) near filing time still land.
_DETAIL_REFETCH_WINDOW_DAYS = 30


def run_state(scraper: StateScraper) -> ScraperRun:
    """Run one state end-to-end and persist a ScraperRun row."""
    started = datetime.now(UTC)
    run = ScraperRun(state=scraper.state.upper(), started_at=started, status="ok")

    if isinstance(scraper, DetailSkipping):
        try:
            scraper.set_skip_detail_urls(_complete_detail_urls(scraper.state))
        except Exception:
            log.exception(
                "%s: skip-url query failed; fetching all details", scraper.state
            )
            scraper.set_skip_detail_urls(set())

    raw: bytes | None = None
    try:
        raw = scraper.fetch()
    except NotModified:
        # Success: source reachable but unchanged — skip parse/validate/store.
        # rows_scraped stays None (not 0) so the audit row-drift check is silent.
        run.rows_new = 0
        return _finish(run, status="not_modified", error=None)
    except ScrapeFailed as e:
        return _finish(run, status="fetch_failed", error=str(e))

    try:
        rows = scraper.parse(raw)
    except ParseFailed as e:
        run.snapshot_path = _save_snapshot(scraper.state, raw)
        return _finish(run, status="parse_failed", error=str(e))
    except Exception as e:
        run.snapshot_path = _save_snapshot(scraper.state, raw)
        return _finish(run, status="parse_failed", error=f"{type(e).__name__}: {e}")

    result = validate(scraper, rows)
    if not result.ok:
        run.snapshot_path = _save_snapshot(scraper.state, raw)
        run.rows_scraped = result.row_count
        return _finish(run, status="validation_failed", error=result.reason)

    try:
        with session_scope() as session:
            seen, new = upsert_notices(session, rows)
            run.rows_scraped = seen
            run.rows_new = new
            session.add(run)
    except Exception as e:
        return _finish(run, status="storage_failed", error=f"{type(e).__name__}: {e}")

    run.finished_at = datetime.now(UTC)
    return run


def _complete_detail_urls(
    state: str, *, refetch_window_days: int = _DETAIL_REFETCH_WINDOW_DAYS
) -> set[str]:
    """Detail-page URLs whose notice data is already fully stored.

    A detail page only supplies address and layoff_count; once both are
    populated (and the notice is old enough that in-place amendments are
    unlikely) re-fetching it buys nothing. Notices with either field NULL —
    including past detail-fetch failures — stay out of the set and get retried.
    """
    cutoff = date.today() - timedelta(days=refetch_window_days)
    with session_scope() as session:
        rows = session.execute(
            select(Notice.raw_notice_url).where(
                Notice.state == state.upper(),
                Notice.raw_notice_url.is_not(None),
                Notice.address.is_not(None),
                Notice.layoff_count.is_not(None),
                Notice.notice_date < cutoff,
            )
        ).all()
    return {url for (url,) in rows if url}


def _finish(run: ScraperRun, *, status: str, error: str | None) -> ScraperRun:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)
    level = logging.INFO if status == "not_modified" else logging.WARNING
    log.log(level, "scraper run %s status=%s error=%s", run.state, status, error)
    if status in ("parse_failed", "validation_failed", "storage_failed"):
        # The fetched content was never ingested: drop the state's source_cache
        # rows so the next run re-downloads instead of 304ing on content the DB
        # never saw (which would also stall a parser fix until the source next
        # changes).
        http_cache.invalidate_state(run.state)
    try:
        with session_scope() as session:
            session.add(run)
    except Exception:
        log.exception("failed to persist failed ScraperRun for %s", run.state)
    return run


def _save_snapshot(state: str, raw: bytes) -> str:
    base = Path(os.environ.get("SNAPSHOT_DIR", "./snapshots"))
    state_dir = base / state.upper()
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{datetime.now(UTC):%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}.bin"
    path.write_bytes(raw)
    return str(path)
