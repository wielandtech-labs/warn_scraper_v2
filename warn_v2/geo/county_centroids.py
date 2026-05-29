"""(state, county) → (lat, lon) centroid lookup.

Backed by a bundled gzipped JSON file derived from the US Census Gazetteer
of Counties (~3.2 k entries).  The file is loaded lazily on first lookup and
cached for the lifetime of the process.

Data file path: ``warn_v2/geo/_data/counties.json.gz`` — a single JSON object
mapping ``"{STATE}|{county_normalized}"`` strings to ``[lat, lon]`` pairs,
where ``county_normalized = county.lower().strip()`` with legal-type suffixes
(" county", " parish", " borough", etc.) removed.

For example, ``"KY|madison"`` covers "Madison", "Madison County", etc.

If the data file is missing (e.g. in a fresh checkout before the fetch
script has been run), every lookup returns ``None`` — callers must handle
that case rather than relying on the file being present.

Build the data file with::

    python -m warn_v2.scripts.fetch_county_centroids
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
from decimal import Decimal
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent / "_data" / "counties.json.gz"

_lock = threading.Lock()
_cache: dict[str, tuple[float, float]] | None = None

# Legal-type suffixes that appear in scraper county names and must be
# stripped before lookup (same list as in fetch_county_centroids.py).
_COUNTY_SUFFIXES: tuple[str, ...] = (
    " city and borough",
    " census area",
    " municipality",
    " city and county",
    " parish",
    " borough",
    " county",
)


def _normalize(state: str | None, county: str | None) -> str | None:
    """Return the canonical lookup key ``"{STATE}|{county_lower}"`` or ``None``.

    Strips legal-type suffixes so "Madison County" and "Madison" both map
    to ``"KY|madison"``.
    """
    if not state or not county:
        return None
    s = state.strip().upper()
    c = county.strip().lower()
    for suffix in _COUNTY_SUFFIXES:
        if c.endswith(suffix):
            c = c[: -len(suffix)].strip()
            break
    if not s or not c:
        return None
    return f"{s}|{c}"


def _load() -> dict[str, tuple[float, float]]:
    """Load the centroid table into memory once."""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        if not _DATA_PATH.exists():
            log.warning(
                "County centroid data file not found at %s; lookups will return None. "
                "Run: python -m warn_v2.scripts.fetch_county_centroids",
                _DATA_PATH,
            )
            _cache = {}
            return _cache
        with gzip.open(_DATA_PATH, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        loaded: dict[str, tuple[float, float]] = {}
        for k, v in raw.items():
            try:
                loaded[str(k)] = (float(v[0]), float(v[1]))
            except (TypeError, ValueError, IndexError):
                continue
        _cache = loaded
        log.info("Loaded %d county centroids from %s", len(loaded), _DATA_PATH)
        return _cache


def lookup(state: str | None, county: str | None) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` for a US county, or ``None`` if unknown.

    Matching is case-insensitive, strips whitespace, and strips legal-type
    suffixes (so both "Madison" and "Madison County" match).
    """
    key = _normalize(state, county)
    if key is None:
        return None
    return _load().get(key)


def lookup_decimal(state: str | None, county: str | None) -> tuple[Decimal, Decimal] | None:
    """Same as ``lookup`` but returns Decimal values suitable for SQLAlchemy."""
    pair = lookup(state, county)
    if pair is None:
        return None
    return Decimal(str(pair[0])), Decimal(str(pair[1]))


def reload_for_testing(data: dict[str, tuple[float, float]]) -> None:
    """Replace the in-memory cache (tests only). Pass an empty dict to clear."""
    global _cache
    with _lock:
        _cache = dict(data)
