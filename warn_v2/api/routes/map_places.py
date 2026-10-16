"""Routes: /api/map-places — geocoded notices aggregated per place for /map.

/api/map-pins sends one row per notice, which stopped scaling once the
geocoded set passed ~80 000: the full set is megabytes, and one browser marker
per notice is what made the map unusable on phones. Most geocodes are city
centroids, though, so 80k notices sit on only ~10-15k distinct points. This
endpoint groups by point (rounded to 4 dp, ~11 m) and returns each place's
notice count and total workers — the whole filtered set in one small payload,
which the client clusters on the GPU.

The body is columnar (parallel arrays) rather than a list of objects: with
~15k rows the repeated keys would be most of the payload.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.filters import apply_notice_filters
from warn_v2.db.models import Location, Notice

router = APIRouter(prefix="/map-places", tags=["map"])


@router.get("")
def list_map_places(
    state: str | None = Query(None, description="Two-letter state code, e.g. CA"),
    closure_category: str | None = Query(
        None, description="Normalized closure type: Closure | Layoff | Non-WARN"
    ),
    industry: str | None = Query(
        None, description="NAICS sector id (e.g. 31-33) of the linked company"
    ),
    subsector: str | None = Query(
        None, description="3-digit NAICS subsector (e.g. 311); narrows within a sector"
    ),
    min_layoffs: int | None = Query(
        None,
        ge=1,
        description="Only notices reporting at least this many affected workers "
        "(notices with no reported count are excluded)",
    ),
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Return ``{lat, lon, notices, workers, label}`` as parallel arrays, one
    entry per distinct point, busiest place first.

    ``workers`` sums reported layoff counts; notices without a count add to
    ``notices`` but not ``workers``. ``label`` is "City, ST" (or just "ST" when
    the point has no city) for the map's place search.
    """
    lat = func.round(Location.lat, 4)
    lon = func.round(Location.lon, 4)
    notices = func.count()
    stmt = (
        select(
            lat.label("lat"),
            lon.label("lon"),
            notices.label("notices"),
            func.coalesce(func.sum(Notice.layoff_count), 0).label("workers"),
            func.min(Location.city).label("city"),
            func.min(Location.state).label("state"),
        )
        .join(Location, Notice.location_id == Location.id)
        .where(
            Notice.is_superseded.is_(False),
            Location.lat.is_not(None),
            Location.lon.is_not(None),
        )
        .group_by(lat, lon)
        .order_by(notices.desc())
    )
    stmt = apply_notice_filters(
        stmt,
        state=state,
        closure_category=closure_category,
        industry=industry,
        subsector=subsector,
        min_layoffs=min_layoffs,
        after=after,
        before=before,
        location_joined=True,
    )

    rows = db.execute(stmt).all()
    body = {
        "lat": [round(float(r.lat), 4) for r in rows],
        "lon": [round(float(r.lon), 4) for r in rows],
        "notices": [r.notices for r in rows],
        "workers": [int(r.workers) for r in rows],
        "label": [f"{r.city}, {r.state}" if r.city else r.state for r in rows],
    }
    # Same staleness budget as /api/map-pins: scrapes land a few times a day.
    return JSONResponse(body, headers={"Cache-Control": "public, max-age=300"})
