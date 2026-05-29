"""Routes: /stats — aggregation endpoints for the frontend charts.

Note: same-origin assumption holds when the SPA is served by the same FastAPI
pod (see api/__init__.py StaticFiles mount), so no CORS middleware is needed.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.db.models import Company, Notice

router = APIRouter(prefix="/stats", tags=["stats"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class StateStat(BaseModel):
    state: str
    notice_count: int
    layoff_total: int


class MonthStat(BaseModel):
    month: str  # "YYYY-MM"
    notice_count: int
    layoff_total: int


class EmployerStat(BaseModel):
    employer: str
    company_id: int | None
    notice_count: int
    layoff_total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_date_filters(stmt, after: date | None, before: date | None):
    if after:
        stmt = stmt.where(Notice.notice_date >= after)
    if before:
        stmt = stmt.where(Notice.notice_date <= before)
    return stmt


def _not_superseded(stmt):
    return stmt.where(Notice.is_superseded.is_(False))


def _coerce_int(value) -> int:
    """Pyramid of nullable / Decimal coalesces to a plain int."""
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/by-state", response_model=list[StateStat])
def by_state(
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    db: Session = Depends(get_db),
) -> list[StateStat]:
    stmt = (
        select(
            Notice.state,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .group_by(Notice.state)
        .order_by(Notice.state)
    )
    stmt = _not_superseded(stmt)
    stmt = _apply_date_filters(stmt, after, before)
    rows = db.execute(stmt).all()
    return [
        StateStat(state=r[0], notice_count=_coerce_int(r[1]), layoff_total=_coerce_int(r[2]))
        for r in rows
    ]


@router.get("/by-month", response_model=list[MonthStat])
def by_month(
    state: str | None = Query(None, description="Restrict to one state"),
    after: date | None = Query(None),
    before: date | None = Query(None),
    db: Session = Depends(get_db),
) -> list[MonthStat]:
    # SQLite + Postgres both support strftime / to_char paths, but a portable
    # approach is to bin client-side after pulling year/month — keep it in SQL
    # using DATE_TRUNC on PG and a CASE-style string on SQLite. Easiest portable
    # form: cast notice_date to text in YYYY-MM via substr().
    month_col = func.substr(cast(Notice.notice_date, String), 1, 7).label("month")

    stmt = (
        select(
            month_col,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .where(Notice.notice_date.is_not(None))
        .group_by(month_col)
        .order_by(month_col)
    )
    stmt = _not_superseded(stmt)
    stmt = _apply_date_filters(stmt, after, before)
    if state:
        stmt = stmt.where(Notice.state == state.upper())

    rows = db.execute(stmt).all()
    return [
        MonthStat(month=r[0], notice_count=_coerce_int(r[1]), layoff_total=_coerce_int(r[2]))
        for r in rows
    ]


@router.get("/top-employers", response_model=list[EmployerStat])
def top_employers(
    limit: int = Query(10, ge=1, le=100),
    state: str | None = Query(None),
    after: date | None = Query(None),
    before: date | None = Query(None),
    db: Session = Depends(get_db),
) -> list[EmployerStat]:
    layoff_sum = func.coalesce(func.sum(Notice.layoff_count), 0)
    stmt = (
        select(
            Notice.employer,
            Notice.company_id,
            func.count(Notice.notice_id),
            layoff_sum,
        )
        .group_by(Notice.employer, Notice.company_id)
        .order_by(layoff_sum.desc())
        .limit(limit)
    )
    stmt = _not_superseded(stmt)
    stmt = _apply_date_filters(stmt, after, before)
    if state:
        stmt = stmt.where(Notice.state == state.upper())

    # Prevent Company from being garbage-collected from the query if we ever
    # add a join — currently we only use the FK column.
    _ = Company

    rows = db.execute(stmt).all()
    return [
        EmployerStat(
            employer=r[0],
            company_id=r[1],
            notice_count=_coerce_int(r[2]),
            layoff_total=_coerce_int(r[3]),
        )
        for r in rows
    ]
