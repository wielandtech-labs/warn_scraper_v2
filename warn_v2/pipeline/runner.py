"""End-to-end run for one state: fetch → parse → validate → upsert → log."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from warn_v2.db.models import ScraperRun
from warn_v2.db.session import session_scope
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import ParseFailed, ScrapeFailed, StateScraper

log = logging.getLogger(__name__)


def run_state(scraper: StateScraper) -> ScraperRun:
    """Run one state end-to-end and persist a ScraperRun row."""
    started = datetime.now(UTC)
    run = ScraperRun(state=scraper.state.upper(), started_at=started, status="ok")

    raw: bytes | None = None
    try:
        raw = scraper.fetch()
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


def _finish(run: ScraperRun, *, status: str, error: str | None) -> ScraperRun:
    run.status = status
    run.error = error
    run.finished_at = datetime.now(UTC)
    log.warning("scraper run %s status=%s error=%s", run.state, status, error)
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
