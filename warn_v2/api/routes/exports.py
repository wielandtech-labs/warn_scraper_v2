"""Routes: /api/notices/export and /api/companies/export.

Bulk CSV/JSON download reusing the same filters as the list endpoints
(warn_v2.api.filters). Access is role-gated via the session cookie:

- anonymous / free    -> capped at FREE_EXPORT_CAP rows, public columns only
- paid                -> up to PAID_EXPORT_CAP rows, plus D&B-enriched columns
                         (minus raw DUNS identifiers)
- enterprise / admin  -> paid columns plus raw DUNS identifiers

Rows are materialised up to the cap (the full dataset is well within memory)
then the CSV is streamed row-by-row so the response body isn't built as one
giant string.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, joinedload

from warn_v2.api.deps import get_current_user, get_db
from warn_v2.api.filters import apply_notice_filters
from warn_v2.companies.naics import naics_filter
from warn_v2.db.models import Company, Notice, User

router = APIRouter(tags=["export"])

FREE_EXPORT_CAP = 1_000
PAID_EXPORT_CAP = 200_000  # generous ceiling, comfortably above the full dataset

_NOTICE_PUBLIC_COLS = [
    "notice_id", "state", "employer", "notice_date", "effective_date",
    "layoff_count", "closure_category", "company_name", "naics_code", "naics_desc",
    "city", "county", "zip", "lat", "lon", "source_url", "raw_notice_url",
]
_NOTICE_ENRICHED_COLS = [
    "parent_company_name", "global_ultimate_name", "employee_count",
]
_NOTICE_ENTERPRISE_COLS = ["company_duns"]

_COMPANY_PUBLIC_COLS = [
    "id", "name", "sic_code", "sic_desc", "naics_code", "naics_desc", "website",
    "enriched_at", "enrichment_confidence", "enrichment_source", "layoff_total",
]
_COMPANY_ENRICHED_COLS = [
    "parent_company_name", "global_ultimate_name", "hq_address", "employee_count",
]
_COMPANY_ENTERPRISE_COLS = ["duns", "parent_duns"]


class ExportAccess:
    """Row cap + enriched/enterprise-column visibility from the viewer's role."""

    def __init__(self, user: User | None = Depends(get_current_user)) -> None:
        role = user.role if user is not None else None
        self.enterprise = role in ("enterprise", "admin")
        self.enriched = self.enterprise or role == "paid"
        self.cap = PAID_EXPORT_CAP if self.enriched else FREE_EXPORT_CAP


