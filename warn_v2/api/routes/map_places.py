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

import sys
from datetime import date
from typing import NamedTuple

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_db
from warn_v2.api.filters import apply_notice_filters, apply_stats_closure_filter
from warn_v2.api.timeline import (
    Body,
    Bucket,
    TTLCache,
    body_response,
    json_bytes,
    month_col,
    period_of,
    period_range,
)
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


class PlaceFilters(NamedTuple):
    """The timeline's filter set: the rows-cache key (the body cache adds the
    bucket). Dates are parsed, so "2015-01-01" and "2015-1-1" share an entry."""

    state: str | None = None
    closure_category: str | None = None
    industry: str | None = None
    subsector: str | None = None
    after: date | None = None
    before: date | None = None


class _PlaceMonths(NamedTuple):
    lat: list[float]
    lon: list[float]
    label: list[str]
    # (place index, "YYYY-MM", notices, workers), one per non-empty cell.
    cells: list[tuple[int, str, int, int]]


# ~12 MB for monthly since 1999 at prod scale (measured on a synthetic
# 12k-place, 80k-cell set); the three warmed windows plus a few taps.
_rows_cache: TTLCache[_PlaceMonths] = TTLCache(max_entries=6)
# A body is ~1.5 MB raw at prod scale, plus its gzip copy (both count); 32 MB
# holds every unfiltered window x bucket plus a run of linked-view taps. The
# pod's limit is 512 Mi.
_body_cache: TTLCache[Body] = TTLCache(max_entries=64, max_bytes=32 << 20)


def _query_place_months(db: Session, f: PlaceFilters) -> _PlaceMonths:
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
    stmt = apply_stats_closure_filter(stmt, f.closure_category)
    stmt = apply_notice_filters(
        stmt,
        state=f.state,
        industry=f.industry,
        subsector=f.subsector,
        after=f.after,
        before=f.before,
        location_joined=True,
    )

    places: dict[tuple[float, float], int] = {}
    out = _PlaceMonths([], [], [], [])
    for r in db.execute(stmt).all():
        key = (round(float(r.lat), 4), round(float(r.lon), 4))
        i = places.get(key)
        if i is None:
            i = places[key] = len(places)
            out.lat.append(key[0])
            out.lon.append(key[1])
            out.label.append(f"{r.city}, {r.state}" if r.city else r.state)
        # Interned: a few hundred distinct months shared by ~80k cells.
        out.cells.append((i, sys.intern(r.month), r.notices, int(r.workers)))
    return out


def place_months(db: Session, f: PlaceFilters, *, refresh: bool = False) -> _PlaceMonths:
    """The (place, month) grouping for ``f``, cached."""
    return _rows_cache.get_or_compute(f, lambda: _query_place_months(db, f), refresh=refresh)


def timeline_body(
    db: Session, bucket: Bucket, f: PlaceFilters, *, refresh: bool = False
) -> Body:
    """The serialized /map-places/timeline body, cached. A miss (or
    ``refresh``) rolls it up from the cached month grouping."""

    def build() -> Body:
        months = place_months(db, f)
        cells: dict[tuple[str, int], list[int]] = {}
        for i, month, n, w in months.cells:
            cell = cells.setdefault((period_of(month, bucket), i), [0, 0])
            cell[0] += n
            cell[1] += w
        periods = period_range({p for p, _ in cells}, bucket)
        index = {p: k for k, p in enumerate(periods)}
        ordered = sorted(cells.items(), key=lambda kv: (index[kv[0][0]], kv[0][1]))
        return Body.of(json_bytes({
            "lat": months.lat,
            "lon": months.lon,
            "label": months.label,
            "periods": periods,
            "place": [i for (_, i), _ in ordered],
            "period": [index[p] for (p, _), _ in ordered],
            "notices": [c[0] for _, c in ordered],
            "workers": [c[1] for _, c in ordered],
        }))

    return _body_cache.get_or_compute((bucket, f), build, refresh=refresh)


def clear_timeline_cache() -> None:
    _rows_cache.clear()
    _body_cache.clear()


@router.get("/timeline")
def map_places_timeline(
    request: Request,
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
) -> Response:
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
    f = PlaceFilters(
        state and state.upper(), closure_category, industry, subsector, after, before
    )
    return body_response(
        request, timeline_body(db, bucket, f), {"Cache-Control": "public, max-age=300"}
    )
