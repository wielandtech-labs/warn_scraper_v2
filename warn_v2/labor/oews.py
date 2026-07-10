"""NAICS code → occupation staffing pattern lookup (BLS OEWS).

Backed by a bundled gzipped JSON file derived from the BLS Occupational
Employment and Wage Statistics national industry-specific estimates: for
each industry (NAICS sector / 3-digit / 4-digit), the top detailed SOC
occupations and each one's percent of the industry's employment. Applied to
a notice's ``layoff_count`` this yields an *estimated* occupation mix for
the affected cohort — a statistical prior from the national industry
staffing pattern, not data about the actual affected roles.

Data file path: ``warn_v2/labor/_data/oews_staffing.json.gz`` — a JSON
object::

    {"vintage": "May 2025",
     "occupations": {"51-4041": "Machinists", ...},
     "levels": {
       "sector": {"31-33": {"title": ..., "coverage": 61.3,
                            "occs": [["53-7062", 6.1], ...]}},
       "naics3": {"311": {...}},
       "naics4": {"3119": {...}}}}

``lookup()`` walks from the most specific level the company's 6-digit code
supports down to its sector, so any valid NAICS code resolves to *some*
pattern. If the data file is missing (fresh checkout before the fetch
script has run), every lookup returns ``None`` — callers must handle that.

Build the data file with::

    python -m warn_v2.scripts.fetch_oews_staffing
"""
from __future__ import annotations

import gzip
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from warn_v2.companies.naics import sector_for_code

log = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent / "_data" / "oews_staffing.json.gz"

_lock = threading.Lock()
_cache: dict[str, dict[str, dict]] | None = None  # level → naics key → entry
_occupations: dict[str, str] = {}
_vintage: str | None = None


@dataclass(frozen=True)
class StaffingPattern:
    """The occupation mix OEWS reports for one industry."""

    naics_key: str  # matched key, e.g. "3119" or "31-33"
    level: str  # "4-digit" | "3-digit" | "sector"
    industry_title: str
    coverage_pct: float  # share of industry employment the occupations cover
    occupations: list[tuple[str, str, float]]  # (soc_code, title, pct) desc


def _load() -> dict[str, dict[str, dict]]:
    """Load the staffing-pattern table into memory once."""
    global _cache, _occupations, _vintage
    with _lock:
        if _cache is not None:
            return _cache
        if not _DATA_PATH.exists():
            log.warning(
                "OEWS staffing data file not found at %s; lookups will return None. "
                "Run: python -m warn_v2.scripts.fetch_oews_staffing",
                _DATA_PATH,
            )
            _cache = {}
            return _cache
        with gzip.open(_DATA_PATH, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        _occupations = {str(k): str(v) for k, v in raw.get("occupations", {}).items()}
        levels = raw.get("levels", {})
        _cache = {
            level: dict(levels.get(level, {})) for level in ("sector", "naics3", "naics4")
        }
        _vintage = str(raw["vintage"]) if raw.get("vintage") else None
        log.info(
            "Loaded OEWS staffing patterns (%s) from %s: %d sectors, %d 3-digit, %d 4-digit",
            _vintage,
            _DATA_PATH,
            len(_cache["sector"]),
            len(_cache["naics3"]),
            len(_cache["naics4"]),
        )
        return _cache


def _pattern_from_entry(key: str, level: str, entry: dict) -> StaffingPattern | None:
    occs: list[tuple[str, str, float]] = []
    for item in entry.get("occs", []):
        try:
            soc, pct = str(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        occs.append((soc, _occupations.get(soc, soc), pct))
    if not occs:
        return None
    try:
        coverage = float(entry.get("coverage") or 0.0)
    except (TypeError, ValueError):
        coverage = 0.0
    return StaffingPattern(
        naics_key=key,
        level=level,
        industry_title=str(entry.get("title") or ""),
        coverage_pct=coverage,
        occupations=occs,
    )


def lookup(naics_code: str | None) -> StaffingPattern | None:
    """Return the best staffing pattern for a NAICS code, or ``None``.

    Walks most-specific-first: the code's 4-digit industry group, then its
    3-digit subsector, then its sector ("31-33"-style range id). A company's
    stored code is usually 6 digits but shorter codes work at whatever
    levels they support.
    """
    if not naics_code:
        return None
    code = naics_code.strip()
    if not code.isdigit():
        return None
    # 99* is never a real industry on a company: OEWS 999xxx is government,
    # and providers use 999990 for "unclassified establishments" — walking
    # either into a staffing pattern produces nonsense (police officers on a
    # textile closure). Belt-and-braces with the fetch script's own skip.
    if code.startswith("99"):
        return None
    data = _load()
    if not data:
        return None
    for prefix_len, level_key, level_name in ((4, "naics4", "4-digit"), (3, "naics3", "3-digit")):
        if len(code) < prefix_len:
            continue
        entry = data.get(level_key, {}).get(code[:prefix_len])
        if entry:
            pattern = _pattern_from_entry(code[:prefix_len], level_name, entry)
            if pattern:
                return pattern
    sector = sector_for_code(code)
    if sector:
        entry = data.get("sector", {}).get(sector)
        if entry:
            return _pattern_from_entry(sector, "sector", entry)
    return None


def data_vintage() -> str | None:
    """The OEWS vintage of the bundled data (e.g. "May 2025"), or ``None``."""
    _load()
    return _vintage


def reload_for_testing(data: dict | None, vintage: str | None = None) -> None:
    """Replace the in-memory cache (tests only).

    ``data`` uses the on-disk shape: ``{"occupations": {...}, "levels":
    {"sector": {...}, "naics3": {...}, "naics4": {...}}}``. An empty dict
    means "no patterns" (lookups return None); ``None`` resets the cache so
    the next lookup loads the real bundled file again — use that in fixture
    teardowns, or the empty seed leaks into every later test in the session.
    """
    global _cache, _occupations, _vintage
    with _lock:
        if data is None:
            _cache = None
            _occupations = {}
            _vintage = None
            return
        _occupations = dict(data.get("occupations", {}))
        levels = data.get("levels", {})
        _cache = {
            level: dict(levels.get(level, {})) for level in ("sector", "naics3", "naics4")
        }
        _vintage = vintage
