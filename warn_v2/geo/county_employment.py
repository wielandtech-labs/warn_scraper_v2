"""(state, county) → county employment base lookup (Census CBP).

Backed by a bundled gzipped JSON file derived from Census County Business
Patterns (county-total employment, all industries, ~3.2 k entries). The file
is loaded lazily on first lookup and cached for the lifetime of the process.

Data file path: ``warn_v2/geo/_data/county_employment.json.gz`` — a JSON
object ``{"year": <CBP year>, "counties": {...}}`` where ``counties`` maps
``"{STATE}|{county_normalized}"`` strings to employment integers, with
``county_normalized = county.lower().strip()`` minus legal-type suffixes
(" county", " parish", " borough", etc.) — the same key scheme as
``county_centroids.py``.

If the data file is missing (e.g. in a fresh checkout before the fetch
script has been run), every lookup returns ``None`` — callers must handle
that case rather than relying on the file being present.

Build the data file with::

    python -m warn_v2.scripts.fetch_county_employment
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent / "_data" / "county_employment.json.gz"

_lock = threading.Lock()
_cache: dict[str, int] | None = None
_year: int | None = None

# Legal-type suffixes that appear in scraper county names and must be
# stripped before lookup (same list as in county_centroids.py).
_COUNTY_SUFFIXES: tuple[str, ...] = (
    " city and borough",
    " census area",
    " municipality",
    " city and county",
    " parish",
    " borough",
    " county",
)


def normalize_key(state: str | None, county: str | None) -> str | None:
    """Return the canonical lookup key ``"{STATE}|{county_lower}"`` or ``None``.

    Strips legal-type suffixes so "Madison County" and "Madison" both map
    to ``"KY|madison"``. Public because the stats route uses it to merge
    differently-spelled county rows before ranking.
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


def display_name(county: str) -> str:
    """County name with any legal-type suffix removed, original case kept.

    "Madison County" → "Madison", "McLean" → "McLean" (title-casing the
    normalized key would mangle names like McLean/DeKalb, so strip from the
    raw string instead).
    """
    c = county.strip()
    low = c.lower()
    for suffix in _COUNTY_SUFFIXES:
        if low.endswith(suffix):
            return c[: -len(suffix)].strip()
    return c


def _load() -> dict[str, int]:
    """Load the employment table into memory once."""
    global _cache, _year
    with _lock:
        if _cache is not None:
            return _cache
        if not _DATA_PATH.exists():
            log.warning(
                "County employment data file not found at %s; lookups will return None. "
                "Run: python -m warn_v2.scripts.fetch_county_employment",
                _DATA_PATH,
            )
            _cache = {}
            return _cache
        with gzip.open(_DATA_PATH, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        loaded: dict[str, int] = {}
        for k, v in raw.get("counties", {}).items():
            try:
                emp = int(v)
            except (TypeError, ValueError):
                continue
            if emp > 0:
                loaded[str(k)] = emp
        try:
            _year = int(raw.get("year"))
        except (TypeError, ValueError):
            _year = None
        _cache = loaded
        log.info(
            "Loaded %d county employment bases (CBP %s) from %s",
            len(loaded),
            _year,
            _DATA_PATH,
        )
        return _cache


def lookup(state: str | None, county: str | None) -> int | None:
    """Return the CBP employment base for a US county, or ``None`` if unknown.

    Matching is case-insensitive, strips whitespace, and strips legal-type
    suffixes (so both "Madison" and "Madison County" match).
    """
    key = normalize_key(state, county)
    if key is None:
        return None
    return _load().get(key)


def lookup_key(key: str) -> int | None:
    """Return the employment base for an already-normalized key."""
    return _load().get(key)


def data_year() -> int | None:
    """The CBP vintage of the bundled data, or ``None`` if unavailable."""
    _load()
    return _year


def reload_for_testing(data: dict[str, int], year: int | None = None) -> None:
    """Replace the in-memory cache (tests only). Pass an empty dict to clear."""
    global _cache, _year
    with _lock:
        _cache = dict(data)
        _year = year
