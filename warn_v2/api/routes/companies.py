"""Routes: /companies"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import PaginationParams, get_db
from warn_v2.api.schemas import CompanyOut, NoticeOut, Page
from warn_v2.db.models import Company, Notice

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=Page[CompanyOut])
def list_companies(
    enriched: bool | None = Query(None, description="Filter by enrichment status"),
    sic_code: str | None = Query(None, description="Exact SIC code match"),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
) -> Page[CompanyOut]:
    stmt = select(Company).order_by(Company.name)
    count_stmt = select(func.count()).select_from(Company)

    if enriched is True:
        stmt = stmt.where(Company.enriched_at.is_not(None))
        count_stmt = count_stmt.where(Company.enriched_at.is_not(None))
    elif enriched is False:
        stmt = stmt.where(Company.enriched_at.is_(None))
        count_stmt = count_stmt.where(Company.enriched_at.is_(None))

    if sic_code:
        stmt = stmt.where(Company.sic_code == sic_code)
        count_stmt = count_stmt.where(Company.sic_code == sic_code)

    total = db.scalar(count_stmt) or 0
    items = list(db.scalars(stmt.offset(pagination.offset).limit(pagination.limit)))
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(
    company_id: int,
    db: Session = Depends(get_db),
) -> CompanyOut:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return company


@router.get("/{company_id}/notices", response_model=Page[NoticeOut])
def list_company_notices(
    company_id: int,
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
) -> Page[NoticeOut]:
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found")

    stmt = (
        select(Notice)
        .where(Notice.company_id == company_id)
        .order_by(Notice.notice_date.desc().nullslast())
    )
    count_stmt = (
        select(func.count())
        .select_from(Notice)
        .where(Notice.company_id == company_id)
    )
    total = db.scalar(count_stmt) or 0
    items = list(db.scalars(stmt.offset(pagination.offset).limit(pagination.limit)))
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)
