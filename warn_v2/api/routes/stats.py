"""Routes: /stats — aggregation endpoints for the frontend charts.

Note: same-origin assumption holds when the SPA is served by the same FastAPI
pod (see api/__init__.py StaticFiles mount), so no CORS middleware is needed.
"""
from __future__ import annotations

import calendar
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session, aliased

from warn_v2.api.deps import get_db
from warn_v2.companies.naics import (
    SECTOR_NAME,
    naics_filter,
    sector_for_code,
    subsector_for_code,
    subsector_name,
)
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
    # Pace projection for the current, incomplete month (count-to-date scaled by
    # the fraction of the month elapsed). Set only on the final row when it is
    # the current UTC month; null on complete periods.
    projected_notice_count: int | None = None
    projected_layoff_total: int | None = None


class PeriodStat(BaseModel):
    period: str  # "YYYY-MM-DD" for day buckets, "YYYY-MM" for month buckets
    notice_count: int
    layoff_total: int
    # Pace projection for the current, incomplete month/year. Set only on the
    # final row when it is the current UTC period; always null for day buckets.
    projected_notice_count: int | None = None
    projected_layoff_total: int | None = None


class EmployerStat(BaseModel):
    employer: str
    company_id: int | None
    notice_count: int
    layoff_total: int


class SubsectorStat(BaseModel):
    code: str  # 3-digit NAICS subsector, e.g. "311"
    name: str
    notice_count: int
    layoff_total: int


class IndustryStat(BaseModel):
    sector: str  # NAICS sector id, e.g. "31-33"
    name: str
    notice_count: int  # = sum of its subsectors
    layoff_total: int  # = sum of its subsectors
    subsectors: list[SubsectorStat]


class ParentGroupStat(BaseModel):
    # Anonymous: a corporate family is identified only by a representative member
    # WARN company, never by the D&B parent name or the internal grouping key.
    representative_company_id: int
    representative_company_name: str
    member_count: int
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


def _apply_closure_filter(stmt, closure_category: str | None):
    if closure_category:
        stmt = stmt.where(Notice.closure_category == closure_category)
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


def _today() -> date:
    """Current UTC date. Module-level so tests can monkeypatch it."""
    return datetime.now(UTC).date()


def _apply_industry_filter(stmt, industry, subsector, *, joined: bool = False):
    """Filter a Notice-based stmt by the linked company's NAICS sector/subsector.

    Joins Company (Notice.company_id) unless the caller already has it joined.
    An inner join drops notices with no linked company, which is correct: an
    un-enriched notice has no NAICS and so matches no industry.
    """
    clause = naics_filter(Company.naics_code, industry, subsector)
    if clause is None:
        return stmt
    if not joined:
        stmt = stmt.join(Company, Notice.company_id == Company.id)
    return stmt.where(clause)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/by-state", response_model=list[StateStat])
