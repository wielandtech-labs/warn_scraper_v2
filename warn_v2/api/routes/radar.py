"""Routes: /radar + /notices/{id}/occupation-mix — the forward-looking view.

WARN notices must be filed at least 60 days before the separation date, so
``effective_date`` is a forward signal: it says when an affected cohort
actually hits the labor market. Every other view is retrospective on
``notice_date``; the radar lists notices whose effective date is still
ahead, soonest first.

The occupation mix applies the national BLS OEWS staffing pattern for the
company's NAICS industry to the notice's ``layoff_count`` (see
``warn_v2.labor.oews``). It is a statistical prior from the industry's
employment mix — not information about the actual affected roles — and both
endpoints' consumers must present it as such.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from warn_v2.api.deps import PaginationParams, get_db
from warn_v2.api.filters import apply_notice_filters
from warn_v2.api.schemas import Page
from warn_v2.companies.naics import SECTOR_NAME, sector_for_code
from warn_v2.db.models import Notice
from warn_v2.labor import oews

router = APIRouter(tags=["radar"])

# Occupations shown inline per radar row; the full pattern (≤12) stays on the
# per-notice occupation-mix endpoint to keep list payloads small.
_PREVIEW_OCCUPATIONS = 3


class OccupationEstimate(BaseModel):
    soc_code: str
    title: str
    pct: float  # percent of the industry's employment (OEWS PCT_TOTAL)
    # round(layoff_count * pct / 100); None when the notice has no count.
    estimate: int | None


class RadarNoticeOut(BaseModel):
    notice_id: str
    employer: str
    company_id: int | None
    state: str
    city: str | None
    county: str | None
    notice_date: date | None
    effective_date: date  # non-null by construction (the radar keys on it)
    days_until: int
    layoff_count: int | None
    closure_category: str | None
    naics_code: str | None  # None → "industry unknown" in the UI
    sector: str | None
    sector_name: str | None
    occupation_preview: list[OccupationEstimate] | None  # None when no pattern
    oews_vintage: str | None


class OccupationMixOut(BaseModel):
    notice_id: str
    available: bool
    reason: str | None  # "no_naics" | "no_pattern" when unavailable
    naics_code: str | None
    matched_naics: str | None  # the OEWS key that matched, e.g. "3119"
    match_level: str | None  # "4-digit" | "3-digit" | "sector"
    industry_title: str | None
    coverage_pct: float | None  # share of industry employment the list covers
    layoff_count: int | None
    oews_vintage: str | None
    occupations: list[OccupationEstimate]


def _today() -> date:
    """Current UTC date. Module-level so tests can monkeypatch it."""
    return datetime.now(UTC).date()


def _estimates(
    occupations: list[tuple[str, str, float]], layoff_count: int | None
) -> list[OccupationEstimate]:
    return [
        OccupationEstimate(
            soc_code=soc,
            title=title,
            pct=pct,
            estimate=round(layoff_count * pct / 100) if layoff_count else None,
        )
        for soc, title, pct in occupations
    ]


def _radar_row(notice: Notice, today: date) -> RadarNoticeOut:
    naics = notice.company.naics_code if notice.company else None
    sector = sector_for_code(naics)
    preview: list[OccupationEstimate] | None = None
    pattern = oews.lookup(naics)
    if pattern:
        preview = _estimates(
            pattern.occupations[:_PREVIEW_OCCUPATIONS], notice.layoff_count
        )
    return RadarNoticeOut(
        notice_id=notice.notice_id,
        employer=notice.employer,
        company_id=notice.company_id,
        state=notice.state,
        city=notice.location.city if notice.location else None,
        county=notice.location.county if notice.location else None,
        notice_date=notice.notice_date,
        effective_date=notice.effective_date,
        days_until=(notice.effective_date - today).days,
        layoff_count=notice.layoff_count,
        closure_category=notice.closure_category,
        naics_code=naics,
        sector=sector,
        sector_name=SECTOR_NAME.get(sector) if sector else None,
        occupation_preview=preview,
        oews_vintage=oews.data_vintage() if preview else None,
    )


@router.get("/radar", response_model=Page[RadarNoticeOut])
def radar(
    state: str | None = Query(None, description="Two-letter state code, e.g. CA"),
    closure_category: str | None = Query(
        None, description="Normalized closure type: Closure | Layoff"
    ),
    industry: str | None = Query(
        None, description="NAICS sector id (e.g. 31-33) of the linked company"
    ),
    subsector: str | None = Query(
        None, description="3-digit NAICS subsector (e.g. 311); narrows within a sector"
    ),
    min_layoffs: int = Query(
        0, ge=0, description="Only cohorts of at least this many workers (drops unknown counts)"
    ),
    days: int | None = Query(
        None, ge=1, le=730, description="Horizon: only effective dates within this many days"
    ),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
) -> Page[RadarNoticeOut]:
    """Upcoming layoff cohorts: notices whose effective date is today or later,
    soonest first. Notices without a dated separation stay on /notices."""
    today = _today()
    stmt = (
        select(Notice)
        .options(joinedload(Notice.company), joinedload(Notice.location))
        .order_by(
            Notice.effective_date.asc(),
            Notice.layoff_count.desc().nullslast(),
            Notice.scraped_at.desc(),
        )
    )
    count_stmt = select(func.count()).select_from(Notice)

    def _conditions(s):
        s = s.where(Notice.is_superseded.is_(False), Notice.effective_date >= today)
        # No industry filter ⇒ no Company join ⇒ notices with no linked
        # company (NAICS unknown) are included, per the graceful-degradation
        # requirement; an industry filter correctly excludes them.
        s = apply_notice_filters(
            s,
            state=state,
            closure_category=closure_category,
            industry=industry,
            subsector=subsector,
        )
        if min_layoffs > 0:
            s = s.where(Notice.layoff_count >= min_layoffs)
        if days is not None:
            s = s.where(Notice.effective_date <= today + timedelta(days=days))
        return s

    stmt = _conditions(stmt)
    count_stmt = _conditions(count_stmt)

    total = db.scalar(count_stmt) or 0
    notices = list(db.scalars(stmt.offset(pagination.offset).limit(pagination.limit)))
    return Page(
        items=[_radar_row(n, today) for n in notices],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/notices/{notice_id}/occupation-mix", response_model=OccupationMixOut)
def occupation_mix(notice_id: str, db: Session = Depends(get_db)) -> OccupationMixOut:
    """The full estimated occupation mix for one notice (radar preview = top 3)."""
    notice = db.scalar(
        select(Notice)
        .options(joinedload(Notice.company))
        .where(Notice.notice_id == notice_id)
    )
    if notice is None:
        raise HTTPException(status_code=404, detail="Notice not found")

    naics = notice.company.naics_code if notice.company else None
    pattern = oews.lookup(naics)
    if pattern is None:
        # A malformed code (non-digit junk) counts as "no usable NAICS", not
        # as an OEWS coverage gap.
        usable = bool(naics and naics.strip().isdigit())
        return OccupationMixOut(
            notice_id=notice.notice_id,
            available=False,
            reason="no_pattern" if usable else "no_naics",
            naics_code=naics,
            matched_naics=None,
            match_level=None,
            industry_title=None,
            coverage_pct=None,
            layoff_count=notice.layoff_count,
            oews_vintage=None,
            occupations=[],
        )
    return OccupationMixOut(
        notice_id=notice.notice_id,
        available=True,
        reason=None,
        naics_code=naics,
        matched_naics=pattern.naics_key,
        match_level=pattern.level,
        industry_title=pattern.industry_title,
        coverage_pct=pattern.coverage_pct,
        layoff_count=notice.layoff_count,
        oews_vintage=oews.data_vintage(),
        occupations=_estimates(pattern.occupations, notice.layoff_count),
    )
