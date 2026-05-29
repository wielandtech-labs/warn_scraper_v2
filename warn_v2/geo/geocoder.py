"""Geocoding: US Census address API → ZIP centroid → city centroid fallback.

Strategy (in priority order):
  1. US Census Geocoder — free, no API key, US-only, street-level precision.
     Requires a street address.  Called only when ``address`` is provided.
  2. ZIP centroid — local dictionary lookup, instant, ~city-block radius.
     Used when no address is available or Census call fails/returns nothing.
  3. City centroid — (state, city) lookup from the Census Places Gazetteer,
     ~city-level accuracy (~11 km).  Used when no ZIP is available and the
     first two tiers both return None.  Covers states whose WARN sources
     report city name but not ZIP code (e.g. AK, AL, MA, MN, TX, WA, …).

The Census geocoder is called synchronously with a short timeout.  Any
exception (network error, rate-limit, bad JSON) falls through to ZIP centroid
so callers always get a best-effort result without raising.

Typical usage in storage.py::

    from warn_v2.geo.geocoder import geocode as _geocode
    pair = _geocode(row.address, row.city, row.state, row.zip)
    if pair:
        loc.lat, loc.lon = pair
"""
from __future__ import annotations

import logging
from decimal import Decimal

from warn_v2.geo.city_centroids import lookup_decimal as _city_lookup
from warn_v2.geo.zip_centroids import lookup_decimal

log = logging.getLogger(__name__)

_CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/address"
_TIMEOUT = 8  # seconds


def _census_geocode(
    street: str,
    city: str | None,
    state: str | None,
    zip_code: str | None,
) -> tuple[Decimal, Decimal] | None:
    """Call the Census geocoder for a street address.

    Returns ``(lat, lon)`` as Decimals, or ``None`` on any failure.
    Import is deferred so this module can be imported in test environments
    without network access failing at import time.
    """
    import httpx  # local import keeps startup fast

    params: dict[str, str] = {
        "benchmark": "Public_AR_Current",
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
            log.debug("Census geocoded %r → (%.4f, %.4f)", street, lat, lon)
            return lat, lon
        log.debug("Census geocoder: no match for %r %s %s %s", street, city, state, zip_code)
    except Exception as exc:
        log.debug("Census geocoder error for %r: %s", street, exc)
    return None


def geocode(
    address: str | None,
    city: str | None,
    state: str | None,
    zip_code: str | None,
) -> tuple[Decimal, Decimal] | None:
    """Best-effort geocode returning ``(lat, lon)`` as Decimal pair, or ``None``.

    Priority:
      1. Census street-level geocoding (when *address* is given)
      2. ZIP centroid (fast local lookup, ~city-block radius)
      3. City centroid (fast local lookup, ~city-level / ~11 km)
    """
    # 1. Full street address via Census geocoder
    if address:
        result = _census_geocode(address, city, state, zip_code)
        if result is not None:
            return result

    # 2. ZIP centroid fallback
    result = lookup_decimal(zip_code)
    if result is not None:
        return result

    # 3. City centroid fallback (handles states that report city but not ZIP)
    return _city_lookup(state, city)
