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


def canonical_name(name: str | None) -> str:
    """Return the normalized comparison key for a company name (may be "")."""
    if not name:
        return ""
    s = _PUNCT.sub(" ", name.lower())
    tokens = _WS.sub(" ", s).split()
    # Strip trailing legal suffixes (there can be more than one, e.g. "co inc").
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    if not tokens:  # name was nothing but legal tokens — fall back to the lot
        tokens = _WS.sub(" ", _PUNCT.sub(" ", name.lower())).split()
    return " ".join(tokens)
