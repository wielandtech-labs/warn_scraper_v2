"""Routes: /api/map-pins — lightweight geocoded-notice list for the map view.

This endpoint lives at /api/map-pins (not under /api/notices) to avoid a
routing conflict with the parametric /api/notices/{notice_id} route.

It intentionally returns a plain list (no pagination wrapper) and projects
only the 7 fields the map popup renders — employer, state, notice_date,
layoff_count, lat, lon — keeping each record ~7x smaller than a full
NoticeOut. This lets the map fetch every geocoded notice in the selected
time frame in a single request instead of being capped at the 500-item
limit that applies to the general /notices endpoint.

The geocoded set has outgrown a single screenful (~22 500 and climbing), so
the map sends the current viewport (``min_lat``/``min_lon``/``max_lat``/
``max_lon``) and we filter to it — zooming in returns only what's visible.
The 50 000 ``limit`` ceiling is a safety cap on the zoomed-all-the-way-out
case; as the dataset grows past it, zooming in still loads each region's pins
in full.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.schemas import MapPinOut
from warn_v2.companies.naics import naics_filter
from warn_v2.db.models import Company, Location, Notice

router = APIRouter(prefix="/map-pins", tags=["map"])


@router.get("", response_model=list[MapPinOut])
def list_map_pins(
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
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    min_lat: float | None = Query(None, description="Viewport south bound (with the other 3)"),
    min_lon: float | None = Query(None, description="Viewport west bound (with the other 3)"),
    max_lat: float | None = Query(None, description="Viewport north bound (with the other 3)"),
    max_lon: float | None = Query(None, description="Viewport east bound (with the other 3)"),
    limit: int = Query(50_000, ge=1, le=50_000, description="Max pins to return (ceiling 50 000)"),
    db: Session = Depends(get_db),
) -> list[MapPinOut]:
    """Return lightweight pin objects for every geocoded notice matching the filters.

    Always joins to locations and requires lat/lon IS NOT NULL, so every
    returned item is safe to place on the map without client-side filtering.
    Ordered newest-first so clusters reflect the most recent activity.
    """
    stmt = (
        select(
            Notice.notice_id,
            Notice.employer,
            Notice.state,
            Notice.notice_date,
            Notice.layoff_count,
            Location.lat,
            Location.lon,
        )
        .join(Location, Notice.location_id == Location.id)
        .where(
            Notice.is_superseded.is_(False),
            Location.lat.is_not(None),
            Location.lon.is_not(None),
        )
        .order_by(Notice.notice_date.desc().nullslast(), Notice.scraped_at.desc())
    )

    if state:
        stmt = stmt.where(Notice.state == state.upper())
    if closure_category:
        stmt = stmt.where(Notice.closure_category == closure_category)
    industry_filter = naics_filter(Company.naics_code, industry, subsector)
    if industry_filter is not None:
        # Inner-join the linked company; un-enriched notices (no NAICS) are
        # correctly excluded when an industry filter is active.
        stmt = stmt.join(Company, Notice.company_id == Company.id).where(industry_filter)
    if after:
        stmt = stmt.where(Notice.notice_date >= after)
    if before:
        stmt = stmt.where(Notice.notice_date <= before)
    # Viewport filter: only applied when the full box is provided. Lets the map
    # request just the visible pins as the user pans/zooms (antimeridian-crossing
    # boxes aren't handled — irrelevant for the contiguous US + mainland AK).
    if None not in (min_lat, min_lon, max_lat, max_lon):
        stmt = stmt.where(
            Location.lat >= min_lat,
            Location.lat <= max_lat,
            Location.lon >= min_lon,
            Location.lon <= max_lon,
        )

    rows = db.execute(stmt.limit(limit)).all()
    return [MapPinOut(**r._mapping) for r in rows]