def _coerce(v: object) -> object:
    """JSON/CSV-friendly scalar: dates -> ISO string, Decimal -> float."""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _respond(
    fmt: str, columns: list[str], records: list[dict], filename: str
) -> StreamingResponse | JSONResponse:
    if fmt == "json":
        return JSONResponse(content=[{c: _coerce(r.get(c)) for c in columns} for r in records])

    def stream():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for r in records:
            writer.writerow([_coerce(r.get(c)) for c in columns])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        stream(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@router.get("/notices/export", response_model=None)
def export_notices(
    state: str | None = Query(None),
    employer: str | None = Query(None),
    closure_category: str | None = Query(None),
    industry: str | None = Query(None),
    subsector: str | None = Query(None),
    after: date | None = Query(None),
    before: date | None = Query(None),
    geocoded_only: bool = Query(False),
    format: str = Query("csv", pattern="^(csv|json)$"),
    access: ExportAccess = Depends(),
    db: Session = Depends(get_db),
) -> StreamingResponse | JSONResponse:
    stmt = (
        select(Notice)
        .options(joinedload(Notice.company), joinedload(Notice.location))
        .where(Notice.is_superseded.is_(False))
        .order_by(Notice.notice_date.desc().nullslast(), Notice.scraped_at.desc())
    )
    stmt = apply_notice_filters(
        stmt,
        state=state, employer=employer, closure_category=closure_category,
        industry=industry, subsector=subsector, after=after, before=before,
        geocoded_only=geocoded_only,
    )
    columns = list(_NOTICE_PUBLIC_COLS)
    if access.enriched:
        columns += _NOTICE_ENRICHED_COLS
    if access.enterprise:
        columns += _NOTICE_ENTERPRISE_COLS

    records = []
    for n in db.scalars(stmt.limit(access.cap)).unique():
        c, loc = n.company, n.location
        rec = {
            "notice_id": n.notice_id, "state": n.state, "employer": n.employer,
            "notice_date": n.notice_date, "effective_date": n.effective_date,
            "layoff_count": n.layoff_count, "closure_category": n.closure_category,
            "company_name": c.name if c else None,
            "naics_code": c.naics_code if c else None,
            "naics_desc": c.naics_desc if c else None,
            "city": loc.city if loc else None, "county": loc.county if loc else None,
            "zip": loc.zip if loc else None,
            "lat": loc.lat if loc else None, "lon": loc.lon if loc else None,
            "source_url": n.source_url, "raw_notice_url": n.raw_notice_url,
        }
        if access.enriched:
            rec.update({
                "parent_company_name": c.parent_company_name if c else None,
                "global_ultimate_name": c.global_ultimate_name if c else None,
                "employee_count": c.employee_count if c else None,
            })
        if access.enterprise:
            rec["company_duns"] = c.duns if c else None
        records.append(rec)
    return _respond(format, columns, records, "warn-notices")


@router.get("/companies/export", response_model=None)
def export_companies(
    name: str | None = Query(None),
    enriched: bool | None = Query(None),
    has_duns: bool | None = Query(None),
    sic_code: str | None = Query(None),
    industry: str | None = Query(None),
    subsector: str | None = Query(None),
    include_merged: bool = Query(False),
    format: str = Query("csv", pattern="^(csv|json)$"),
    access: ExportAccess = Depends(),
    db: Session = Depends(get_db),
) -> StreamingResponse | JSONResponse:
    # Layoff rollup per canonical company (mirrors the /companies list route).
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
    stmt = (
        select(Company, layoff_total)
        .outerjoin(totals_sq, totals_sq.c.cid == Company.id)
        .order_by(Company.name)
    )
    if not include_merged:
        stmt = stmt.where(Company.canonical_company_id.is_(None))
    if name:
        stmt = stmt.where(Company.name.ilike(f"%{name}%"))
    if enriched is True:
        stmt = stmt.where(Company.enriched_at.is_not(None))
    elif enriched is False:
        stmt = stmt.where(Company.enriched_at.is_(None))
    if has_duns is True:
        stmt = stmt.where(Company.duns.is_not(None))
    elif has_duns is False:
        stmt = stmt.where(Company.duns.is_(None))
    if sic_code:
        stmt = stmt.where(Company.sic_code == sic_code)
    ind = naics_filter(Company.naics_code, industry, subsector)
    if ind is not None:
        stmt = stmt.where(ind)

    columns = list(_COMPANY_PUBLIC_COLS)
    if access.enriched:
        columns += _COMPANY_ENRICHED_COLS
    if access.enterprise:
        columns += _COMPANY_ENTERPRISE_COLS

    records = []
    for company, total in db.execute(stmt.limit(access.cap)).all():
        rec = {
            "id": company.id, "name": company.name, "sic_code": company.sic_code,
            "sic_desc": company.sic_desc, "naics_code": company.naics_code,
            "naics_desc": company.naics_desc, "website": company.website,
            "enriched_at": company.enriched_at,
            "enrichment_confidence": company.enrichment_confidence,
            "enrichment_source": company.enrichment_source,
            "layoff_total": int(total),
        }
        if access.enriched:
            rec.update({
                "parent_company_name": company.parent_company_name,
                "global_ultimate_name": company.global_ultimate_name,
                "hq_address": company.hq_address,
                "employee_count": company.employee_count,
            })
        if access.enterprise:
            rec.update({"duns": company.duns, "parent_duns": company.parent_duns})
        records.append(rec)
    return _respond(format, columns, records, "warn-companies")
