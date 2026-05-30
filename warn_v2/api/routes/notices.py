"""Routes: /notices"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from warn_v2.api.deps import PaginationParams, get_db
from warn_v2.api.schemas import NoticeOut, Page
from warn_v2.db.models import Location, Notice

router = APIRouter(prefix="/notices", tags=["notices"])

_PDF_DIR = Path(os.getenv("PDF_DIR", "/var/pdfs"))

_SORT_COLUMNS = {
    "notice_date": Notice.notice_date,
    "state": Notice.state,
    "employer": Notice.employer,
    "layoff_count": Notice.layoff_count,
    "effective_date": Notice.effective_date,
}


@router.get("", response_model=Page[NoticeOut])
def list_notices(
    state: str | None = Query(None, description="Two-letter state code, e.g. CA"),
    employer: str | None = Query(None, description="Employer name (case-insensitive substring)"),
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    geocoded_only: bool = Query(False, description="Only return notices with latitude/longitude"),
    sort_by: str | None = Query(
        None, description="Column: notice_date, state, employer, layoff_count, effective_date"
    ),
    sort_dir: str | None = Query("desc", description="asc or desc"),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
) -> Page[NoticeOut]:
    col = _SORT_COLUMNS.get(sort_by or "notice_date", Notice.notice_date)
    order_expr = col.asc().nullslast() if sort_dir == "asc" else col.desc().nullslast()
    stmt = (
        select(Notice)
        .options(joinedload(Notice.company), joinedload(Notice.location))
        .where(Notice.is_superseded.is_(False))
        .order_by(order_expr, Notice.scraped_at.desc())
    )
    count_stmt = select(func.count()).select_from(Notice).where(Notice.is_superseded.is_(False))

    if state:
        stmt = stmt.where(Notice.state == state.upper())
        count_stmt = count_stmt.where(Notice.state == state.upper())
    if employer:
        pattern = f"%{employer}%"
        stmt = stmt.where(Notice.employer.ilike(pattern))
        count_stmt = count_stmt.where(Notice.employer.ilike(pattern))
    if after:
        stmt = stmt.where(Notice.notice_date >= after)
        count_stmt = count_stmt.where(Notice.notice_date >= after)
    if before:
        stmt = stmt.where(Notice.notice_date <= before)
        count_stmt = count_stmt.where(Notice.notice_date <= before)
    if geocoded_only:
        # Join to locations and require non-null lat/lon.
        stmt = stmt.join(Location, Notice.location_id == Location.id).where(
            Location.lat.is_not(None), Location.lon.is_not(None)
        )
        count_stmt = count_stmt.join(Location, Notice.location_id == Location.id).where(
            Location.lat.is_not(None), Location.lon.is_not(None)
        )

    total = db.scalar(count_stmt) or 0
    items = list(db.scalars(stmt.offset(pagination.offset).limit(pagination.limit)))
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/{notice_id}", response_model=NoticeOut)
def get_notice(
    notice_id: str,
    db: Session = Depends(get_db),
) -> NoticeOut:
    notice = db.scalar(
        select(Notice)
        .options(joinedload(Notice.company), joinedload(Notice.location))
        .where(Notice.notice_id == notice_id)
    )
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found")
    return notice


@router.get("/{notice_id}/pdf")
def get_notice_pdf(notice_id: str, db: Session = Depends(get_db)) -> FileResponse:
    notice = db.get(Notice, notice_id)
    if notice is None or notice.pdf_path is None:
        raise HTTPException(status_code=404, detail="PDF not available")
    full_path = (_PDF_DIR / notice.pdf_path).resolve()
    pdf_dir_resolved = _PDF_DIR.resolve()
    if not str(full_path).startswith(str(pdf_dir_resolved)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="PDF file missing")
    return FileResponse(full_path, media_type="application/pdf")
