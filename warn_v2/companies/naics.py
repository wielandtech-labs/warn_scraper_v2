"""NAICS sector grouping for industry filtering.

Enrichment stores a full NAICS code (e.g. "311999") on Company, but the
description (`naics_desc`) is often missing from the provider. Filtering and
the UI therefore work off the 2-digit **sector**, which is always derivable
from the code and gives a bounded, stable set of ~20 buckets.
"""
from __future__ import annotations

from sqlalchemy import func

from warn_v2.companies.naics_subsectors import NAICS_SUBSECTORS

# (sector_id, display name, 2-digit code prefixes) — 2022 NAICS sectors. The
# range-form ids (31-33, 44-45, 48-49) each cover several 2-digit prefixes.
NAICS_SECTORS: list[tuple[str, str, tuple[str, ...]]] = [
    ("11", "Agriculture, Forestry, Fishing & Hunting", ("11",)),
    ("21", "Mining, Quarrying, Oil & Gas Extraction", ("21",)),
    ("22", "Utilities", ("22",)),
    ("23", "Construction", ("23",)),
    ("31-33", "Manufacturing", ("31", "32", "33")),
    ("42", "Wholesale Trade", ("42",)),
    ("44-45", "Retail Trade", ("44", "45")),
    ("48-49", "Transportation & Warehousing", ("48", "49")),
    ("51", "Information", ("51",)),
    ("52", "Finance & Insurance", ("52",)),
    ("53", "Real Estate, Rental & Leasing", ("53",)),
    ("54", "Professional, Scientific & Technical Services", ("54",)),
    ("55", "Management of Companies & Enterprises", ("55",)),
    ("56", "Administrative, Support & Waste Management", ("56",)),
    ("61", "Educational Services", ("61",)),
    ("62", "Health Care & Social Assistance", ("62",)),
    ("71", "Arts, Entertainment & Recreation", ("71",)),
    ("72", "Accommodation & Food Services", ("72",)),
    ("81", "Other Services (except Public Administration)", ("81",)),
    ("92", "Public Administration", ("92",)),
]

_PREFIX_TO_SECTOR: dict[str, str] = {
    p: sid for sid, _name, prefixes in NAICS_SECTORS for p in prefixes
}
_SECTOR_PREFIXES: dict[str, list[str]] = {
    sid: list(prefixes) for sid, _name, prefixes in NAICS_SECTORS
}
SECTOR_NAME: dict[str, str] = {sid: name for sid, name, _ in NAICS_SECTORS}


def sector_for_code(naics_code: str | None) -> str | None:
    """Return the sector id for a NAICS code (by 2-digit prefix), or None."""
    if not naics_code or len(naics_code) < 2:
        return None
    return _PREFIX_TO_SECTOR.get(naics_code[:2])


def sector_prefixes(sector_id: str | None) -> list[str] | None:
    """Return the 2-digit prefixes for a sector id, or None if unknown."""
    if not sector_id:
        return None
    return _SECTOR_PREFIXES.get(sector_id)


def subsector_for_code(naics_code: str | None) -> str | None:
    """Return the 3-digit subsector for a NAICS code, or None.

    Only returns a value when the code is >=3 digits and its 2-digit prefix maps
    to a known sector (so junk codes don't produce phantom subsectors).
    """
    if not naics_code or len(naics_code) < 3:
        return None
    if naics_code[:2] not in _PREFIX_TO_SECTOR:
        return None
    return naics_code[:3]


def subsector_name(code: str | None) -> str | None:
    """Return the title for a 3-digit NAICS subsector code, or None."""
    if not code:
        return None
    return NAICS_SUBSECTORS.get(code)


def naics_filter(column, industry: str | None, subsector: str | None):
    """Build a SQLAlchemy WHERE clause on a NAICS-code column, or None.

    `column` is the code column to filter (e.g. ``Company.naics_code``). A valid
    3-digit ``subsector`` is more specific and wins over the 2-digit ``industry``
    sector; an unknown/empty pair yields None (caller applies no industry filter).
    Shared by every endpoint that filters by industry so the precedence rules
    stay in one place.
    """
    if subsector and subsector_name(subsector):
        return func.substr(column, 1, 3) == subsector
    prefixes = sector_prefixes(industry)
    if prefixes:
        return func.substr(column, 1, 2).in_(prefixes)
    return None
