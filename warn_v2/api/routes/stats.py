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


class EmployerStat(BaseModel):
    employer: str
    company_id: int | None
    notice_count: int
    layoff_total: int


class SubsectorStat(BaseModel):
    code: str  # 3-digit NAICS subsector, e.g. "311"
    name: str
    notice_count: int


class IndustryStat(BaseModel):
    sector: str  # NAICS sector id, e.g. "31-33"
    name: str
    notice_count: int  # = sum of its subsectors
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


def _not_superseded(stmt):
    return stmt.where(Notice.is_superseded.is_(False))


def _coerce_int(value) -> int:
    """Pyramid of nullable / Decimal coalesces to a plain int."""
    if value is None:
        return 0
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


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
    stmt = _apply_industry_filter(stmt, industry, subsector)
    rows = db.execute(stmt).all()
    return [
        StateStat(state=r[0], notice_count=_coerce_int(r[1]), layoff_total=_coerce_int(r[2]))
        for r in rows
    ]


@router.get("/by-month", response_model=list[MonthStat])
def by_month(
    state: str | None = Query(None, description="Restrict to one state"),
    industry: str | None = Query(None, description="NAICS sector id (e.g. 31-33)"),
    subsector: str | None = Query(None, description="3-digit NAICS subsector (e.g. 311)"),
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
    stmt = _apply_industry_filter(stmt, industry, subsector)

    rows = db.execute(stmt).all()
    return [
        MonthStat(month=r[0], notice_count=_coerce_int(r[1]), layoff_total=_coerce_int(r[2]))
        for r in rows
    ]


@router.get("/top-employers", response_model=list[EmployerStat])
def top_employers(
    limit: int = Query(10, ge=1, le=100),
    state: str | None = Query(None),
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
def industries(db: Session = Depends(get_db)) -> list[IndustryStat]:
    """NAICS sectors (with nested 3-digit subsectors) present among notices.

    Groups each enriched company's NAICS code by its 3-digit subsector, then rolls
    up to both the subsector and its 2-digit sector. Only **populated** sectors and
    subsectors (>=1 non-superseded notice) are returned, so the UI dropdowns never
    offer an empty option and grow as enrichment fills in. Notices whose company
    has no NAICS code, or whose code's sector is unknown, are omitted.
    """
    sub3 = func.substr(Company.naics_code, 1, 3)
    stmt = (
        select(sub3, func.count(Notice.notice_id))
        .select_from(Notice)
        .join(Company, Notice.company_id == Company.id)
        .where(Notice.is_superseded.is_(False), Company.naics_code.is_not(None))
        .group_by(sub3)
    )
    # sector id -> {subsector code -> count}
    by_sector: dict[str, dict[str, int]] = {}
    for code, n in db.execute(stmt).all():
        subsector = subsector_for_code(code)  # code is the 3-digit prefix
        sector = sector_for_code(code)
        if not subsector or not sector:
            continue
        by_sector.setdefault(sector, {})
        by_sector[sector][subsector] = by_sector[sector].get(subsector, 0) + _coerce_int(n)

    out: list[IndustryStat] = []
    for sector, subs in by_sector.items():
        subsectors = sorted(
            (
                SubsectorStat(
                    code=c, name=subsector_name(c) or c, notice_count=cnt
                )
                for c, cnt in subs.items()
            ),
            key=lambda s: s.notice_count,
            reverse=True,
        )
        out.append(
            IndustryStat(
                sector=sector,
                name=SECTOR_NAME[sector],
                notice_count=sum(subs.values()),
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
