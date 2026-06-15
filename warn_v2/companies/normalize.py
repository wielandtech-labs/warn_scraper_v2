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

import html
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
# from canonical_name's lowercase comparison key). search_name strips the noise
# WARN filings wrap around the real company name so D&B/EDGAR type-ahead can find
# it. Aggressive stripping is paired with acceptance-side certainty guards
# (match_is_consistent / is_unsearchable + the provider's similarity threshold),
# so casting a wide net can never persist a *wrong* DUNS — at worst it degrades
# to today's no-match.
_TRAILING_SITE_NO = re.compile(r"(?:\s+\d{3,})+\s*$")
# u2013 = en dash; some WARN sources use it instead of a hyphen. The dash rule
# requires whitespace around the dash so hyphenated names ("Mercedes-Benz",
# "Jo-Ann", "MBV-CA") are untouched.
_DASH_SEGMENT = re.compile(r"\s+[-–]\s+(?P<seg>[^-–]+?)\s*$")  # noqa: RUF001
# "Good Sports Plus Ltd. dba Arc" / "GMRI, Inc. d/b/a Eddie V's" -> keep the
# legal entity before the trade name (consume an optional leading comma too).
_DBA = re.compile(r"\s*,?\s+(?:d/b/a|d\.b\.a\.?|dba)\s+.*$", re.IGNORECASE)
# "TC&Js Enterprises, franchise operator of Chick-fil-A" -> drop the descriptive
# clause. Keyed on markers so it never cuts a ", Inc."/law-firm-style name.
_DESCRIPTIVE_CLAUSE = re.compile(
    r"\s*,\s*(?:a |an )?(?:franchise|franchisee|operator|division|subsidiary|"
    r"formerly|f/k/a|a/k/a|n/k/a)\b.*$",
    re.IGNORECASE,
)
# Any trailing parenthetical, applied repeatedly: "(Remote Employees ...)",
# "(KI Jones Elementary)", "(6230)". Supersedes the old numeric-only rule.
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")
# Appended worksite address: anchored on a US state+ZIP, or a street number +
# street-type word. The leading-number requirement keeps real leading-number
# names ("10x Genomics", "3M", "10 Roads") safe.
_TRAILING_ADDR_ZIP = re.compile(r"\s+\d{1,6}\s+.*?\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$")
_TRAILING_ADDR_STREET = re.compile(
    r"\s+\d{1,6}\s+\S.*?\b(?:st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|"
    r"ct|court|ln|lane|way|pkwy|parkway|hwy|highway|ste|suite|fl|floor|plz|plaza)\b\.?.*$",
    re.IGNORECASE,
)
# Trailing facility descriptors: "Target Corp. Distribution Center" -> the
# parent; "Home Depot Design Center" -> "Home Depot".
_FACILITY_SUFFIX = re.compile(
    r"\s+(?:distribution|design|fulfillment|service|call|data|logistics|"
    r"manufacturing|operations)\s+(?:center|centre|facility)\s*$",
    re.IGNORECASE,
)

# Single tokens too generic to search on their own: an aggressive strip that
# collapses a name to one of these (e.g. "Alliance (Piera Barbaglia ...)"
# -> "Alliance") would only ever match D&B by luck, so we skip the lookup.
_GENERIC_SINGLE_TOKENS: frozenset[str] = frozenset({
    "alliance", "services", "service", "solutions", "group", "associates",
    "partners", "holdings", "enterprises", "industries", "systems",
    "management", "center", "consulting", "logistics", "ministries",
    "foundation", "institute", "international", "national", "regional",
})
# Joining words ignored when checking that a match stays faithful to the original.
_STOPWORDS: frozenset[str] = frozenset({
    "the", "of", "and", "for", "at", "in", "on", "to", "a", "an",
})
# Curly quotes (often arriving via HTML entities like &rsquo;) -> ASCII, so
# "McDonald" + curly apostrophe searches the same as "McDonald's".
_SMART_QUOTES = {
    0x2018: "'", 0x2019: "'", 0x201A: "'", 0x201B: "'",
    0x201C: '"', 0x201D: '"',
}


