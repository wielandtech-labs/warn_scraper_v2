"""Geocoding: US Census address API → ZIP centroid → city centroid → county centroid.

Strategy (in priority order):
  1. US Census Geocoder — free, no API key, US-only, street-level precision.
     Requires a street address.  Called only when ``address`` is provided.
  2. ZIP centroid — local dictionary lookup, instant, ~city-block radius.
     Used when no address is available or Census call fails/returns nothing.
  3. City centroid — (state, city) lookup from the Census Places Gazetteer,
     ~city-level accuracy (~11 km).  Used when no ZIP is available and the
     first two tiers both return None.  Covers states whose WARN sources
     report city name but not ZIP code (e.g. AK, AL, MA, MN, TX, WA, …).
  4. County centroid — (state, county) lookup from the Census County Gazetteer,
     ~county-level accuracy (~30 km).  Last resort for states that report only
     county (e.g. KY, MT).

Every tier also resolves the containing **county** when the caller didn't
supply one: the Census ``geographies/`` endpoints return the county alongside
the coordinates (tier 1 gets it for free; tiers 2-3 reverse-look-up the
resolved coordinates via :func:`county_from_coords`).  Most WARN sources don't
publish a county column, so this is what feeds the county-based features.

The Census geocoder is called synchronously with a short timeout.  Any
exception (network error, rate-limit, bad JSON) falls through to ZIP centroid
so callers always get a best-effort result without raising.

Typical usage in storage.py::

    from warn_v2.geo.geocoder import geocode as _geocode
    result = _geocode(row.address, row.city, row.state, row.zip, row.county)
    if result:
        loc.lat, loc.lon, loc.geocode_source = result.lat, result.lon, result.source
        if result.county and not loc.county:
            loc.county = result.county
"""
from __future__ import annotations

import logging
from decimal import Decimal
from functools import cache
from typing import NamedTuple

from warn_v2.geo.bbox import in_state_bbox
from warn_v2.geo.city_centroids import lookup_decimal as _city_lookup
from warn_v2.geo.county_centroids import lookup_decimal as _county_lookup
from warn_v2.geo.zip_centroids import lookup_decimal

log = logging.getLogger(__name__)


class GeoResult(NamedTuple):
    """Return type of :func:`geocode`.

    ``source`` records which tier produced the coordinates:
    ``'census'`` | ``'zip'`` | ``'city'`` | ``'county'``.
    ``county`` is the containing county's full Census name (``"Sedgwick
    County"``, ``"Baltimore city"``, ``"Capitol Planning Region"``) — or the
    caller-supplied county verbatim — or ``None`` when it couldn't be
    resolved. Full names keep independent cities distinct from same-named
    counties and match the bundled CBP employment keys; the stats layer
    normalizes suffixed and bare spellings onto the same key.
    """

    lat: Decimal
    lon: Decimal
    source: str  # "census" | "zip" | "city" | "county"
    county: str | None = None


# The "geographies" endpoints return the containing county (and other layers)
# alongside the coordinates; the plain "locations" endpoints return coords only.
_CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/address"
_CENSUS_COORDS_URL = "https://geocoding.geo.census.gov/geocoder/geographies/coordinates"
_TIMEOUT = 8  # seconds

# USPS state/territory abbreviation → 2-digit state FIPS code, used to verify
# that a Census-returned county actually lies in the expected state (state
# bounding boxes are rectangles that overlap near borders; FIPS is exact —
# e.g. a "DC" address on the MD line can resolve to a Prince George's, MD hit).
STATE_FIPS: dict[str, str] = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08",
    "CT": "09", "DE": "10", "DC": "11", "FL": "12", "GA": "13", "HI": "15",
    "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
    "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33",
    "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46",
    "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
    "WV": "54", "WI": "55", "WY": "56",
    "AS": "60", "GU": "66", "MP": "69", "PR": "72", "VI": "78",
}


def _county_from_geographies(
    geographies: dict, state: str | None
) -> tuple[str, str] | None:
    """Extract ``(name, basename)`` for the county layer of a Census payload.

    ``name`` is the full Census NAME ("Sedgwick County", "Baltimore city",
    "Capitol Planning Region"); ``basename`` drops the type suffix. We store
    NAME: the bundled CBP employment keys derive from the same full names,
    and a bare BASENAME collides with same-named counties — "Baltimore city"'s
    basename is "Baltimore", which normalizes onto Baltimore *County*.

    Returns ``None`` when no county layer is present or when the county's
    state FIPS doesn't match *state* (wrong-state match near a border).
    """
    counties = geographies.get("Counties") or []
    if not counties:
        return None
    entry = counties[0]
    name = (entry.get("NAME") or entry.get("BASENAME") or "").strip()
    if not name:
        return None
    basename = (entry.get("BASENAME") or "").strip() or name
    if state and STATE_FIPS.get(state.strip().upper()) != entry.get("STATE"):
        log.debug(
            "Census county %r (state FIPS %s) doesn't match expected state %s — dropping",
            name, entry.get("STATE"), state,
        )
        return None
    return name, basename


