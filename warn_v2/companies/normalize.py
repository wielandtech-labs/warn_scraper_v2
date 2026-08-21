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
# "Advance Stores Company, Incorporated and its subsidiary, Golden State ..." ->
# keep the parent. The subsidiary keyword trails "and its" rather than a bare
# comma, so _DESCRIPTIVE_CLAUSE (comma-anchored) misses it.
_SUBSIDIARY_CLAUSE = re.compile(r"\s+and\s+its\s+subsidiar(?:y|ies)\b.*$", re.IGNORECASE)
# Trailing footnote/status annotation introduced by a spaced asterisk:
# "... *Due to COVID-19 Tampa, FL 33607". The required leading whitespace keeps
# mid-name stars ("E*Trade") safe.
_TRAILING_STAR_NOTE = re.compile(r"\s+\*.*$")
# An unbalanced trailing "(" with no closing paren: "Tyson Foods, Inc. (Amarillo
# B-Shift Operations". Balanced parens keep their ")", so this never fires on them.
_TRAILING_OPEN_PAREN = re.compile(r"\s*\([^()]*$")
# Any trailing parenthetical, applied repeatedly: "(Remote Employees ...)",
# "(KI Jones Elementary)", "(6230)". Supersedes the old numeric-only rule.
# Tolerates trailing footnote stars glued to the paren ("(CANCELLED)**").
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\**\s*$")
# Same for square brackets: "GE Transportation Systems ... [Erie Plant]".
_TRAILING_BRACKET = re.compile(r"\s*\[[^\[\]]*\]\**\s*$")
# Trailing 1-2 digit affected-count, only when it directly follows a closing
# paren/bracket or the word "county" ("DuPont (Pickaway) 65"). The anchor keeps
# real short-number names ("Motel 6", "Pier 1", "Take 5 Oil Change") safe;
# 3+-digit counts are already handled by _TRAILING_SITE_NO.
_TRAILING_PAREN_COUNT = re.compile(r"([)\]]|\bcounty)\s*\d{1,2}\s*$", re.IGNORECASE)
# Dangling conjunction left over from a truncated multi-entity name:
# "Alliance Castings Company, LLC Alliance (Stark) 394 and".
_TRAILING_CONJ = re.compile(r"\s+(?:and|&)\s*$", re.IGNORECASE)
# Leading filing-status noise: bare star wrappers ("**JC Penney (Cancelled)",
# "*RESCINDED* Advanced Packaging, Inc.") and UPPERCASE status words
# ("UPDATE First Brands Group ..."). Case-sensitive on the words so an ordinary
# name like "Update Parts Inc" is never touched; a wrong strip on a genuinely
# star-named company degrades to a no-match per the module contract.
_LEADING_NOISE = re.compile(
    r"^\s*(?:\*+\s*|(?:UPDATED?|AMENDED|AMENDMENT|REVISED|RESCINDED|CORRECTED|"
    r"CANCELLED)\b\**[:\s-]+)"
)
# Appended worksite address, anchored on a trailing US state+ZIP — high
# precision. The leading-number requirement keeps real leading-number names
# ("10x Genomics", "3M", "10 Roads") safe; the middle is length-bounded so a
# digit-prefixed name without a real ZIP can't trigger catastrophic backtracking.
_TRAILING_ADDR_ZIP = re.compile(r"\s+\d{1,6}\s+.{0,80}?\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$")
# Trailing facility descriptors: "Target Corp. Distribution Center" -> the
# parent; "Home Depot Design Center" -> "Home Depot". Kept narrow — only words
# that are unambiguously facility tags, never a company's own name (so "5 Star
# Logistics Center" / "X Data Center" are left intact).
_FACILITY_SUFFIX = re.compile(
    r"\s+(?:distribution|design|fulfillment)\s+(?:center|centre)\s*$",
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
# Non-distinctive tokens for the faithfulness check: a match sharing ONLY one of
# these with the original is not evidence it's the same company ("Acme Healthcare"
# vs "Sutter Healthcare"). Superset of the single-token denylist plus common
# industry/descriptor words.
_GENERIC_MATCH_TOKENS: frozenset[str] = _GENERIC_SINGLE_TOKENS | frozenset({
    "health", "healthcare", "staffing", "restaurant", "restaurants", "hospital",
    "medical", "clinic", "care", "company", "corporation", "global", "american",
    "us", "usa", "capital", "financial", "technology", "technologies",
    "school", "schools", "transportation", "distribution", "manufacturing",
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
    # Collapse embedded newlines/runs of whitespace up front: every trailing-
    # anchored rule below uses ``.*$``, which can't cross a "\n", so a multi-line
    # stored name would silently defeat the descriptive/paren/address strips.
    s = _WS.sub(" ", s)
    # Leading status noise can stack ("**RESCINDED** Acme"); strip until stable,
    # but never down to nothing.
    head = s
    while True:
        stripped = _LEADING_NOISE.sub("", head, count=1)
        if stripped == head:
            break
        head = stripped
    if head.strip():
        s = head
    s = _HASH_STORE_NO.sub(" ", _LEADING_STORE_NO.sub("", s))
    s = _DBA.sub("", s)
    s = _DESCRIPTIVE_CLAUSE.sub("", s)
    s = _SUBSIDIARY_CLAUSE.sub("", s)
    s = _truncate_repeated_entity(s)
    # Trailing junk stacks in layers ("... (Trumbull) 150": the count hides the
    # parenthetical from the paren rule), so run the whole trailing block to a
    # fixed point — each pass only ever shortens the string, so this terminates.
    while True:
        prev = s
        s = _TRAILING_STAR_NOTE.sub("", s)
        s = _TRAILING_OPEN_PAREN.sub("", s)
        s = _TRAILING_ADDR_ZIP.sub("", s)
        # Trailing parens/brackets can stack ("Foo (Bar) (1234)"); strip until stable.
        while True:
            stripped = _TRAILING_BRACKET.sub("", _TRAILING_PAREN.sub("", s))
            if stripped == s:
                break
            s = stripped
        s = _TRAILING_PAREN_COUNT.sub(r"\1", s)
        s = _TRAILING_CONJ.sub("", s)
        s = _strip_dash_segment(s)
        s = _FACILITY_SUFFIX.sub("", s)
        s = _TRAILING_SITE_NO.sub("", s)
        if s == prev:
            break
    s = _WS.sub(" ", s).strip(" ,")
    return s if s else name


# Trade-name extraction for the dba retry: everything AFTER the marker, the
# mirror image of _DBA (which keeps the legal entity). Includes aka/fka — a
# former or alternate name is still a searchable identity.
_DBA_EXTRACT = re.compile(
    r"\b(?:d/b/a|d\.b\.a\.?|dba|a/k/a|a\.k\.a\.?|aka|f/k/a|f\.k\.a\.?|fka)\b"
    r"[:\s]+(?P<trade>.+)$",
    re.IGNORECASE,
)


def dba_name(name: str | None) -> str | None:
    """Return the cleaned trade-name side of a dba/aka/fka clause, or None.

    ``search_name`` keeps the legal entity and drops the trade name — the right
    default, but when the legal entity misses ("Managed Services-IDS (dba
    Cardinal Health)") the trade name is the better query. Works on the raw
    name because the clause often lives inside a parenthetical that
    ``search_name`` deletes outright.
    """
    if not name:
        return None
    s = _WS.sub(" ", html.unescape(name).translate(_SMART_QUOTES))
    m = _DBA_EXTRACT.search(s)
    if not m or m.start() == 0:  # a name that IS the marker word is not a clause
        return None
    trade = search_name(m.group("trade").strip(" ,").rstrip(")]").strip(" ,"))
    if not trade or is_unsearchable(trade):
        return None
    if trade.lower() == search_name(name).lower():
        return None
    return trade


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
    """Collapse a comma-delimited list of near-identical entities to the first.

    "10 Roads Express LLC, 10 Roads Service, LLC, 10 Roads Logistics, LLC" all
    resolve to one company; truncate at the comma-delimited segment that repeats
    the leading two-token stem. Requires the recurrence to begin a new
    comma-segment so prose repetition ("Los Angeles County of Los Angeles") is
    left alone.
    """
    if "," not in s:
        return s
    tokens = s.split()
    if len(tokens) < 4:
        return s
    stem = " ".join(tokens[:2])
    needle = ", " + stem
    idx = s.lower().find(needle.lower(), len(stem))
    if idx > 0:
        return s[:idx].strip(" ,")
    return s


def _fuse_initialisms(tokens: list[str]) -> list[str]:
    """Fuse runs of >=2 consecutive single-letter tokens into one token.

    Punctuation stripping tokenizes "T&H" and "T & H" differently ("t h" both,
    but only after the "&" is dropped); fusing the run to "th" gives both
    spellings the same distinctive token so the faithfulness check can see
    they agree. A lone single letter ("Toys R Us") is left as-is.
    """
    out: list[str] = []
    run: list[str] = []
    for t in tokens:
        if len(t) == 1 and t.isalpha():
            run.append(t)
            continue
        out.extend(["".join(run)] if len(run) >= 2 else run)
        run = []
        out.append(t)
    out.extend(["".join(run)] if len(run) >= 2 else run)
    return out


def _significant_tokens(name: str) -> set[str]:
    """Distinctive lowercase tokens of a name (no legal suffixes, stopwords,
    pure numbers, or single chars) — the basis for the faithfulness check."""
    return {
        t
        for t in _fuse_initialisms(canonical_name(name).split())
        if t not in _STOPWORDS and not t.isdigit() and len(t) > 1
    }


# Scraped table-header fragments that ended up stored as company names
# ("# AFFECTED 85", "# AFFECTED/ EFFECTIVE DATE:").
_HEADER_ARTIFACT = re.compile(r"#\s*AFFECTED|EFFECTIVE\s+DATE", re.IGNORECASE)
# A name cut off mid-phrase upstream ("Bank of", "Medical College of"): any
# match would be pure guesswork, so don't search at all. Deliberately narrow —
# "in"/"at"/"to" would false-positive on real names ("Sonic Drive In").
_DANGLING_LAST_TOKENS: frozenset[str] = frozenset({"of", "for", "the"})


def is_unsearchable(cleaned: str) -> bool:
    """True when a cleaned query is too generic or too broken to look up: a
    lone generic token ("Alliance"), a header artifact stored as a name, a
    string with no letters at all ("#1349"), or a name truncated mid-phrase
    ("Bank of"). Lets aggressive stripping run without risking
    luck-of-the-draw matches."""
    tokens = cleaned.split()
    if not tokens:
        return True
    if len(tokens) == 1 and tokens[0].lower() in _GENERIC_SINGLE_TOKENS:
        return True
    if _HEADER_ARTIFACT.search(cleaned):
        return True
    if not any(ch.isalpha() for ch in cleaned):
        return True
    return tokens[-1].lower() in _DANGLING_LAST_TOKENS


def match_is_consistent(original: str, matched: str) -> bool:
    """True if a provider match stays faithful to the original WARN name.

    Aggressive cleaning casts a wide net; this is the acceptance guard. The
    matched entity must share a *distinctive* token with the *original* name: a
    common industry word ("healthcare", "logistics") shared between two
    different firms is not evidence they're the same company, so the shared set
    must contain at least one non-generic token.
    """
    orig = _significant_tokens(original)
    if not orig:
        # Ampersand/short names ("AT&T", "H&M") reduce to no significant tokens
        # (punctuation dropped, single letters excluded), so there's nothing to
        # check faithfulness against. Auto-rejecting would lock every such
        # company out of a DUNS forever; trust the provider's own match +
        # similarity threshold instead.
        return True
    shared = orig & _significant_tokens(matched)
    return bool(shared - _GENERIC_MATCH_TOKENS)


def cleaned_key(name: str | None) -> str:
    """Site-variant grouping key: canonical form of the SEARCH-cleaned name.

    More aggressive than ``canonical_name`` alone — site designators collapse
    ("ABM Industries - 1120" and "ABM Industries Incorporated" share a key), so
    use it only where an acceptance guard backs it up (sibling enrichment
    propagation), never for destructive merging.
    """
    return canonical_name(search_name(name))


def canonical_name(name: str | None) -> str:
    """Return the normalized comparison key for a company name (may be "")."""
    if not name:
        return ""
    cleaned = _HASH_STORE_NO.sub(" ", _LEADING_STORE_NO.sub("", name))
    s = _PUNCT.sub(" ", cleaned.lower())
    tokens = _WS.sub(" ", s).split()
    # Drop a single leading "the" so "The Boeing Company" keys the same as
    # "Boeing Company" (-> "boeing"). Only when other tokens remain, so a name
    # that is nothing but "The" still has something to key on.
    if len(tokens) > 1 and tokens[0] == "the":
        tokens = tokens[1:]
    # Strip trailing legal suffixes (there can be more than one, e.g. "co inc").
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    if not tokens:  # name was nothing but legal tokens — fall back to the lot
        tokens = _WS.sub(" ", _PUNCT.sub(" ", name.lower())).split()
    return " ".join(tokens)