def search_name(name: str | None) -> str:
    """Clean a WARN company name into an external-search query.

    WARN filings wrap the real company name in per-site designators, worksite
    addresses, dba trade names, and descriptive clauses that make exact-ish
    search miss the actual entity. This strips all of that while preserving
    case. Aggressive by design: the acceptance-side guards (the provider's
    similarity threshold, ``is_unsearchable``, ``match_is_consistent``) ensure a
    wrong strip degrades to a no-match rather than a wrong DUNS.
    """
    if not name:
        return ""
    s = html.unescape(name).translate(_SMART_QUOTES)  # "McDonald&rsquo;s" -> "McDonald's"
    s = _HASH_STORE_NO.sub(" ", _LEADING_STORE_NO.sub("", s))
    s = _DBA.sub("", s)
    s = _DESCRIPTIVE_CLAUSE.sub("", s)
    s = _truncate_repeated_entity(s)
    s = _TRAILING_ADDR_ZIP.sub("", s)
    s = _TRAILING_ADDR_STREET.sub("", s)
    # Trailing parens can stack ("Foo (Bar) (1234)"); strip until stable.
    while True:
        stripped = _TRAILING_PAREN.sub("", s)
        if stripped == s:
            break
        s = stripped
    s = _strip_dash_segment(s)
    s = _FACILITY_SUFFIX.sub("", s)
    s = _TRAILING_SITE_NO.sub("", s)
    s = _WS.sub(" ", s).strip(" ,")
    return s if s else name


def _strip_dash_segment(s: str) -> str:
    """Drop a trailing ' - <segment>' worksite tag.

    Strips any spaced-dash trailing segment unless the segment is itself a legal
    entity (ends in a legal suffix), in which case it's the real company and we
    keep the whole string. Requires a non-trivial prefix to remain.
    """
    m = _DASH_SEGMENT.search(s)
    if not m:
        return s
    seg_tokens = m.group("seg").lower().replace(",", " ").split()
    if seg_tokens and seg_tokens[-1] in _LEGAL_SUFFIXES:
        return s  # "Acme - Widgets LLC": the segment is the entity
    prefix = s[: m.start()].strip(" ,")
    return prefix if prefix else s


def _truncate_repeated_entity(s: str) -> str:
    """Collapse a list of near-identical entities to the first.

    "10 Roads Express LLC, 10 Roads Service, LLC, 10 Roads Logistics, LLC" all
    resolve to one company; truncate at the second occurrence of the leading
    two-token stem so the query is just "10 Roads Express LLC".
    """
    tokens = s.split()
    if len(tokens) < 4:
        return s
    stem = " ".join(tokens[:2]).lower()
    idx = s.lower().find(stem, len(stem))
    if idx > 0:
        return s[:idx].strip(" ,")
    return s


def _significant_tokens(name: str) -> set[str]:
    """Distinctive lowercase tokens of a name (no legal suffixes, stopwords,
    pure numbers, or single chars) — the basis for the faithfulness check."""
    return {
        t
        for t in canonical_name(name).split()
        if t not in _STOPWORDS and not t.isdigit() and len(t) > 1
    }


def is_unsearchable(cleaned: str) -> bool:
    """True when a cleaned query is too generic to look up (a lone generic
    token). Lets aggressive stripping run without risking luck-of-the-draw
    matches on names like "Alliance"."""
    tokens = cleaned.split()
    return len(tokens) == 1 and tokens[0].lower() in _GENERIC_SINGLE_TOKENS


def match_is_consistent(original: str, matched: str) -> bool:
    """True if a provider match stays faithful to the original WARN name.

    Aggressive cleaning casts a wide net; this is the acceptance guard. The
    matched entity must share a distinctive token with the *original* name, so
    an over-stripped query that resolved to an unrelated company is rejected
    rather than persisted as a wrong DUNS.
    """
    a = _significant_tokens(original)
    b = _significant_tokens(matched)
    return bool(a and b and (a & b))


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