def _census_geocode(
    street: str,
    city: str | None,
    state: str | None,
    zip_code: str | None,
) -> tuple[Decimal, Decimal, str | None] | None:
    """Call the Census geocoder for a street address.

    Returns ``(lat, lon, county)`` — Decimals plus the containing county's
    bare name (or ``None``) — or ``None`` on any failure.
    Import is deferred so this module can be imported in test environments
    without network access failing at import time.
    """
    import httpx  # local import keeps startup fast

    params: dict[str, str] = {
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Counties",
        "format": "json",
        "street": street.strip(),
    }
    if city:
        params["city"] = city.strip()
    if state:
        params["state"] = state.strip()
    if zip_code:
        params["zip"] = zip_code.strip()

    try:
        resp = httpx.get(_CENSUS_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        matches = resp.json().get("result", {}).get("addressMatches", [])
        if matches:
            coords = matches[0]["coordinates"]
            # Census returns lon as "x", lat as "y"
            lat = Decimal(str(round(float(coords["y"]), 6)))
            lon = Decimal(str(round(float(coords["x"]), 6)))
            pair = _county_from_geographies(matches[0].get("geographies") or {}, state)
            county = pair[0] if pair else None
            log.debug("Census geocoded %r → (%.4f, %.4f) county=%r", street, lat, lon, county)
            return lat, lon, county
        log.debug("Census geocoder: no match for %r %s %s %s", street, city, state, zip_code)
    except Exception as exc:
        log.debug("Census geocoder error for %r: %s", street, exc)
    return None


@cache
def _names_from_coords(
    lat: Decimal, lon: Decimal, state: str | None
) -> tuple[str, str] | None:
    """Reverse-look-up the county containing ``(lat, lon)`` via the Census API.

    Returns ``(name, basename)`` — e.g. ``("Sedgwick County", "Sedgwick")``,
    ``("Baltimore city", "Baltimore")`` — or ``None`` on any failure or a
    wrong-state match.  Results — including failures — are memoized for the
    process lifetime: ZIP/city-centroid coordinates repeat across many
    locations, so this collapses most lookups to one HTTP call, and an outage
    doesn't stall a long run with one timeout per row.
    """
    import httpx  # local import keeps startup fast

    params = {
        "benchmark": "Public_AR_Current",
        "vintage": "Current_Current",
        "layers": "Counties",
        "format": "json",
        "x": str(lon),
        "y": str(lat),
    }
    try:
        resp = httpx.get(_CENSUS_COORDS_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        geographies = resp.json().get("result", {}).get("geographies") or {}
        pair = _county_from_geographies(geographies, state)
        log.debug("Census county for (%.4f, %.4f): %r", lat, lon, pair)
        return pair
    except Exception as exc:
        log.debug("Census coordinates lookup error for (%s, %s): %s", lat, lon, exc)
    return None


def county_from_coords(
    lat: Decimal, lon: Decimal, state: str | None
) -> str | None:
    """The full Census county name containing ``(lat, lon)``, or ``None``."""
    pair = _names_from_coords(lat, lon, state)
    return pair[0] if pair else None


def geocode(
    address: str | None,
    city: str | None,
    state: str | None,
    zip_code: str | None,
    county: str | None = None,
) -> GeoResult | None:
    """Best-effort geocode → :class:`GeoResult` ``(lat, lon, source, county)``, or ``None``.

    Priority:
      1. Census street-level geocoding (when *address* is given) → source ``'census'``
      2. ZIP centroid (fast local lookup, ~city-block radius)     → source ``'zip'``
      3. City centroid (fast local lookup, ~city-level / ~11 km)  → source ``'city'``
      4. County centroid (fast local lookup, ~county-level / ~30 km) → source ``'county'``

    A tier's result is rejected when it falls outside *state*'s bounding box
    (sources sometimes carry the corporate-HQ address/ZIP instead of the
    worksite — e.g. GA), letting the next tier try with worksite-local data.

    ``result.county`` is the caller-supplied *county* when given (the WARN
    source knows best); otherwise the census tier carries the county from its
    own response and the ZIP/city tiers reverse-look-up the resolved
    coordinates via :func:`county_from_coords` (one extra memoized HTTP call).
    """
    def _validated(pair, source: str, county_hint: str | None) -> GeoResult | None:
        if pair is None:
            return None
        if not in_state_bbox(state, float(pair[0]), float(pair[1])):
            log.debug(
                "geocode: %s result (%.4f, %.4f) outside %s bbox — trying next tier",
                source, pair[0], pair[1], state,
            )
            return None
        return GeoResult(pair[0], pair[1], source, county_hint)

    def _fill_county(result: GeoResult) -> GeoResult:
        if result.county is not None:
            return result
        found = county_from_coords(result.lat, result.lon, state)
        return result._replace(county=found) if found else result

    # 1. Full street address via Census geocoder
    if address:
        hit = _census_geocode(address, city, state, zip_code)
        if hit is not None:
            result = _validated(hit[:2], "census", county or hit[2])
            if result is not None:
                return _fill_county(result)

    # 2. ZIP centroid fallback
    result = _validated(lookup_decimal(zip_code), "zip", county)
    if result is not None:
        return _fill_county(result)

    # 3. City centroid fallback (handles states that report city but not ZIP)
    result = _validated(_city_lookup(state, city), "city", county)
    if result is not None:
        return _fill_county(result)

    # 4. County centroid fallback (handles states that report only county, e.g. KY, MT)
    return _validated(_county_lookup(state, county), "county", county)
