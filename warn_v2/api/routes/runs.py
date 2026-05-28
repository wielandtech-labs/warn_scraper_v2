"""Routes: /scraper-runs"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import PaginationParams, get_db
from warn_v2.api.schemas import Page, ScraperRunOut
from warn_v2.db.models import ScraperRun

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
