"""Conservative company-name normalization for consolidation.

`canonical_name` produces a comparison key that collapses *legal-form* variants
of the SAME company ("Acme Inc" / "Acme, LLC" / "ACME" -> "acme") without
collapsing genuinely different companies. It strips ONLY true legal-entity
suffixes — deliberately NOT the descriptive words in
``enrichment/lookup.py:_LEGAL_SUFFIXES`` (group/holdings/services/technologies/…),
which distinguish real companies and would over-merge ("Smith Services" vs
"Smith Technologies").
"""
from __future__ import annotations

import re

# True legal-entity suffixes only. Order doesn't matter; matched token-wise after
# punctuation is stripped, so "L.L.C" -> "llc" and "L L C" both normalize away.
_LEGAL_SUFFIXES: frozenset[str] = frozenset({
    "inc", "incorporated", "llc", "llp", "lllp", "lp", "ltd", "limited",
    "corp", "corporation", "co", "company", "plc", "pllc", "pc", "pa",
    "lc", "gmbh", "sa", "ag", "nv", "bv",
})

_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")
# Store/location-number markers that distinguish branches of ONE company:
#   "(1045) San Diego LGBT Community Center"  -> drop the leading "(1045)"
#   "Food 4 Less #364"                        -> drop the "#364"
# Stripped before tokenizing so all branches collapse to the same key.
_LEADING_STORE_NO = re.compile(r"^\s*\(\s*\d+\s*\)\s*")
_HASH_STORE_NO = re.compile(r"#\s*\d+")


# Site-designator patterns for search_name (display-case query cleaning, distinct
# from canonical_name's lowercase comparison key):
#   "10x Genomics, Inc. (6230)"   -> trailing "(6230)"
#   "MV Transportation 4499"      -> trailing bare site number(s)
#   "Google - Bordeaux" / "Amazon - SNA 20" -> trailing " - <site>" segment
# The dash rule requires whitespace around the dash so hyphenated names
# ("Mercedes-Benz", "Jo-Ann") are untouched.
_TRAILING_PAREN_NO = re.compile(r"\s*\(\s*\d+\s*\)\s*$")
_TRAILING_SITE_NO = re.compile(r"(?:\s+\d{3,})+\s*$")
# u2013 = en dash; some WARN sources use it instead of a hyphen.
_DASH_SEGMENT = re.compile(r"\s+[-\u2013]\s+(?P<seg>[^-\u2013]+?)\s*$")


def search_name(name: str | None) -> str:
    """Clean a WARN company name into an external-search query.

    WARN filings often carry per-site designators ("Google - Bordeaux",
    "MV Transportation 4499") that make exact-ish name search miss the actual
    company. This strips store/site markers while preserving case, so search
    providers (D&B type-ahead, EDGAR) see the recognizable company name. Over-
    stripping is low-risk: providers still score candidates against the query,
    so a wrong strip degrades to today's no-match, not a wrong match.
    """
    if not name:
        return ""
    s = _HASH_STORE_NO.sub(" ", _LEADING_STORE_NO.sub("", name))
    s = _TRAILING_PAREN_NO.sub("", s)
    m = _DASH_SEGMENT.search(s)
    if m:
        seg = m.group("seg")
        # Drop the segment when it looks like a site tag: contains a digit, or
        # is a short (<=2 word) suffix — never when it has its own legal form.
        seg_tokens = seg.lower().replace(",", " ").split()
        looks_like_site = any(ch.isdigit() for ch in seg) or (
            len(seg_tokens) <= 2 and not (seg_tokens and seg_tokens[-1] in _LEGAL_SUFFIXES)
        )
        if looks_like_site:
            s = s[: m.start()]
    s = _TRAILING_SITE_NO.sub("", s)
    s = _WS.sub(" ", s).strip(" ,")
    return s if s else name


def canonical_name(name: str | None) -> str:
    """Return the normalized comparison key for a company name (may be "")."""
    if not name:
        return ""
    cleaned = _HASH_STORE_NO.sub(" ", _LEADING_STORE_NO.sub("", name))
    s = _PUNCT.sub(" ", cleaned.lower())
    tokens = _WS.sub(" ", s).split()
    # Strip trailing legal suffixes (there can be more than one, e.g. "co inc").
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    if not tokens:  # name was nothing but legal tokens — fall back to the lot
        tokens = _WS.sub(" ", _PUNCT.sub(" ", name.lower())).split()
    return " ".join(tokens)
