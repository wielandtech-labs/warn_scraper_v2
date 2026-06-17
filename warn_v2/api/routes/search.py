"""Routes: /api/search — global company + notice autocomplete.

Substring-filters companies and notices by name/employer and ranks them by
trigram similarity on Postgres (backed by the gin_trgm_ops indexes from the
0014 migration); on SQLite (tests) it falls back to plain name/date ordering.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.schemas import SearchCompanyOut, SearchNoticeOut, SearchResults
from warn_v2.db.models import Company, Notice

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResults)
def search(
    q: str = Query(..., min_length=1, max_length=100, description="Search text"),
    limit: int = Query(8, ge=1, le=25, description="Max results of each type"),
    db: Session = Depends(get_db),
) -> SearchResults:
    term = q.strip()
    if not term:
        return SearchResults(companies=[], notices=[])
    pattern = f"%{term}%"
    is_pg = db.get_bind().dialect.name == "postgresql"

    # Companies: canonical rows only, substring-filtered, ranked by trigram
    # similarity on Postgres (name order on SQLite).
    comp_stmt = (
        select(Company.id, Company.name)
        .where(Company.canonical_company_id.is_(None), Company.name.ilike(pattern))
    )
    comp_stmt = (
        comp_stmt.order_by(func.similarity(Company.name, term).desc(), Company.name)
        if is_pg
        else comp_stmt.order_by(Company.name)
    )
    companies = [
        SearchCompanyOut(id=r.id, name=r.name)
        for r in db.execute(comp_stmt.limit(limit)).all()
    ]

    # Notices: non-superseded, employer substring; trigram-ranked on PG else newest.
    notice_stmt = (
        select(Notice.notice_id, Notice.employer, Notice.state, Notice.notice_date)
        .where(Notice.is_superseded.is_(False), Notice.employer.ilike(pattern))
    )
    notice_stmt = (
        notice_stmt.order_by(
            func.similarity(Notice.employer, term).desc(),
            Notice.notice_date.desc().nullslast(),
        )
        if is_pg
        else notice_stmt.order_by(Notice.notice_date.desc().nullslast())
    )
    notices = [
        SearchNoticeOut(
            notice_id=r.notice_id,
            employer=r.employer,
            state=r.state,
            notice_date=r.notice_date,
        )
        for r in db.execute(notice_stmt.limit(limit)).all()
    ]
    return SearchResults(companies=companies, notices=notices)
