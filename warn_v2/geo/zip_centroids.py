"""ZIP → (lat, lon) centroid lookup.

Backed by a bundled gzipped JSON file derived from the US Census ZCTA
gazetteer (~42 k entries). The file is loaded lazily on first lookup and
cached for the lifetime of the process.

Data file path: ``warn_v2/geo/_data/zcta.json.gz`` — a single JSON object
mapping 5-digit ZIP strings to ``[lat, lon]`` pairs.

If the data file is missing (e.g. in a fresh checkout before the fetch
script has been run), every lookup returns ``None`` — callers must handle
that case rather than relying on the file being present.

Build the data file with::

    python -m warn_v2.scripts.fetch_zip_centroids
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
from decimal import Decimal
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent / "_data" / "zcta.json.gz"

_lock = threading.Lock()
_cache: dict[str, tuple[float, float]] | None = None


def _normalize(zip_value: str | None) -> str | None:
    """Trim, zero-pad, and validate a ZIP-shaped string. Returns 5 digits or None."""
    if not zip_value:
        return None
    z = zip_value.strip().split("-", 1)[0]  # drop ZIP+4 if present
    if not z.isdigit():
        return None
    if len(z) < 5:
        z = z.zfill(5)
    elif len(z) > 5:
        return None
    return z


def _load() -> dict[str, tuple[float, float]]:
    """Load the centroid table into memory once."""
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        if not _DATA_PATH.exists():
            log.warning("ZIP centroid data file not found at %s; lookups will return None.",
                        _DATA_PATH)
            _cache = {}
            return _cache
        with gzip.open(_DATA_PATH, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        # Validate shape and coerce numbers to float
        loaded: dict[str, tuple[float, float]] = {}
        for k, v in raw.items():
            try:
                loaded[str(k)] = (float(v[0]), float(v[1]))
            except (TypeError, ValueError, IndexError):
                continue
        _cache = loaded
        log.info("Loaded %d ZIP centroids from %s", len(loaded), _DATA_PATH)
        return _cache


def lookup(zip_value: str | None) -> tuple[float, float] | None:
    """Return (lat, lon) for a US ZIP code, or None if unknown / malformed."""
    z = _normalize(zip_value)
    if z is None:
        return None
    return _load().get(z)


def lookup_decimal(zip_value: str | None) -> tuple[Decimal, Decimal] | None:
    """Same as ``lookup`` but returns Decimal values suitable for SQLAlchemy."""
    pair = lookup(zip_value)
    if pair is None:
        return None
    return Decimal(str(pair[0])), Decimal(str(pair[1]))


def reload_for_testing(data: dict[str, tuple[float, float]]) -> None:
    """Replace the in-memory cache (tests only). Pass an empty dict to clear."""
    global _cache
    with _lock:
        _cache = dict(data)
