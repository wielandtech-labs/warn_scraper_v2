"""Recover the worksite city from Minnesota's wide-format WARN rows.

MN's 2025 monthly report PDFs use a merged-cell table that pdfplumber can't
split into columns, so the text-line fallback (`mn._parse_text_lines`) captures
the whole ``Layoff Name | Account: City | Account: Industry`` run as one string,
e.g. ``"Upsher-Smith 2025 Maple Grove Manufacturing"``. The 2026 clean-table
format has a proper City column and is unaffected.

This recovers the city deterministically: strip the trailing industry supersector
label (a controlled DEED vocabulary), then take the longest trailing 1-3 words
that match a known MN city in the bundled gazetteer. Matching from the *end*
anchors on the City column and naturally rejects out-of-state HQ cities the source
sometimes lists (Bentonville, San Francisco, Omaha) — those simply return None and
stay un-geocoded, which is correct.
"""
from __future__ import annotations

import re

from warn_v2.geo import city_centroids

# DEED industry supersector labels, appended as the final column. Longest first so
# multi-word labels match before their prefixes ("Admin & Support Services" before
# "Admin & Support"). Kept permissive — an unknown label just means no city is
# recovered (the row stays un-geocoded, as today).
_INDUSTRIES: tuple[str, ...] = tuple(
    sorted(
        {
            "Health Care/Social Assist",
            "Health/Social Assist",
            "Arts/Entertainment/Rec",
            "Arts/Entertainment",
            "Admin & Support Services",
            "Admin & Support",
            "Finance & Insurance",
            "Professional Services",
            "Other Services",
            "Mining/Oil /Gas Extraction",
            "Mining/Oil/Gas Extraction",
            "Accommodation/Food Services",
            "Educational Services",
            "Real Estate",
            "Manufacturing",
            "Retail",
            "Warehousing",
            "Transportation",
            "Information",
            "Utilities",
            "Wholesale",
            "Agriculture",
            "Construction",
            "Management",
        },
        key=len,
        reverse=True,
    )
)

_MAX_CITY_WORDS = 3
# The bundled Census gazetteer keys saint-prefixed cities with a period
# ("St. Paul"); the MN source drops it ("St Paul").
_ST_RE = re.compile(r"\bSt\b")


def _lookup_city(candidate: str) -> str | None:
    """Return the gazetteer-normalized city name if *candidate* is a known MN city."""
    for variant in (candidate, _ST_RE.sub("St.", candidate)):
        if city_centroids.lookup("MN", variant) is not None:
            return variant
    return None


def split_city_from_label(label: str | None) -> str | None:
    """Recover the MN worksite city from a wide-format label, or None.

    >>> split_city_from_label("Upsher-Smith 2025 Maple Grove Manufacturing")
    'Maple Grove'
    >>> split_city_from_label("Transaxle St Paul St Paul Manufacturing")
    'St. Paul'
    >>> split_city_from_label("Block 2024 San Francisco Information")  # out-of-state
    """
    if not label:
        return None
    s = label.strip()
    low = s.lower()
    for industry in _INDUSTRIES:
        if low.endswith(industry.lower()):
            s = s[: len(s) - len(industry)].rstrip()
            break

    words = s.split()
    for n in range(min(_MAX_CITY_WORDS, len(words)), 0, -1):
        city = _lookup_city(" ".join(words[-n:]))
        if city is not None:
            return city
    return None
