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
from warn_v2.api.filters import apply_notice_filters, apply_stats_closure_filter
from warn_v2.api.timeline import Bucket, month_col, period_of, period_range
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


@router.get("/timeline")
def map_places_timeline(
    bucket: Bucket = Query("quarter", description="Time bucket: year | quarter | month"),
    state: str | None = Query(None, description="Two-letter state code, e.g. CA"),
    closure_category: str | None = Query(
        None, description="Closure | Layoff | Non-WARN (default: all but Non-WARN)"
    ),
    industry: str | None = Query(
        None, description="NAICS sector id (e.g. 31-33) of the linked company"
    ),
    subsector: str | None = Query(
        None, description="3-digit NAICS subsector (e.g. 311); narrows within a sector"
    ),
    after: date | None = Query(None, description="Only notices on or after this date"),
    before: date | None = Query(None, description="Only notices on or before this date"),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Per-place counts for every period, for the /timelapse map: one payload
    the client scrubs through without a request per frame.

    ``periods`` is the contiguous range of bucket keys ("2020", "2020-Q2" or
    "2020-04"), oldest first. ``lat``/``lon``/``label`` describe each place as
    in /api/map-places. The counts are sparse — only (place, period) pairs
    with at least one notice — as parallel arrays: ``place`` and ``period``
    index into the arrays above, ``notices``/``workers`` are that cell's
    counts. Unlike /api/map-places, Non-WARN events are left out unless
    ``closure_category`` asks for them, as on every stats chart.
    """
    lat = func.round(Location.lat, 4)
    lon = func.round(Location.lon, 4)
    stmt = (
        select(
            lat.label("lat"),
            lon.label("lon"),
            month_col.label("month"),
            func.count().label("notices"),
            func.coalesce(func.sum(Notice.layoff_count), 0).label("workers"),
            func.min(Location.city).label("city"),
            func.min(Location.state).label("state"),
        )
        .join(Location, Notice.location_id == Location.id)
        .where(
            Notice.is_superseded.is_(False),
            Notice.notice_date.is_not(None),
            Location.lat.is_not(None),
            Location.lon.is_not(None),
        )
        .group_by(lat, lon, month_col)
        .order_by(lat, lon, month_col)
    )
    stmt = apply_stats_closure_filter(stmt, closure_category)
    stmt = apply_notice_filters(
        stmt,
        state=state,
        industry=industry,
        subsector=subsector,
        after=after,
        before=before,
        location_joined=True,
    )

    places: dict[tuple[float, float], int] = {}
    body: dict[str, list] = {k: [] for k in ("lat", "lon", "label")}
    cells: dict[tuple[str, int], list[int]] = {}
    for r in db.execute(stmt).all():
        key = (round(float(r.lat), 4), round(float(r.lon), 4))
        i = places.get(key)
        if i is None:
            i = places[key] = len(places)
            body["lat"].append(key[0])
            body["lon"].append(key[1])
            body["label"].append(f"{r.city}, {r.state}" if r.city else r.state)
        cell = cells.setdefault((period_of(r.month, bucket), i), [0, 0])
        cell[0] += r.notices
        cell[1] += int(r.workers)

    periods = period_range({p for p, _ in cells}, bucket)
    index = {p: k for k, p in enumerate(periods)}
    ordered = sorted(cells.items(), key=lambda kv: (index[kv[0][0]], kv[0][1]))
    body["periods"] = periods
    body["place"] = [i for (_, i), _ in ordered]
    body["period"] = [index[p] for (p, _), _ in ordered]
    body["notices"] = [c[0] for _, c in ordered]
    body["workers"] = [c[1] for _, c in ordered]
    return JSONResponse(body, headers={"Cache-Control": "public, max-age=300"})
