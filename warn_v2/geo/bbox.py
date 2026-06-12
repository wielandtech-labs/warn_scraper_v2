"""Approximate per-state bounding boxes for sanity-checking geocode results.

Boxes are (lat_min, lat_max, lon_min, lon_max) with ~1 degree padding — meant
to catch *gross* errors (a GA notice pinned in California, lat/lon 0), so
generous bounds are intentional. Shared by the audit (flagging) and the
geocoder (rejecting an out-of-state result so a lower tier can try instead).
"""
from __future__ import annotations

STATE_BBOX: dict[str, tuple[float, float, float, float]] = {
    "AL": (29.0, 36.0, -89.5, -84.0), "AK": (50.0, 72.5, -180.0, -129.0),
    "AZ": (30.5, 38.0, -116.0, -108.0), "AR": (32.0, 37.5, -95.5, -88.5),
    "CA": (31.5, 42.5, -125.5, -113.5), "CO": (36.0, 42.0, -110.0, -101.0),
    "CT": (40.0, 42.5, -74.5, -71.0), "DE": (37.5, 40.5, -76.5, -74.0),
    "DC": (38.3, 39.5, -77.5, -76.5), "FL": (24.0, 31.5, -88.0, -79.5),
    "GA": (29.5, 35.5, -86.0, -80.0), "HI": (18.0, 23.5, -161.0, -154.0),
    "ID": (41.0, 49.5, -118.0, -110.5), "IL": (36.0, 43.5, -92.0, -86.5),
    "IN": (37.0, 42.5, -89.0, -84.0), "IA": (39.5, 44.5, -97.0, -89.5),
    "KS": (36.0, 41.0, -103.0, -94.0), "KY": (35.5, 40.0, -90.0, -81.0),
    "LA": (28.0, 34.0, -95.0, -88.0), "ME": (42.5, 48.5, -72.0, -66.0),
    "MD": (37.0, 40.5, -80.0, -74.5), "MA": (41.0, 43.5, -74.0, -69.5),
    "MI": (41.0, 48.5, -91.0, -82.0), "MN": (43.0, 49.5, -98.0, -89.0),
    "MS": (29.5, 35.5, -92.5, -87.5), "MO": (35.5, 41.0, -96.5, -88.5),
    "MT": (44.0, 49.5, -116.5, -103.5), "NE": (39.5, 43.5, -104.5, -95.0),
    "NV": (34.5, 42.5, -120.5, -113.5), "NH": (42.0, 45.8, -73.0, -70.0),
    "NJ": (38.5, 41.8, -76.0, -73.5), "NM": (30.5, 37.5, -109.5, -102.5),
    "NY": (40.0, 45.5, -80.5, -71.0), "NC": (33.0, 37.5, -85.0, -75.0),
    "ND": (45.0, 49.5, -104.5, -96.0), "OH": (37.5, 42.5, -85.5, -80.0),
    "OK": (33.0, 37.5, -103.5, -94.0), "OR": (41.0, 47.0, -125.0, -116.0),
    "PA": (39.0, 42.8, -81.0, -74.0), "RI": (40.8, 42.5, -72.5, -70.5),
    "SC": (31.5, 35.7, -84.0, -78.0), "SD": (42.0, 46.5, -104.5, -95.5),
    "TN": (34.0, 37.5, -91.0, -81.0), "TX": (25.0, 37.0, -107.0, -93.0),
    "UT": (36.0, 42.5, -114.5, -108.5), "VT": (42.0, 45.5, -74.0, -71.0),
    "VA": (35.5, 40.0, -84.0, -75.0), "WA": (45.0, 49.5, -125.0, -116.5),
    "WV": (37.0, 41.0, -83.0, -77.0), "WI": (41.5, 47.5, -93.5, -86.5),
    "WY": (40.5, 45.5, -111.5, -103.5),
}


def in_state_bbox(state: str | None, lat: float, lon: float) -> bool:
    """True when (lat, lon) falls inside ``state``'s box.

    Unknown or missing states return True (no basis to reject). Alaska's
    Aleutian islands cross the antimeridian — positive longitudes >= 170
    are accepted for AK.
    """
    if not state:
        return True
    state = state.upper()
    box = STATE_BBOX.get(state)
    if box is None:
        return True
    lat_min, lat_max, lon_min, lon_max = box
    if state == "AK" and lat_min <= lat <= lat_max and lon >= 170.0:
        return True
    return lat_min <= lat <= lat_max and lon_min <= lon <= lon_max