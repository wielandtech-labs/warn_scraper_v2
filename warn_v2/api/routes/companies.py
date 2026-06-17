"""Routes: /companies"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from warn_v2.api.deps import PaginationParams, ViewerSchemas, get_db
from warn_v2.api.schemas import FamilyMemberOut, Page
from warn_v2.companies.naics import naics_filter
from warn_v2.db.models import Company, Notice

router = APIRouter(prefix="/companies", tags=["companies"])

_SORT_COLUMNS = {
    "name": Company.name,
    "enriched_at": Company.enriched_at,
    "enrichment_confidence": Company.enrichment_confidence,
}


# response_model=None on the company/notice-shaped routes: the output schema
# depends on the viewer's role (ViewerSchemas), so a static response_model
# would strip the enriched fields for paid/admin sessions.
@router.get("", response_model=None)
def list_companies(
    name: str | None = Query(None, description="Company name (case-insensitive substring)"),
    enriched: bool | None = Query(None, description="Filter by enrichment status"),
    has_duns: bool | None = Query(
        None, description="Filter companies that have (or lack) a DUNS number"
    ),
    sic_code: str | None = Query(None, description="Exact SIC code match"),
    industry: str | None = Query(None, description="NAICS sector id (e.g. 31-33)"),
    subsector: str | None = Query(
        None, description="3-digit NAICS subsector (e.g. 311); narrows within a sector"
    ),
    include_merged: bool = Query(
        False, description="Include rows consolidated into another company"
    ),
    sort_by: str | None = Query(
        None, description="Column: name, enriched_at, enrichment_confidence, layoff_total"
    ),
    sort_dir: str | None = Query("asc", description="asc or desc"),
    pagination: PaginationParams = Depends(),
    view: ViewerSchemas = Depends(),
    db: Session = Depends(get_db),
) -> Page:
    # Workers affected per logical company: sum layoff_count over non-superseded
    # notices, rolled up to the canonical via coalesce(canonical_company_id, id)
    # (same semantics as the family endpoint and top-employers). One grouped
    # subquery joined in — merged dupes therefore show 0 under include_merged
    # (their notices roll to the canonical).
    member = aliased(Company)
    canon_id = func.coalesce(member.canonical_company_id, member.id)
    totals_sq = (
        select(
            canon_id.label("cid"),
            func.coalesce(func.sum(Notice.layoff_count), 0).label("layoff_total"),
        )
        .select_from(Notice)
        .join(member, member.id == Notice.company_id)
        .where(Notice.is_superseded.is_(False))
        .group_by(canon_id)
        .subquery()
    )
    layoff_total = func.coalesce(totals_sq.c.layoff_total, 0)

    col = (
        layoff_total
        if sort_by == "layoff_total"
        else _SORT_COLUMNS.get(sort_by or "name", Company.name)
    )
    order_expr = col.desc().nullslast() if sort_dir == "desc" else col.asc().nullslast()
    # Secondary name sort keeps pagination stable when the column has ties/NULLs.
    stmt = (
        select(Company, layoff_total)
        .outerjoin(totals_sq, totals_sq.c.cid == Company.id)
        .order_by(order_expr, Company.name)
    )
    count_stmt = select(func.count()).select_from(Company)

    if not include_merged:
        # Hide duplicates that were consolidated into a canonical company.
        stmt = stmt.where(Company.canonical_company_id.is_(None))
        count_stmt = count_stmt.where(Company.canonical_company_id.is_(None))

    if name:
        pattern = f"%{name}%"
        stmt = stmt.where(Company.name.ilike(pattern))
        count_stmt = count_stmt.where(Company.name.ilike(pattern))

    if enriched is True:
        stmt = stmt.where(Company.enriched_at.is_not(None))
        count_stmt = count_stmt.where(Company.enriched_at.is_not(None))
    elif enriched is False:
        stmt = stmt.where(Company.enriched_at.is_(None))
        count_stmt = count_stmt.where(Company.enriched_at.is_(None))

    if has_duns is True:
        stmt = stmt.where(Company.duns.is_not(None))
        count_stmt = count_stmt.where(Company.duns.is_not(None))
    elif has_duns is False:
        stmt = stmt.where(Company.duns.is_(None))
        count_stmt = count_stmt.where(Company.duns.is_(None))

    if sic_code:
        stmt = stmt.where(Company.sic_code == sic_code)
        count_stmt = count_stmt.where(Company.sic_code == sic_code)

    industry_filter = naics_filter(Company.naics_code, industry, subsector)
    if industry_filter is not None:
        stmt = stmt.where(industry_filter)
        count_stmt = count_stmt.where(industry_filter)

    total = db.scalar(count_stmt) or 0
    rows = db.execute(stmt.offset(pagination.offset).limit(pagination.limit)).all()
    items = []
    for company, company_layoffs in rows:
        # CompanyOut picks this up via from_attributes; only the list route
        # computes it (None elsewhere = "not computed", not zero).
        company.layoff_total = int(company_layoffs)
        items.append(company)
    return view.company_page(items, total, pagination.limit, pagination.offset)


@router.get("/{company_id}", response_model=None)
def get_company(
    company_id: int,
    view: ViewerSchemas = Depends(),
    db: Session = Depends(get_db),
):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return view.company.model_validate(company)


@router.get("/{company_id}/notices", response_model=None)
def list_company_notices(
    company_id: int,
    pagination: PaginationParams = Depends(),
    view: ViewerSchemas = Depends(),
    db: Session = Depends(get_db),
) -> Page:
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")

    # Roll up notices from companies consolidated into this one, and exclude
    # superseded notices (so totals match the rest of the API).
    merged_ids = select(Company.id).where(Company.canonical_company_id == company_id)
    notice_filter = (
        Notice.company_id.in_(merged_ids) | (Notice.company_id == company_id)
    ) & Notice.is_superseded.is_(False)

    stmt = (
        select(Notice)
        .where(notice_filter)
        .order_by(Notice.notice_date.desc().nullslast())
    )
    count_stmt = select(func.count()).select_from(Notice).where(notice_filter)
    total = db.scalar(count_stmt) or 0
    items = list(db.scalars(stmt.offset(pagination.offset).limit(pagination.limit)))
    return view.notice_page(items, total, pagination.limit, pagination.offset)


@router.get("/{company_id}/family", response_model=list[FamilyMemberOut])
def list_company_family(
    company_id: int,
    db: Session = Depends(get_db),
) -> list[FamilyMemberOut]:
    """Sibling companies sharing this company's corporate family.

    parent_group_key lives only on canonical rows, so resolve a merged dupe to its
    canonical first. A "self:" / NULL key means no known family -> empty list (the
    frontend hides the section). Each member's notice/layoff totals roll up its own
    merged dupes and exclude superseded notices, matching the rest of the API.
    """
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    canonical_id = company.canonical_company_id or company.id
    canonical = (
        company if canonical_id == company.id else db.get(Company, canonical_id)
    )
    key = canonical.parent_group_key if canonical is not None else None
    if not key or key.startswith("self:"):
        return []

    members = list(
        db.scalars(
            select(Company).where(
                Company.canonical_company_id.is_(None),
                Company.parent_group_key == key,
            )
        )
    )
    if not members:
        return []

    # Roll each member's own merged dupes up via coalesce(canonical_company_id,
    # company_id), then count/sum notices per logical (canonical) company.
    canon_id = func.coalesce(Company.canonical_company_id, Notice.company_id)
    member_ids = [m.id for m in members]
    rows = db.execute(
        select(
            canon_id.label("cid"),
            func.count(Notice.notice_id),
            func.coalesce(func.sum(Notice.layoff_count), 0),
        )
        .select_from(Notice)
        .join(Company, Notice.company_id == Company.id, isouter=True)
        .where(canon_id.in_(member_ids))
        .where(Notice.is_superseded.is_(False))
        .group_by(canon_id)
    ).all()
    stats = {r[0]: (int(r[1]), int(r[2])) for r in rows}

    out = [
        FamilyMemberOut(
            company_id=m.id,
            name=m.name,
            notice_count=stats.get(m.id, (0, 0))[0],
            layoff_total=stats.get(m.id, (0, 0))[1],
            is_self=(m.id == canonical_id),
        )
        for m in members
    ]
    out.sort(key=lambda x: x.layoff_total, reverse=True)
    return out
