"""(state, city) → (lat, lon) centroid lookup.

Backed by a bundled gzipped JSON file derived from the US Census Gazetteer
of Incorporated Places and Census-Designated Places (~29 k entries). The
file is loaded lazily on first lookup and cached for the lifetime of the
process.

Data file path: ``warn_v2/geo/_data/places.json.gz`` — a single JSON object
mapping ``"{STATE}|{city_normalized}"`` strings to ``[lat, lon]`` pairs, where
``city_normalized = city.lower().strip()``.

If the data file is missing (e.g. in a fresh checkout before the fetch
script has been run), every lookup returns ``None`` — callers must handle
that case rather than relying on the file being present.

Build the data file with::

    python -m warn_v2.scripts.fetch_city_centroids
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
from decimal import Decimal
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent / "_data" / "places.json.gz"

_lock = threading.Lock()
_cache: dict[str, tuple[float, float]] | None = None


def _normalize(state: str | None, city: str | None) -> str | None:
    """Return the canonical lookup key ``"{STATE}|{city_lower}"`` or ``None``."""
    if not state or not city:
        return None
    s = state.strip().upper()
    c = city.strip().lower()
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
                "City centroid data file not found at %s; lookups will return None.",
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
        log.info("Loaded %d city centroids from %s", len(loaded), _DATA_PATH)
        return _cache


def lookup(state: str | None, city: str | None) -> tuple[float, float] | None:
    """Return ``(lat, lon)`` for a US city, or ``None`` if unknown.

    Matching is case-insensitive and strips leading/trailing whitespace.
    """
    key = _normalize(state, city)
    if key is None:
        return None
    return _load().get(key)


def lookup_decimal(state: str | None, city: str | None) -> tuple[Decimal, Decimal] | None:
    """Same as ``lookup`` but returns Decimal values suitable for SQLAlchemy."""
    pair = lookup(state, city)
    if pair is None:
        return None
    return Decimal(str(pair[0])), Decimal(str(pair[1]))


def reload_for_testing(data: dict[str, tuple[float, float]]) -> None:
    """Replace the in-memory cache (tests only). Pass an empty dict to clear."""
    global _cache
    with _lock:
        _cache = dict(data)
