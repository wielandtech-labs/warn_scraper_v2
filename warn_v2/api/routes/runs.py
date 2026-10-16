"""Routes: /scraper-runs"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import PaginationParams, get_db
from warn_v2.api.schemas import Page, ScraperRunOut, StateStatusOut
from warn_v2.api.timeline import month_col
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
    raw_items = list(db.scalars(stmt.offset(pagination.offset).limit(pagination.limit)))
    items = [ScraperRunOut.model_validate(r) for r in raw_items]
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
    last_success = {r[0]: r[1] for r in success_rows}

    # Notice-date coverage per state (non-superseded, matching the public
    # stats), so the status page can show how far back each state reaches.
    range_rows = db.execute(
        select(Notice.state, func.min(Notice.notice_date), func.max(Notice.notice_date))
        .where(Notice.is_superseded.is_(False))
        .group_by(Notice.state)
    )
    notice_ranges = {state: (lo, hi) for state, lo, hi in range_rows}
    coverage = _coverage_start(db)

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
            coverage_start=coverage.get(r.state),
        )
        for r in latest_runs
    ]
    out.sort(key=lambda s: s.state)
    return out


def _coverage_start(db: Session) -> dict[str, date]:
    """Per state, the first notice of the first calendar year that is followed
    by another year with notices (or is the latest year with any).

    first_notice_date alone is pulled back by stray rows — a lone mis-dated
    or one-off notice years before a state's archive begins (CA has one 1997
    row ahead of a series starting in 2000) — which would make /timelapse
    count the state as reporting through years it has no data for. Requiring
    the next year to have notices too skips such strays while keeping small
    states whose real series has only a notice or two a year. Non-WARN events
    are left out, as in the stats this coverage qualifies.
    """
    year = func.substr(month_col, 1, 4)
    rows = db.execute(
        select(Notice.state, year, func.min(Notice.notice_date))
        .where(
            Notice.is_superseded.is_(False),
            Notice.notice_date.is_not(None),
            Notice.closure_category.is_distinct_from("Non-WARN"),
        )
        .group_by(Notice.state, year)
    )
    by_state: dict[str, dict[int, date]] = {}
    for state, y, first in rows:
        by_state.setdefault(state, {})[int(y)] = first
    out = {}
    for state, years in by_state.items():
        latest = max(years)
        start = min(y for y in years if y + 1 in years or y == latest)
        out[state] = years[start]
    return out
