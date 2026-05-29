"""Free enrichment lookups: SEC EDGAR (SIC) and SIC→NAICS crosswalk.

Tier 2 of the enrichment cascade — runs after the optional external provider
and before the Claude Haiku fallback.

EDGAR API
---------
Uses the SEC EDGAR full-text search (no authentication required):

    GET https://efts.sec.gov/LATEST/search-index
        ?q="COMPANY+NAME"&forms=10-K,10-Q&dateRange=custom&startdt=2010-01-01

Each hit's ``_source`` contains ``entity_name`` and ``sic``.  The company name
is matched with :func:`~difflib.SequenceMatcher` after stripping legal suffixes
— only results scoring ≥ 0.75 are accepted.

NAICS crosswalk
---------------
A bundled JSON at ``warn_v2/enrichment/_data/sic_naics_crosswalk.json`` maps
SIC codes to NAICS codes.  This is a sector-level approximation for codes not
covered by a more precise lookup.  Generate / regenerate the file with::

    uv run python -m warn_v2.scripts.fetch_sic_naics_crosswalk
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_EDGAR_URL = "https://efts.sec.gov/LATEST/search-index"
_EDGAR_TIMEOUT = 8  # seconds

_SIC_DESC_PATH = Path(__file__).parent / "_data" / "sic_descriptions.json"
_CROSSWALK_PATH = Path(__file__).parent / "_data" / "sic_naics_crosswalk.json"

# Loaded once; protected by _LOCK
_sic_descriptions: dict[str, str] | None = None
_sic_naics: dict[str, list[str]] | None = None
_LOCK = threading.Lock()

# Legal suffixes stripped before name comparison
_LEGAL_SUFFIXES = frozenset(
    [
        "inc", "llc", "corp", "corporation", "ltd", "co", "company",
        "incorporated", "limited", "lp", "lllp", "plc", "group", "holdings",
        "international", "solutions", "services", "technologies", "enterprises",
        "associates", "partners", "industries",
    ]
)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class LookupResult:
    """Result from the EDGAR tier — SIC code and optional NAICS approximation."""

    entity_name: str            # matched entity name from EDGAR
    sic_code: str | None = None
    sic_desc: str | None = None
    naics_code: str | None = None
    naics_desc: str | None = None
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def normalize_name(name: str) -> str:
    """Lowercase, strip punctuation, and remove common legal suffixes."""
    name = re.sub(r"[,\.&'\-/]", " ", name.lower())
    tokens = [t for t in name.split() if t not in _LEGAL_SUFFIXES and t]
    return " ".join(tokens)


def _name_score(a: str, b: str) -> float:
    na, nb = normalize_name(a), normalize_name(b)
    return SequenceMatcher(None, na, nb).ratio()


def _load_sic_descriptions() -> dict[str, str]:
    global _sic_descriptions
    if _sic_descriptions is None:
        with _LOCK:
            if _sic_descriptions is None:
                if _SIC_DESC_PATH.exists():
                    _sic_descriptions = json.loads(_SIC_DESC_PATH.read_text())
                else:
                    log.warning("SIC descriptions file not found at %s", _SIC_DESC_PATH)
                    _sic_descriptions = {}
    return _sic_descriptions


def _load_crosswalk() -> dict[str, list[str]]:
    global _sic_naics
    if _sic_naics is None:
        with _LOCK:
            if _sic_naics is None:
                if _CROSSWALK_PATH.exists():
                    _sic_naics = json.loads(_CROSSWALK_PATH.read_text())
                else:
                    log.warning("SIC→NAICS crosswalk not found at %s", _CROSSWALK_PATH)
                    _sic_naics = {}
    return _sic_naics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def naics_from_sic(sic_code: str) -> tuple[str, str] | None:
    """Return ``(naics_code, naics_desc)`` for a SIC code, or ``None``.

    Uses the bundled SIC→NAICS crosswalk.  For SIC codes not in the crosswalk,
    returns ``None`` rather than guessing.
    """
    entry = _load_crosswalk().get(sic_code)
    if entry and len(entry) >= 2:
        return entry[0], entry[1]
    return None


def edgar_lookup(
    company_name: str,
    state: str | None = None,
) -> LookupResult | None:
    """Search SEC EDGAR for the company's SIC code.

    Returns a :class:`LookupResult` when a name-matching SEC filer is found,
    ``None`` otherwise.  Never raises — network/parse errors are logged and
    return ``None`` so the enrichment cascade can continue.

    Args:
        company_name: Company name as it appears in the WARN notice.
        state: Two-letter US state code used as an optional filter.
    """
    params: dict[str, str] = {
        "q": f'"{company_name}"',
        "forms": "10-K,10-Q",
        "dateRange": "custom",
        "startdt": "2010-01-01",
    }
    if state:
        params["locationCode"] = state.upper()

    try:
        resp = httpx.get(
            _EDGAR_URL,
            params=params,
            timeout=_EDGAR_TIMEOUT,
            headers={"User-Agent": "warn-v2/0.1 (research; raphael@wielandtech.com)"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.debug("EDGAR lookup failed for %r: %s", company_name, exc)
        return None

    hits = data.get("hits", {}).get("hits", [])
    sic_descs = _load_sic_descriptions()

    for hit in hits[:10]:
        src = hit.get("_source", {})
        entity_name: str = src.get("entity_name") or ""
        sic: str | None = src.get("sic") or None

        if not entity_name or not sic:
            continue

        score = _name_score(company_name, entity_name)
        if score < 0.75:
            continue

        sic_desc = sic_descs.get(sic)
        naics_pair = naics_from_sic(sic) if sic else None

        confidence = 0.85 if score >= 0.90 else 0.70
        source_url = f"https://efts.sec.gov/LATEST/search-index?q={company_name!r}&forms=10-K,10-Q"

        log.debug(
            "EDGAR hit for %r → %r (SIC %s, score=%.2f)",
            company_name, entity_name, sic, score,
        )

        return LookupResult(
            entity_name=entity_name,
            sic_code=sic,
            sic_desc=sic_desc,
            naics_code=naics_pair[0] if naics_pair else None,
            naics_desc=naics_pair[1] if naics_pair else None,
            confidence=confidence,
            sources=[source_url],
        )

    return None
