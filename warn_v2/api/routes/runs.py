"""Routes: /scraper-runs"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import PaginationParams, get_db
from warn_v2.api.schemas import Page, ScraperRunOut, StateStatusOut
from warn_v2.db.models import SCRAPER_SUCCESS_STATUSES, Notice, ScraperRun

router = APIRouter(prefix="/scraper-runs", tags=["scraper-runs"])


@router.get("", response_model=Page[ScraperRunOut])
def list_scraper_runs(
    state: str | None = Query(None, description="Two-letter state code, e.g. CA"),
    status: str | None = Query(
        None,
        description="ok | fetch_failed | parse_failed | validation_failed | storage_failed",
    ),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
) -> Page[ScraperRunOut]:
    stmt = select(ScraperRun).order_by(ScraperRun.started_at.desc())
    count_stmt = select(func.count()).select_from(ScraperRun)

    if state:
        stmt = stmt.where(ScraperRun.state == state.upper())
        count_stmt = count_stmt.where(ScraperRun.state == state.upper())
    if status:
        stmt = stmt.where(ScraperRun.status == status)
        count_stmt = count_stmt.where(ScraperRun.status == status)

    total = db.scalar(count_stmt) or 0
    items = list(db.scalars(stmt.offset(pagination.offset).limit(pagination.limit)))
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/status", response_model=list[StateStatusOut])
def scraper_status(db: Session = Depends(get_db)) -> list[StateStatusOut]:
    """Per-state scraper health for the public status page.

    Returns one row per state with run history: its latest attempt (status,
    row counts, error) plus when it last succeeded. Two grouped queries keep
    this O(states) rather than N+1, and avoid window functions so it runs
    identically on SQLite (tests) and Postgres (prod).
    """
    # Latest run per state: max(started_at) grouped, joined back for the full row.
    latest = (
        select(ScraperRun.state, func.max(ScraperRun.started_at).label("mx"))
        .group_by(ScraperRun.state)
        .subquery()
    )
    latest_runs = db.scalars(
        select(ScraperRun).join(
            latest,
            and_(
                ScraperRun.state == latest.c.state,
                ScraperRun.started_at == latest.c.mx,
            ),
        )
    )

    # Latest successful run per state — only the timestamp is needed.
    success_rows = db.execute(
        select(ScraperRun.state, func.max(ScraperRun.started_at))
        .where(ScraperRun.status.in_(SCRAPER_SUCCESS_STATUSES))
        .group_by(ScraperRun.state)
    )
    last_success = dict(success_rows.all())

    # Notice-date coverage per state (non-superseded, matching the public
    # stats), so the status page can show how far back each state reaches.
    range_rows = db.execute(
        select(Notice.state, func.min(Notice.notice_date), func.max(Notice.notice_date))
        .where(Notice.is_superseded.is_(False))
        .group_by(Notice.state)
    )
    notice_ranges = {state: (lo, hi) for state, lo, hi in range_rows}

    out = [
        StateStatusOut(
            state=r.state,
            last_run_at=r.started_at,
            last_status=r.status,
            last_finished_at=r.finished_at,
            rows_scraped=r.rows_scraped,
            rows_new=r.rows_new,
            error=r.error,
            last_success_at=last_success.get(r.state),
            first_notice_date=notice_ranges.get(r.state, (None, None))[0],
            last_notice_date=notice_ranges.get(r.state, (None, None))[1],
        )
        for r in latest_runs
    ]
    out.sort(key=lambda s: s.state)
    return out
