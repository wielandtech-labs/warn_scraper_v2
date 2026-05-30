"""Best-effort field extraction from WARN notice PDFs.

WARN notices are formal letters following federal requirements, so they share
common language patterns across states. This module extracts structured fields
from raw PDF bytes using pdfplumber for text and regex for field matching.

All extraction is best-effort: if a field cannot be reliably identified, it is
omitted from the result dict rather than returning a wrong value.
"""
from __future__ import annotations

import io
import logging
import re
from datetime import date

import pdfplumber  # noqa: F401 — imported at module level so tests can patch it

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# "affecting 150 full-time employees" / "150 permanent employees affected"
_COUNT_SPECIFIC_RE = re.compile(
    r"affect(?:ing|ed)\s+(\d{1,4})\s+(?:full[- ]?time\s+)?(?:permanent\s+)?(?:workers?|employees?)",
    re.I,
)
# Generic "N employees" — lower confidence, used as fallback
_COUNT_GENERIC_RE = re.compile(
    r"\b(\d{1,4})\s+(?:full[- ]?time\s+)?(?:permanent\s+)?(?:workers?|employees?)\b",
    re.I,
)

# "effective [on or about] March 15, 2024" or "effective 03/15/2024"
_EFFECTIVE_DATE_RE = re.compile(
    r"effective\s+"
    r"(?:date\s*(?:of\s+(?:the\s+)?(?:layoff|separation|closure)?\s*)?:?\s*)?"
    r"(?:on\s+or\s+about\s+)?"
    r"(?:is\s+)?"
    r"((?:[A-Za-z]+\s+\d{1,2},?\s*\d{4})|(?:\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}))",
    re.I,
)

# Standard US address street suffix list.
# Uses greedy middle + no-comma char class so the engine backtracks to the
# last suffix word rather than stopping mid-word (e.g. "st" inside "Industrial").
_ADDR_RE = re.compile(
    r"(\d{1,5}"                              # house number
    r"\s+[A-Za-z0-9][A-Za-z0-9 #.\-]+"      # street name words (greedy, comma excluded)
    r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|"
    r"Lane|Ln|Way|Court|Ct|Place|Pl|Circle|Cir|Highway|Hwy|"
    r"Parkway|Pkwy|Route|Suite|Ste|Building|Bldg)"
    r"\.?(?:\s+(?:Suite|Ste\.?|#)\s*\S+)?)",  # optional unit suffix
    re.I,
)

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

# City-state-zip at end of address line: "Anchorage, AK 99501"
_CITY_STATE_ZIP_RE = re.compile(
    r"([A-Za-z][A-Za-z ]{1,30}),\s*[A-Z]{2}\s+(\d{5})(?:-\d{4})?\b"
)


def extract_warn_fields(pdf_bytes: bytes) -> dict:
    """Extract WARN notice fields from raw PDF bytes.

    Returns a dict with any subset of:
      layoff_count (int), effective_date (date),
      address (str), city (str), zip (str)

    Returns ``{}`` on any failure (never raises).
    """
    try:
        text = _extract_text(pdf_bytes)
        if not text:
            return {}
        return _parse_text(text)
    except Exception as e:
        log.debug("pdf_extract: failed to parse PDF: %s", e)
        return {}


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF using pdfplumber."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    return "\n".join(parts)


def _parse_text(text: str) -> dict:
    result: dict = {}

    # --- layoff_count ---
    m = _COUNT_SPECIFIC_RE.search(text)
    if m:
        try:
            result["layoff_count"] = int(m.group(1))
        except ValueError:
            pass
    if "layoff_count" not in result:
        m = _COUNT_GENERIC_RE.search(text)
        if m:
            try:
                result["layoff_count"] = int(m.group(1))
            except ValueError:
                pass

    # --- effective_date ---
    m = _EFFECTIVE_DATE_RE.search(text)
    if m:
        d = _parse_date(m.group(1).strip())
        if d is not None:
            result["effective_date"] = d

    # --- address + city + zip ---
    # Try "City, ST ZIP" pattern first — most reliable city extraction
    city_m = _CITY_STATE_ZIP_RE.search(text)
    if city_m:
        result["city"] = city_m.group(1).strip().title()
        result["zip"] = city_m.group(2)

    # Street address
    addr_m = _ADDR_RE.search(text)
    if addr_m:
        result["address"] = addr_m.group(0).strip()

    # ZIP fallback: if no city-state-zip match, grab the last 5-digit ZIP
    if "zip" not in result:
        zips = _ZIP_RE.findall(text)
        if zips:
            result["zip"] = zips[-1]

    return result


def _parse_date(text: str) -> date | None:
    """Parse a date string to a date object."""
    from warn_v2.scrapers._helpers import as_date
    return as_date(text)