def by_state(
    closure_category: str | None = Query(
        None, description="Normalized closure type: Closure | Layoff"
    ),
    industry: str | None = Query(None, description="NAICS sector id (e.g. 31-33)"),
    subsector: str | None = Query(None, description="3-digit NAICS subsector (e.g. 311)"),
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
    stmt = _apply_closure_filter(stmt, closure_category)
    stmt = _apply_industry_filter(stmt, industry, subsector)
    rows = db.execute(stmt).all()
    return [
        StateStat(state=r[0], notice_count=_coerce_int(r[1]), layoff_total=_coerce_int(r[2]))
        for r in rows
    ]


def _aggregate_over_time(
    db: Session,
    *,
    substr_len: int,
    state: str | None,
    closure_category: str | None,
    industry: str | None,
    subsector: str | None,
    after: date | None,
    before: date | None,
) -> list[tuple[str, int, int]]:
    """Group non-superseded notices into time buckets by a string prefix of
    notice_date. substr_len=7 yields "YYYY-MM" (monthly), 10 yields "YYYY-MM-DD"
    (daily). Portable across SQLite + Postgres (no DATE_TRUNC/strftime). Returns
    (period, notice_count, layoff_total) tuples ordered oldest-first.
    """
    period_col = func.substr(cast(Notice.notice_date, String), 1, substr_len).label("period")
    stmt = (
        select(
            period_col,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .where(Notice.notice_date.is_not(None))
        .group_by(period_col)
        .order_by(period_col)
    )
    stmt = _not_superseded(stmt)
    stmt = _apply_date_filters(stmt, after, before)
    stmt = _apply_closure_filter(stmt, closure_category)
    if state:
        stmt = stmt.where(Notice.state == state.upper())
    stmt = _apply_industry_filter(stmt, industry, subsector)

    return [
        (r[0], _coerce_int(r[1]), _coerce_int(r[2])) for r in db.execute(stmt).all()
    ]


def _pace_projection(
    rows: list[tuple[str, int, int]],
    *,
    substr_len: int,
    after: date | None,
    before: date | None,
) -> tuple[int, int] | None:
    """Pace-projected (notice_count, layoff_total) for the current period.

    Returns a projection for the FINAL row iff it is the current UTC month
    (substr_len=7) or year (substr_len=4) and the date filters don't truncate
    it; otherwise None. projected = round(actual * period_days / elapsed_days),
    floored at the actual count so it never dips below data already reported.
    Day buckets (substr_len=10) are never projected: a partial "today" barely
    distorts the 30-day daily view. Nothing is projected until 10% of the
    period has elapsed: below that the pace multiplier (>10x) amplifies a
    couple of notices into a y-axis-blowing spike at every period start.
    """
    if substr_len not in (4, 7) or not rows:
        return None
    today = _today()
    if rows[-1][0] != today.isoformat()[:substr_len]:
        return None
    # A `before` earlier than today truncates the current period mid-way, so a
    # through-today pace would understate; skip. before >= today is harmless.
    if before is not None and before < today:
        return None
    if substr_len == 7:
        period_start = today.replace(day=1)
        period_days = calendar.monthrange(today.year, today.month)[1]
        elapsed = today.day
    else:
        period_start = date(today.year, 1, 1)
        period_days = 366 if calendar.isleap(today.year) else 365
        elapsed = today.timetuple().tm_yday
    # An `after` inside the current period means the row only covers part of
    # the elapsed window — the elapsed-fraction denominator would be wrong.
    if after is not None and after > period_start:
        return None
    if elapsed >= period_days:
        return None  # last day of the period: nothing left to project
    if elapsed * 10 < period_days:
        return None  # <10% elapsed: too early to call a pace (see docstring)
    scale = period_days / elapsed
    _, notices, layoffs = rows[-1]
    return max(notices, round(notices * scale)), max(layoffs, round(layoffs * scale))


@router.get("/by-month", response_model=list[MonthStat])
def by_month(
    state: str | None = Query(None, description="Restrict to one state"),
    closure_category: str | None = Query(
        None, description="Normalized closure type: Closure | Layoff"
    ),
    industry: str | None = Query(None, description="NAICS sector id (e.g. 31-33)"),
    subsector: str | None = Query(None, description="3-digit NAICS subsector (e.g. 311)"),
    after: date | None = Query(None),
    before: date | None = Query(None),
    db: Session = Depends(get_db),
) -> list[MonthStat]:
    rows = _aggregate_over_time(
        db,
        substr_len=7,
        state=state,
        closure_category=closure_category,
        industry=industry,
        subsector=subsector,
        after=after,
        before=before,
    )
    out = [MonthStat(month=p, notice_count=n, layoff_total=lt) for p, n, lt in rows]
    proj = _pace_projection(rows, substr_len=7, after=after, before=before)
    if proj is not None:
        out[-1].projected_notice_count, out[-1].projected_layoff_total = proj
    return out


@router.get("/over-time", response_model=list[PeriodStat])
def over_time(
    bucket: str = Query("month", description="Time bucket: day | month | year"),
    state: str | None = Query(None, description="Restrict to one state"),
    closure_category: str | None = Query(
        None, description="Normalized closure type: Closure | Layoff"
    ),
    industry: str | None = Query(None, description="NAICS sector id (e.g. 31-33)"),
    subsector: str | None = Query(None, description="3-digit NAICS subsector (e.g. 311)"),
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    db: Session = Depends(get_db),
) -> list[PeriodStat]:
    """Notice/layoff counts bucketed by day, month, or year — drives the dashboard
    and state-page time-series charts. Daily buckets suit the 30-day window,
    monthly the 1-year/5-year windows, yearly the all-time view. Same filters as
    /by-month.
    """
    substr_len = {"day": 10, "year": 4}.get(bucket, 7)
    rows = _aggregate_over_time(
        db,
        substr_len=substr_len,
        state=state,
        closure_category=closure_category,
        industry=industry,
        subsector=subsector,
        after=after,
        before=before,
    )
    out = [PeriodStat(period=p, notice_count=n, layoff_total=lt) for p, n, lt in rows]
    proj = _pace_projection(rows, substr_len=substr_len, after=after, before=before)
    if proj is not None:
        out[-1].projected_notice_count, out[-1].projected_layoff_total = proj
    return out


@router.get("/top-employers", response_model=list[EmployerStat])
def top_employers(
    limit: int = Query(10, ge=1, le=100),
    state: str | None = Query(None),
    closure_category: str | None = Query(
        None, description="Normalized closure type: Closure | Layoff"
    ),
    industry: str | None = Query(None, description="NAICS sector id (e.g. 31-33)"),
    subsector: str | None = Query(None, description="3-digit NAICS subsector (e.g. 311)"),
    after: date | None = Query(None),
    before: date | None = Query(None),
    db: Session = Depends(get_db),
) -> list[EmployerStat]:
    # Roll duplicate companies up to their canonical row: group by
    # coalesce(canonical_company_id, company_id) and label by the canonical
    # company's name, so "Acme Inc" + "Acme, LLC" collapse into one row.
    layoff_sum = func.coalesce(func.sum(Notice.layoff_count), 0)
    canon_id = func.coalesce(Company.canonical_company_id, Notice.company_id)
    canon = aliased(Company)
    stmt = (
        select(
            func.coalesce(func.min(canon.name), func.min(Notice.employer)).label("employer"),
            # Aggregated so Postgres accepts it: within each group canon_id is a
            # single value (or NULL for employer-string-only groups), so min() is
            # exact. Selecting the bare canon_id triggers a GROUP BY error on PG.
            func.min(canon_id).label("company_id"),
            func.count(Notice.notice_id),
            layoff_sum,
        )
        .select_from(Notice)
        .join(Company, Notice.company_id == Company.id, isouter=True)
        .join(canon, canon.id == canon_id, isouter=True)
        # Roll linked dups up to their canonical company id; fall back to the
        # employer string for notices with no linked company (company_id NULL).
        .group_by(func.coalesce(cast(canon_id, String), Notice.employer))
        .order_by(layoff_sum.desc())
        .limit(limit)
    )
    stmt = _not_superseded(stmt)
    stmt = _apply_date_filters(stmt, after, before)
    stmt = _apply_closure_filter(stmt, closure_category)
    if state:
        stmt = stmt.where(Notice.state == state.upper())
    # Company is already (outer-)joined above, so just add the WHERE clause.
    stmt = _apply_industry_filter(stmt, industry, subsector, joined=True)

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


@router.get("/industries", response_model=list[IndustryStat])
def industries(
    state: str | None = Query(None, description="Restrict to one state"),
    closure_category: str | None = Query(
        None, description="Normalized closure type: Closure | Layoff"
    ),
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    db: Session = Depends(get_db),
) -> list[IndustryStat]:
    """NAICS sectors (with nested 3-digit subsectors) present among notices.

    Groups each enriched company's NAICS code by its 3-digit subsector, then rolls
    up to both the subsector and its 2-digit sector. Only **populated** sectors and
    subsectors (>=1 non-superseded notice) are returned, so the UI dropdowns never
    offer an empty option and grow as enrichment fills in. Notices whose company
    has no NAICS code, or whose code's sector is unknown, are omitted.

    With no filters this returns the all-time taxonomy used by the filter
    dropdowns; the optional date/state/closure filters let the dashboard show the
    industry mix for a 30-day or 1-year window.
    """
    sub3 = func.substr(Company.naics_code, 1, 3)
    stmt = (
        select(
            sub3,
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .select_from(Notice)
        .join(Company, Notice.company_id == Company.id)
        .where(Notice.is_superseded.is_(False), Company.naics_code.is_not(None))
        .group_by(sub3)
    )
    stmt = _apply_date_filters(stmt, after, before)
    stmt = _apply_closure_filter(stmt, closure_category)
    if state:
        stmt = stmt.where(Notice.state == state.upper())

    # sector id -> {subsector code -> [notice_count, layoff_total]}
    by_sector: dict[str, dict[str, list[int]]] = {}
    for code, n, lt in db.execute(stmt).all():
        subsector = subsector_for_code(code)  # code is the 3-digit prefix
        sector = sector_for_code(code)
        if not subsector or not sector:
            continue
        bucket = by_sector.setdefault(sector, {}).setdefault(subsector, [0, 0])
        bucket[0] += _coerce_int(n)
        bucket[1] += _coerce_int(lt)

    out: list[IndustryStat] = []
    for sector, subs in by_sector.items():
        subsectors = sorted(
            (
                SubsectorStat(
                    code=c, name=subsector_name(c) or c, notice_count=v[0], layoff_total=v[1]
                )
                for c, v in subs.items()
            ),
            key=lambda s: s.notice_count,
            reverse=True,
        )
        out.append(
            IndustryStat(
                sector=sector,
                name=SECTOR_NAME[sector],
                notice_count=sum(v[0] for v in subs.values()),
                layoff_total=sum(v[1] for v in subs.values()),
                subsectors=subsectors,
            )
        )
    out.sort(key=lambda s: s.notice_count, reverse=True)
    return out


@router.get("/by-parent-group", response_model=list[ParentGroupStat])
def by_parent_group(
    limit: int = Query(10, ge=1, le=100),
    state: str | None = Query(None),
    after: date | None = Query(None),
    before: date | None = Query(None),
    db: Session = Depends(get_db),
) -> list[ParentGroupStat]:
    """Rank corporate families by total layoffs across all their subsidiaries.

    A family is the set of canonical companies sharing a non-self parent_group_key.
    Singleton families (one member) are dropped — they add nothing over
    top-employers. Each family is labeled anonymously by its largest member.
    """
    # One row per (family, member company): roll notices up to their canonical
    # company, then group by the canonical's parent_group_key. The inner join to
    # Company drops notices with no linked company; the alias join resolves the
    # canonical row that carries parent_group_key.
    canon_id = func.coalesce(Company.canonical_company_id, Notice.company_id)
    canon = aliased(Company)
    stmt = (
        select(
            canon.parent_group_key.label("gkey"),
            canon_id.label("cid"),
            func.min(canon.name).label("name"),
            func.count(Notice.notice_id).label("notices"),
            func.coalesce(func.sum(Notice.layoff_count), 0).label("layoffs"),
        )
        .select_from(Notice)
        .join(Company, Notice.company_id == Company.id)
        .join(canon, canon.id == canon_id)
        .where(canon.parent_group_key.is_not(None))
        .where(~canon.parent_group_key.like("self:%"))
        .group_by(canon.parent_group_key, canon_id)
    )
    stmt = _not_superseded(stmt)
    stmt = _apply_date_filters(stmt, after, before)
    if state:
        stmt = stmt.where(Notice.state == state.upper())

    families: dict[str, list[tuple[int, str, int, int]]] = {}
    for gkey, cid, name, notices, layoffs in db.execute(stmt).all():
        families.setdefault(gkey, []).append(
            (cid, name, _coerce_int(notices), _coerce_int(layoffs))
        )

    out: list[ParentGroupStat] = []
    for members in families.values():
        if len(members) < 2:
            continue
        # Representative = largest member by layoffs, tiebreak by name ascending.
        rep = min(members, key=lambda m: (-m[3], m[1]))
        out.append(
            ParentGroupStat(
                representative_company_id=rep[0],
                representative_company_name=rep[1],
                member_count=len(members),
                notice_count=sum(m[2] for m in members),
                layoff_total=sum(m[3] for m in members),
            )
        )
    out.sort(key=lambda s: s.layoff_total, reverse=True)
    return out[:limit]
