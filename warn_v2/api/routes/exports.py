"""Routes: /api/notices/export and /api/companies/export.

Bulk CSV/JSON download reusing the same filters as the list endpoints
(warn_v2.api.filters). Access is role-gated via the session cookie or API key:

- anonymous / free    -> capped at FREE_EXPORT_CAP rows, public columns only
- paid                -> up to PAID_EXPORT_CAP rows, plus D&B-enriched columns
                         (minus raw DUNS identifiers)
- enterprise / admin  -> paid columns plus raw DUNS identifiers

Memory discipline: exports select plain column tuples (never ORM entities) and
stream through a server-side cursor (yield_per), so peak memory is one batch
of rows regardless of export size. The previous implementation materialised
every notice as an ORM object with joined Company/Location before streaming —
a full-dataset export blew through the pod's 512Mi limit and took the API down
(OOM -> 502), seen in prod 2026-07-07.
"""
from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator, Mapping
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from warn_v2.api.deps import get_current_user, get_db
from warn_v2.api.filters import apply_notice_filters
from warn_v2.companies.naics import naics_filter
from warn_v2.db.models import Company, Location, Notice, User

router = APIRouter(tags=["export"])

FREE_EXPORT_CAP = 1_000
PAID_EXPORT_CAP = 200_000  # generous ceiling, comfortably above the full dataset
_YIELD_PER = 1_000  # rows fetched per server-side cursor batch

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
    if isinstance(v, date):  # datetime is a date subclass — both become ISO
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _stream_rows(db: Session, stmt) -> Iterator[Mapping]:
    """Execute with a server-side cursor; yields one RowMapping at a time.

    The generator runs while the StreamingResponse body is being sent; FastAPI
    closes the get_db dependency (and with it this cursor) only after the
    response completes, so streaming from the request's session is safe.
    """
    for row in db.execute(stmt.execution_options(yield_per=_YIELD_PER)):
        yield row._mapping


def _respond(
    fmt: str, columns: list[str], rows: Iterator[Mapping], filename: str
) -> StreamingResponse:
    """Stream rows as CSV or a JSON array without ever holding them all."""
    if fmt == "json":

        def stream_json() -> Iterator[str]:
            yield "["
            sep = ""
            for r in rows:
                yield sep + json.dumps({c: _coerce(r.get(c)) for c in columns})
                sep = ","
            yield "]"

        return StreamingResponse(stream_json(), media_type="application/json")

    def stream_csv() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(columns)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        for r in rows:
            writer.writerow([_coerce(r.get(c)) for c in columns])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)

    return StreamingResponse(
        stream_csv(),
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
) -> StreamingResponse:
    # Column tuples only — every column any tier can see is selected (unemitted
    # ones never leave the process), so one statement serves all tiers.
    stmt = (
        select(
            Notice.notice_id, Notice.state, Notice.employer, Notice.notice_date,
            Notice.effective_date, Notice.layoff_count, Notice.closure_category,
            Company.name.label("company_name"), Company.naics_code, Company.naics_desc,
            Location.city, Location.county, Location.zip, Location.lat, Location.lon,
            Notice.source_url, Notice.raw_notice_url,
            Company.parent_company_name, Company.global_ultimate_name,
            Company.employee_count, Company.duns.label("company_duns"),
        )
        .select_from(Notice)
        .outerjoin(Company, Company.id == Notice.company_id)
        .outerjoin(Location, Location.id == Notice.location_id)
        .where(Notice.is_superseded.is_(False))
        .order_by(Notice.notice_date.desc().nullslast(), Notice.scraped_at.desc())
    )
    stmt = apply_notice_filters(
        stmt,
        state=state, employer=employer, closure_category=closure_category,
        industry=industry, subsector=subsector, after=after, before=before,
        geocoded_only=geocoded_only,
        location_joined=True, company_joined=True,
    )
    columns = list(_NOTICE_PUBLIC_COLS)
    if access.enriched:
        columns += _NOTICE_ENRICHED_COLS
    if access.enterprise:
        columns += _NOTICE_ENTERPRISE_COLS
    return _respond(
        format, columns, _stream_rows(db, stmt.limit(access.cap)), "warn-notices"
    )


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
) -> StreamingResponse:
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
    stmt = (
        select(
            Company.id, Company.name, Company.sic_code, Company.sic_desc,
            Company.naics_code, Company.naics_desc, Company.website,
            Company.enriched_at, Company.enrichment_confidence,
            Company.enrichment_source,
            func.coalesce(totals_sq.c.layoff_total, 0).label("layoff_total"),
            Company.parent_company_name, Company.global_ultimate_name,
            Company.hq_address, Company.employee_count,
            Company.duns, Company.parent_duns,
        )
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
    return _respond(
        format, columns, _stream_rows(db, stmt.limit(access.cap)), "warn-companies"
    )
