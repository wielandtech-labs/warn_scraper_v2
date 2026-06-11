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
from collections import Counter
from datetime import date

import pdfplumber

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

# City-state-zip at end of address line: "Anchorage, AK 99501".
# Captures (city, state, zip) so callers can prefer in-state worksite matches over
# the state-official recipient block at the top of a WARN letter.
_CITY_STATE_ZIP_RE = re.compile(
    r"([A-Za-z][A-Za-z .]{1,30}),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\b"
)

# Cap OCR to the first few pages — the worksite/recipient addresses are always on
# the opening page(s), and OCR is slow (~seconds/page).
_OCR_MAX_PAGES = 3


def extract_warn_fields(pdf_bytes: bytes, state: str | None = None) -> dict:
    """Extract WARN notice fields from raw PDF bytes.

    Returns a dict with any subset of:
      layoff_count (int), effective_date (date),
      address (str), city (str), zip (str)

    *state* (the notice's 2-letter state) biases city/ZIP selection toward an
    in-state worksite, avoiding the state-official recipient block (e.g. the
    capital) and out-of-state corporate HQ a WARN letter also lists.

    Returns ``{}`` on any failure (never raises).
    """
    try:
        text = _extract_text(pdf_bytes)
        if not text:
            return {}
        return _parse_text(text, state)
    except Exception as e:
        log.debug("pdf_extract: failed to parse PDF: %s", e)
        return {}


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract all text from a PDF, falling back to OCR for scanned-image PDFs."""
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                parts.append(t)
    text = "\n".join(parts)
    if text.strip():
        return text
    # No embedded text layer (scanned image, e.g. WV/HI) → OCR fallback.
    return _ocr_text(pdf_bytes)


def _ocr_text(pdf_bytes: bytes, max_pages: int = _OCR_MAX_PAGES) -> str:
    """OCR the first *max_pages* pages of a scanned PDF; "" if OCR is unavailable.

    Lazy-imports pdf2image/pytesseract (and relies on the poppler + tesseract
    binaries in the image) so a missing OCR stack degrades to "" rather than raising.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
    except Exception as e:  # libs not installed (e.g. local test env)
        log.debug("pdf_extract: OCR libraries unavailable: %s", e)
        return ""
    try:
        images = convert_from_bytes(
            pdf_bytes, dpi=200, first_page=1, last_page=max_pages
        )
    except Exception as e:  # poppler missing / unrasterizable
        log.debug("pdf_extract: OCR rasterize failed: %s", e)
        return ""
    out: list[str] = []
    for img in images:
        try:
            out.append(pytesseract.image_to_string(img))
        except Exception as e:
            log.debug("pdf_extract: OCR failed on a page: %s", e)
    log.info("pdf_extract: OCR fallback produced %d chars", sum(len(o) for o in out))
    return "\n".join(out)


def _choose_city_zip(text: str, state: str | None) -> tuple[str, str] | None:
    """Pick the best (city, zip) from a letter's "City, ST ZIP" lines.

    WARN letters open with a recipient block (Governor, state DOL — often the
    capital) and may list a corporate HQ, so the first match is unreliable. When
    *state* is known, restrict to in-state matches and take the most frequent
    (the worksite city/ZIP repeats across the letter); fall back to the first match
    overall when there's no state hint or no in-state match.
    """
    matches = _CITY_STATE_ZIP_RE.findall(text)  # [(city, st, zip), ...]
    if not matches:
        return None
    norm = [(c.strip().title(), st.upper(), z) for c, st, z in matches]
    if state:
        in_state = [(c, z) for c, st, z in norm if st == state.upper()]
        if in_state:
            counts = Counter(in_state)
            top = max(counts.values())
            for cz in in_state:  # first-seen among the most frequent
                if counts[cz] == top:
                    return cz
    return norm[0][0], norm[0][2]


def _parse_text(text: str, state: str | None = None) -> dict:
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
    city_zip = _choose_city_zip(text, state)
    if city_zip:
        result["city"], result["zip"] = city_zip

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
