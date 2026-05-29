"""Routes: /api/map-pins — lightweight geocoded-notice list for the map view.

This endpoint lives at /api/map-pins (not under /api/notices) to avoid a
routing conflict with the parametric /api/notices/{notice_id} route.

It intentionally returns a plain list (no pagination wrapper) and projects
only the 7 fields the map popup renders — employer, state, notice_date,
layoff_count, lat, lon — keeping each record ~7x smaller than a full
NoticeOut. This lets the map fetch every geocoded notice in the selected
time frame in a single request instead of being capped at the 500-item
limit that applies to the general /notices endpoint.

The limit ceiling (10 000) is a safety cap, not a practical constraint:
the DB currently has ~3 400 geocoded notices.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.schemas import MapPinOut
from warn_v2.db.models import Location, Notice

router = APIRouter(prefix="/map-pins", tags=["map"])


@router.get("", response_model=list[MapPinOut])
def list_map_pins(
    state: str | None = Query(None, description="Two-letter state code, e.g. CA"),
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    limit: int = Query(10_000, ge=1, le=10_000, description="Max pins to return (ceiling 10 000)"),
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
            Location.lat.is_not(None),
            Location.lon.is_not(None),
        )
        .order_by(Notice.notice_date.desc().nullslast(), Notice.scraped_at.desc())
    )

    if state:
        stmt = stmt.where(Notice.state == state.upper())
    if after:
        stmt = stmt.where(Notice.notice_date >= after)
    if before:
        stmt = stmt.where(Notice.notice_date <= before)

    rows = db.execute(stmt.limit(limit)).all()
    return [MapPinOut(**r._mapping) for r in rows]
