"""(state, county) → county employment base lookup.

Backed by a bundled gzipped JSON file of county-total employment, all
industries, ~3.2 k entries. The file is loaded lazily on first lookup and
cached for the lifetime of the process. Its source is whichever
``fetch_county_employment.py`` last built it — BLS QCEW by default, Census CBP
optionally — so callers surface ``data_source()`` rather than naming one.

Data file path: ``warn_v2/geo/_data/county_employment.json.gz`` — a JSON
object ``{"year": <year>, "source": "QCEW"|"CBP", "counties": {...}}`` where
``counties`` maps
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
import re
import threading
from pathlib import Path

log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent / "_data" / "county_employment.json.gz"

_lock = threading.Lock()
_cache: dict[str, int] | None = None
_year: int | None = None
_source: str | None = None

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


# Misspellings / abbreviations seen in scraped county columns, keyed by state
# then by the lowercased base name (suffix already stripped). Values are the
# Census spelling, case preserved, so they double as display names.
_COUNTY_ALIASES: dict[str, dict[str, str]] = {
    "IA": {"harrision": "Harrison"},
    "MD": {"balto": "Baltimore", "balto city": "Baltimore City"},
    "MS": {"lefore": "Leflore"},
    "PA": {"schuykill": "Schuylkill"},
}

# Parenthetical qualifiers that name the legal type ("St. Louis (county)")
# become a plain suffix; any other parenthetical ("(and other counties)") is
# dropped.
_PAREN_RE = re.compile(r"\s*\(([^)]*)\)")
_PAREN_TYPES = frozenset({"county", "city", "parish", "borough"})
# "Jefferson County - Louisville": the trailing qualifier names the seat/city.
_DASH_QUALIFIER_RE = re.compile(r"\s+-\s+.*$")
# "Balto Co." / "Montgomery Co"
_CO_ABBREV_RE = re.compile(r"\s+co\.?$", re.IGNORECASE)


def canonical_name(state: str | None, county: str | None) -> str | None:
    """Clean a raw county label to its suffix-less display name, or ``None``.

    Scraped counties and the Census NAMEs written by the county backfill share
    ``locations.county``, so one county arrives as "Fairfax" / "Fairfax
    County", "Balto Co." / "Baltimore County", "Cook  (and other counties)".
    This collapses those to one spelling ("Fairfax", "Baltimore", "Cook")
    while keeping genuinely different places apart: "Baltimore City" and
    "Fairfax city" (independent cities) and CT planning regions keep their
    full names because " city" / " planning region" are not stripped.
    Original casing is kept (McLean, DeKalb).
    """
    if not state or not county:
        return None
    c = " ".join(county.split())

    def _paren(m: re.Match) -> str:
        inner = m.group(1).strip().lower()
        return f" {inner}" if inner in _PAREN_TYPES else ""

    c = _PAREN_RE.sub(_paren, c)
    c = _DASH_QUALIFIER_RE.sub("", c)
    c = _CO_ABBREV_RE.sub(" County", c).strip()
    low = c.lower()
    for suffix in _COUNTY_SUFFIXES:
        if low.endswith(suffix):
            c = c[: -len(suffix)].strip()
            break
    if not c:
        return None
    return _COUNTY_ALIASES.get(state.strip().upper(), {}).get(c.lower(), c)


def normalize_key(state: str | None, county: str | None) -> str | None:
    """Return the canonical lookup key ``"{STATE}|{county_lower}"`` or ``None``.

    Built on :func:`canonical_name`, so "Madison County", "Madison" and
    "Madison Co." all map to ``"KY|madison"``. Public because the stats route
    and the report aggregation use it to merge differently-spelled county rows
    before ranking.
    """
    if not state or not state.strip():
        return None
    name = canonical_name(state, county)
    if name is None:
        return None
    return f"{state.strip().upper()}|{name.lower()}"


def _load() -> dict[str, int]:
    """Load the employment table into memory once."""
    global _cache, _year, _source
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
        # Files built before the source was recorded are all CBP.
        _source = str(raw.get("source") or "CBP")
        _cache = loaded
        log.info(
            "Loaded %d county employment bases (%s %s) from %s",
            len(loaded),
            _source,
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
    """The reference year of the bundled data, or ``None`` if unavailable."""
    _load()
    return _year


def data_source() -> str | None:
    """Which survey the bundled data came from ("QCEW" or "CBP")."""
    _load()
    return _source


def reload_for_testing(
    data: dict[str, int], year: int | None = None, source: str | None = "QCEW"
) -> None:
    """Replace the in-memory cache (tests only). Pass an empty dict to clear."""
    global _cache, _year, _source
    with _lock:
        _cache = dict(data)
        _year = year
        _source = source
