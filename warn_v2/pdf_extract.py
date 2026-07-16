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

# Full state name -> USPS abbreviation. WARN letters often spell the state out
# ("Kapolei, Hawaii 96707"), which a 2-letter-only pattern would drop — losing the
# worksite even though it's right there in the text.
_STATE_TO_ABBR: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA", "hawaii": "HI",
    "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
# Longest-first so "West Virginia" wins over "Virginia" in the alternation.
_STATE_NAME_ALT = "|".join(
    sorted((re.escape(n) for n in _STATE_TO_ABBR), key=len, reverse=True)
)

# City-state-zip at end of address line: "Anchorage, AK 99501" or "Kapolei, Hawaii
# 96707". Captures (city, state, zip) so callers can prefer in-state worksite
# matches over the state-official recipient block at the top of a WARN letter. The
# 2-letter branch stays case-sensitive (uppercase); full names match any case via
# the scoped (?i:...) group. Normalize the state with _normalize_state.
_CITY_STATE_ZIP_RE = re.compile(
    r"([A-Za-z][A-Za-z .]{1,30}),\s*"
    r"([A-Z]{2}|(?i:" + _STATE_NAME_ALT + r"))"
    r"\s+(\d{5})(?:-\d{4})?\b"
)


def _normalize_state(raw: str) -> str | None:
    """USPS abbreviation for a captured state token (2-letter or full name)."""
    if len(raw) == 2:
        return raw.upper()
    return _STATE_TO_ABBR.get(raw.lower())

# Cap OCR to the first few pages — the worksite/recipient addresses are always on
# the opening page(s), and OCR is slow (~seconds/page).
_OCR_MAX_PAGES = 3

# Cap OCR rasterization so an oversized page (a scan embedded at an abnormal
# point size — a TN Wayback capture was seen at 1600x2140pt vs. the ~612x792pt
# of a normal letter page) can't blow past the pdf-downloader Job's memory
# limit. pdftoppm renders directly at the capped resolution (poppler computes
# the render DPI from the target size up front, it doesn't rasterize at full
# size and then downscale), so this actually bounds peak memory.
_MAX_OCR_RASTER_PX = 2500


def _capped_ocr_dpi(pdf_bytes: bytes, requested_dpi: int, max_pages: int) -> int:
    """Lower *requested_dpi* if it would rasterize a considered page past
    ``_MAX_OCR_RASTER_PX`` on its longest side.

    Falls back to *requested_dpi* unchanged if the page size can't be read —
    the caller's own pdfplumber.open/convert_from_bytes will fail the same
    way moments later, which already degrades gracefully.
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            max_pt = max(
                (max(p.width, p.height) for p in pdf.pages[:max_pages]),
                default=0,
            )
    except Exception:
        return requested_dpi
    if max_pt <= 0:
        return requested_dpi
    capped = int(_MAX_OCR_RASTER_PX * 72 / max_pt)
    return min(requested_dpi, capped) if capped > 0 else requested_dpi

# A WARN letter addresses state officials (often at the capital) and may list a
# corporate HQ, so the worksite must be told apart from these. Worksite cues sit
# near the real address ("located at 1 Moore Ave, Buckhannon, WV 26201"); recipient
# cues mark the agency block ("Rapid Response ... Bldg. 3, Room 312, Charleston").
_WORKSITE_CUE = re.compile(
    r"locat|facilit|\bplant\b|worksite|work\s+site|operat|premises|"
    r"affect|lay(?:ing|-?off)|clos(?:e|ing|ure)|reduction|\bsite\b",
    re.I,
)
_RECIPIENT_CUE = re.compile(
    r"rapid\s+response|dislocated\s+worker|workforce|department\s+of\s+labor|"
    r"\bdirector\b|governor|honorable|\bmayor\b|commissioner|secretary|"
    r"\bbureau\b|\bbldg\b|\broom\s*\d|p\.?\s*o\.?\s*box",
    re.I,
)
# Known WARN-recipient agency addresses (state DOL / Rapid Response HQ) by
# (state, zip) — these recur verbatim across that state's letters.
_RECIPIENT_ZIPS: frozenset[tuple[str, str]] = frozenset(
    {("WV", "25305"), ("HI", "96813")}
)


def extract_warn_fields(pdf_bytes: bytes, state: str | None = None) -> dict:
    """Extract WARN notice fields from raw PDF bytes.

    Returns a dict with any subset of:
      layoff_count (int), effective_date (date),
      address (str), city (str), zip (str),
      occupations (list[tuple[str, int]] — see :func:`extract_occupations`)

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
        dpi = _capped_ocr_dpi(pdf_bytes, 200, max_pages)
        images = convert_from_bytes(
            pdf_bytes, dpi=dpi, first_page=1, last_page=max_pages
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


def ocr_word_boxes(
    pdf_bytes: bytes, *, dpi: int = 300, max_pages: int = _OCR_MAX_PAGES
) -> list[list[dict]]:
    """OCR a scanned PDF into positioned words, one list per page.

    Each word is a pdfplumber-``extract_words``-shaped dict —
    ``{"text": str, "x0": float, "top": float}`` — with ``x0``/``top``
    normalized from raster pixels back to PDF points (``px * 72 / dpi``), so a
    caller's column x-boundaries stay in the familiar ~0-612 point scale
    regardless of the OCR rasterization dpi.

    This is the positioned-word sibling of ``_ocr_text``: same lazy imports and
    same graceful degradation — returns ``[]`` (never raises) when the OCR stack
    (pdf2image/pytesseract + the poppler/tesseract binaries) is unavailable, so a
    non-OCR environment falls through to a clean "no rows" rather than crashing.
    """
    try:
        import pytesseract
        from pdf2image import convert_from_bytes
        from pytesseract import Output
    except Exception as e:  # libs not installed (e.g. local test env)
        log.debug("pdf_extract: OCR libraries unavailable: %s", e)
        return []
    try:
        dpi = _capped_ocr_dpi(pdf_bytes, dpi, max_pages)
        images = convert_from_bytes(pdf_bytes, dpi=dpi, first_page=1, last_page=max_pages)
    except Exception as e:  # poppler missing / unrasterizable
        log.debug("pdf_extract: OCR rasterize failed: %s", e)
        return []

    scale = 72.0 / dpi
    pages: list[list[dict]] = []
    for img in images:
        words: list[dict] = []
        try:
            data = pytesseract.image_to_data(img, config="--psm 6", output_type=Output.DICT)
        except Exception as e:
            log.debug("pdf_extract: OCR failed on a page: %s", e)
            pages.append(words)
            continue
        for text, left, top, conf in zip(
            data["text"], data["left"], data["top"], data["conf"], strict=True
        ):
            # tesseract emits blank/structural boxes with conf -1; keep only real words.
            if not text or not text.strip() or float(conf) < 0:
                continue
            words.append(
                {"text": text, "x0": left * scale, "top": top * scale}
            )
        pages.append(words)
    log.info(
        "pdf_extract: OCR word-box fallback produced %d words across %d page(s)",
        sum(len(p) for p in pages),
        len(pages),
    )
    return pages


def _most_frequent_cz(pool: list[tuple[str, str]]) -> tuple[str, str] | None:
    """Most frequent (city, zip) in *pool*; ties broken by first appearance."""
    if not pool:
        return None
    counts = Counter(pool)
    top = max(counts.values())
    for cz in pool:  # first-seen among the most frequent
        if counts[cz] == top:
            return cz
    return None


def _choose_city_zip(text: str, state: str | None) -> tuple[str, str] | None:
    """Pick the worksite (city, zip) from a letter's "City, ST ZIP" lines.

    WARN letters open with a recipient block (Governor, state DOL — often the
    capital) and may list a corporate HQ, so first-match is unreliable. With the
    notice *state* known, we keep only **in-state, non-recipient** matches, prefer
    those carrying a worksite cue, and take the most frequent. If nothing survives,
    return None (better un-geocoded than a false capital/HQ pin). Without a state
    hint we fall back to the first match (legacy callers / non-letter PDFs).
    """
    lines = text.splitlines()
    cands: list[tuple[str, str, str, bool, bool]] = []  # city, st, zip, worksite, recip
    for i, line in enumerate(lines):
        # Narrow window: the match's own line plus the line above (a city often sits
        # on its own line under a street/agency line). A wider window bleeds the
        # recipient block's markers onto a nearby worksite line.
        window = " ".join(lines[max(0, i - 1): i + 1])
        for m in _CITY_STATE_ZIP_RE.finditer(line):
            st = _normalize_state(m.group(2))
            if st is None:
                continue
            c, z = m.group(1).strip().title(), m.group(3)
            recip = (st, z) in _RECIPIENT_ZIPS or bool(_RECIPIENT_CUE.search(window))
            worksite = bool(_WORKSITE_CUE.search(window))
            cands.append((c, st, z, worksite, recip))
    if not cands:
        return None

    if state:
        s = state.upper()
        in_state = [(c, z, w) for c, st, z, w, r in cands if st == s and not r]
        cued = [(c, z) for c, z, w in in_state if w]
        plain = [(c, z) for c, z, w in in_state]
        return _most_frequent_cz(cued) or _most_frequent_cz(plain)

    return cands[0][0], cands[0][2]


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

    # ZIP fallback: if no city-state-zip match, grab the last 5-digit ZIP. Only when
    # the state is unknown — with a state, a bare last-ZIP would likely be the
    # recipient/HQ ZIP that state-aware selection just (correctly) rejected.
    if "zip" not in result and state is None:
        zips = _ZIP_RE.findall(text)
        if zips:
            result["zip"] = zips[-1]

    # --- occupations ("Position Titles / Number Impacted" table) ---
    occupations = extract_occupations(text)
    if occupations:
        result["occupations"] = occupations

    return result


def _parse_date(text: str) -> date | None:
    """Parse a date string to a date object."""
    from warn_v2.scrapers._helpers import as_date
    return as_date(text)


# ---------------------------------------------------------------------------
# Conservative layoff-count extraction (backfill-layoff-counts)
# ---------------------------------------------------------------------------
# CT/HI/WV publish no counts on their listing pages — the count exists only in
# the letter body. Unlike the download-time count regexes above (best-effort,
# first match wins), this path bulk-fills NULLs, so it prefers explicit totals
# and returns None on ambiguity rather than guessing.

_COUNT_NOUN = r"(?:employees?|workers?|positions?|individuals?)"
_COUNT_APPROX = r"(?:approximately\s+|about\s+|roughly\s+|up\s+to\s+)?"
_COUNT_NUM = r"(\d{1,3},\d{3}|\d{1,4})"
# Letters spell out small totals ("the total number of affected employees in
# West Virginia is one").
_COUNT_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
_COUNT_NUM_OR_WORD = (
    r"(\d{1,3},\d{3}|\d{1,4}|" + "|".join(_COUNT_WORD_TO_NUM) + r")"
)
# Bounded filler between the number and its noun ("100 full- and part-time
# positions", "71 Greenbrier Mineral employees"). No commas: a comma marks a
# clause/date boundary ("July 3, 2026, all employees ...").
_COUNT_GAP3 = r"(?:[\w&.'\-/()]+\s+){0,3}?"
_COUNT_GAP6 = r"(?:[\w&.'\-/()]+\s+){0,6}?"
_COUNT_AFFECTED = (
    r"(?:affected|impacted|laid[\s-]+off|terminated|separated|eliminated|"
    r"displaced)"
)
_COUNT_MONTHS = (
    r"(?:january|february|march|april|may|june|july|august|september|"
    r"october|november|december)"
)

# Tier 1 — explicit totals. In every pattern, group 1 is the count token.
_COUNT_TOTAL_RES = [
    # "the total separation of 73 employees" / "a total of 205 employees".
    # The filler between "total" and "of" is whitelisted to layoff nouns so
    # headcount phrasings ("total workforce of 500 employees") never match.
    re.compile(
        rf"\btotal\s+(?:(?:permanent\s+)?(?:separation|termination|"
        rf"elimination|displacement|layoff|loss|reduction)s?\s+)?of\s+"
        rf"{_COUNT_APPROX}{_COUNT_NUM}\s+{_COUNT_GAP3}{_COUNT_NOUN}",
        re.I,
    ),
    # "In total, this action will affect 205 employees"
    re.compile(
        rf"\bin\s+total\b[^.]{{0,80}}?\b(?:affect|impact)\w*\s+"
        rf"{_COUNT_APPROX}{_COUNT_NUM}\b",
        re.I,
    ),
    # "The total number of affected employees in West Virginia is one" /
    # "Total number of affected WGH employees: 291" (company abbreviation
    # between the affected-word and the noun). The gap is case-sensitively
    # capitalized so lowercase connectives can't dilute the affected-word
    # ("total number of affected and unaffected employees ... is 500").
    re.compile(
        rf"\btotal\s+number\s+of\s+(?:affected|impacted)\s+"
        rf"(?-i:(?:[A-Z][\w&.'\-]*\s+){{0,3}}?){_COUNT_NOUN}"
        rf"[^.\d]{{0,60}}?(?:\b(?:is|was|will\s+be)\s+|:\s*)"
        rf"{_COUNT_NUM_OR_WORD}\b",
        re.I,
    ),
    # "Approximate number of employees affected: 4" /
    # "Approximate number of employees to be laid off or terminated: 120" —
    # the affected-word is required, so establishment headcounts ("Number of
    # employees at Store: 8", "... employed by the establishment is 86")
    # never match.
    re.compile(
        rf"\bnumber\s+of\s+{_COUNT_NOUN}\s+"
        rf"(?:to\s+be\s+|being\s+|who\s+will\s+be\s+)?{_COUNT_AFFECTED}"
        rf"(?:\s+or\s+{_COUNT_AFFECTED})?"
        rf"\s*[:\-]?\s*{_COUNT_NUM_OR_WORD}\b",
        re.I,
    ),
]

# Tier 2 — the count adjacent to the layoff action.
_COUNT_ACTION_RES = [
    # "will affect 205 employees" / "affecting 150 full-time employees"
    re.compile(
        rf"\b(?:affect|impact)(?:s|ing|ed)?\s+{_COUNT_APPROX}{_COUNT_NUM}"
        rf"\s+{_COUNT_GAP3}{_COUNT_NOUN}",
        re.I,
    ),
    # "approximately 300 workers will be affected" /
    # "100 full- and part-time positions will be eliminated" /
    # "71 Greenbrier Mineral employees at the Mines will be terminated"
    re.compile(
        rf"\b{_COUNT_APPROX}{_COUNT_NUM}\s+{_COUNT_GAP3}{_COUNT_NOUN}"
        rf"\s+{_COUNT_GAP6}will\s+be\s+{_COUNT_AFFECTED}",
        re.I,
    ),
    # "laying off approximately 530 ... employees" /
    # "the permanent separation of 78 employees"
    re.compile(
        rf"\b(?:lay(?:ing)?\s+off|layoffs?\s+of|termination\s+of|"
        rf"separation\s+of|elimination\s+of|displacement\s+of)\s+"
        rf"{_COUNT_APPROX}{_COUNT_NUM}\s+{_COUNT_GAP3}{_COUNT_NOUN}",
        re.I,
    ),
    # "All 10 employees have been notified of their separation date"
    re.compile(rf"\ball\s+{_COUNT_NUM}\s+{_COUNT_NOUN}\b", re.I),
]

# Tier 3 — count+noun in a sentence that mentions the layoff action at all
# ("This mass layoff will affect every WVURC employee, which ... is 507
# employees").
_COUNT_ACTION_CUE = re.compile(
    r"affect|impact|lay[\s-]*off|laid[\s-]+off|terminat|separat|eliminat|"
    r"displac|reduction\s+in\s+force",
    re.I,
)
_COUNT_NUM_NOUN_RE = re.compile(
    rf"(?<![\d,]){_COUNT_NUM}\s+{_COUNT_GAP3}{_COUNT_NOUN}\b", re.I
)

# Tier 4 — a positions/counts table. Header names the count column ("no."
# keeps its period mandatory so the English word "no" in prose never opens a
# table); data rows end with the count, optionally followed by a separation
# date.
_COUNT_TABLE_HEADER_RE = re.compile(
    rf"(?:#|\bno\.|\bnumber)\s*(?:of\s+)?(?:affected\s+|impacted\s+)?"
    rf"{_COUNT_NOUN}|\bnumber\s+impacted\b|"
    rf"\b{_COUNT_NOUN}\s+(?:impacted|affected)\b",
    re.I,
)
_COUNT_ROW_DATE = (
    rf"(?:\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}|{_COUNT_MONTHS}\s+\d{{1,2}},?\s+\d{{4}})"
)
_COUNT_TABLE_ROW_RE = re.compile(
    rf"^(.*?[A-Za-z]{{2,}}.*?)\s(\d{{1,4}})(?:\s+{_COUNT_ROW_DATE})?\s*$", re.I
)
# A trailing small integer even where the full row shape fails (wrapped row
# continuations like "I 1") — any such line outside the parsed run poisons
# the table.
_COUNT_TRAILING_INT_RE = re.compile(rf"\s\d{{1,4}}(?:\s+{_COUNT_ROW_DATE})?\s*$", re.I)
_COUNT_GRAND_TOTAL_RE = re.compile(
    r"\bgrand\s+total\b\D{0,40}?(\d{1,4})\s*$", re.I
)
# No leading \b so "Subtotal" is caught too.
_COUNT_TOTAL_WORD_RE = re.compile(r"total\b", re.I)
_COUNT_PAGE_LINE_RE = re.compile(r"\bpage\b", re.I)
# A row-shaped line carrying these is a contact/address sentence ("call our
# office at Building 3 Room 312"), not a job-category row.
_COUNT_ROW_VETO_RE = re.compile(
    r"\b(?:please|contact|questions?|phone|email|sincerely|regards|"
    r"room|suite|floor|bldg|building|box)\b",
    re.I,
)


# A count right after these is the establishment size, not the layoff
# ("the Company employs a total of 500 employees").
_COUNT_HEADCOUNT_CUE = re.compile(
    r"\b(?:employs|employing|employed|workforce|staffs?)\b", re.I
)
# A year, month, or duration word inside the match means the number was a
# date part or a notice period ("60 days' notice to employees"), not a count.
_COUNT_GAP_POISON = re.compile(
    rf"\b(?:19|20)\d{{2}}\b|{_COUNT_MONTHS}|\b(?:day|week|month|year|hour)s?\b",
    re.I,
)


def _count_candidate(m: re.Match, text: str) -> int | None:
    """Validate a count match; None rejects it.

    Group 1 is the count token. Rejects: zero/implausible values; bare years
    (a count of exactly 1900-2099 at one site is far less likely than a date
    leak — comma-formatted "1,900" stays valid); dollar amounts ("a $500
    payment to employees"); day-of-month reads ("on July 3 2026 all
    employees ...", "On 3 July ..."); matches whose filler words carry a
    date or duration ("60 days' notice to employees"); and counts right
    after a headcount verb ("employs a total of 500 employees").
    """
    tok = m.group(1).lower()
    value = _COUNT_WORD_TO_NUM.get(tok)
    if value is None:
        try:
            value = int(tok.replace(",", ""))
        except ValueError:
            return None
    if not 1 <= value <= 9999:
        return None
    if "," not in tok and 1900 <= value <= 2099:
        return None
    # Dollar amounts, and phone/store/statute fragments ("808-943-6670",
    # "(808) 469-4900", "#057", "639.6") — the digits directly follow a
    # joining character, so they are part of a larger token, not a count.
    # Hyphen variants cover pdfminer's ToUnicode output (U+2010/U+2011,
    # U+2212); en/em dashes are excluded — they punctuate prose right before
    # legitimate counts ("the closing—75 employees ...") and essentially
    # never join phone digits.
    joiners = "$-/.#" + chr(0x2010) + chr(0x2011) + chr(0x2212)
    start = m.start(1)
    if start > 0 and text[start - 1] in joiners:
        return None
    # Line-wrapped fragments ("808-943-\n6670" flattens to "943- 6670"):
    # a digit + joiner + space right before the number is the same token
    # split across lines. A worded label ("laid off - 120") is not — the
    # joiner there follows a letter, not a digit.
    if (
        start >= 3
        and text[start - 1] == " "
        and text[start - 2] in joiners
        and text[start - 3].isdigit()
    ):
        return None
    before = text[max(0, m.start(1) - 12): m.start(1)]
    if re.search(_COUNT_MONTHS + r"\s*$", before, re.I):
        return None
    context = text[max(0, m.start(0) - 24): m.start(0)]
    if _COUNT_HEADCOUNT_CUE.search(context):
        return None
    after_num = text[m.end(1): m.end(0)]
    if _COUNT_GAP_POISON.search(after_num):
        return None
    return value


def _is_table_header(line: str) -> bool:
    """A count-column header: short, digit-free, and names the count column.

    The length/digit filters keep prose sentences that merely mention "the
    number of affected employees" (or labeled fields like "... affected: 4")
    from opening a table scan.
    """
    stripped = line.strip()
    return (
        len(stripped) <= 60
        and not any(c.isdigit() for c in stripped)
        and bool(_COUNT_TABLE_HEADER_RE.search(stripped))
    )


def _scan_table(
    lines: list[str], start: int
) -> tuple[int | None, list[tuple[str, int]]]:
    """Scan one table run from its header line; returns (count, rows).

    Rows are the parsed ``(title, count)`` data rows — the title column is
    whatever precedes the trailing count on each row line. Blank lines and
    page footers are transparent. Any count-shaped line that can't be
    trusted as a data row — a four-digit value (year/ZIP leak), a
    contact/address sentence ("... at Building 3 Room 312"), a wrapped-row
    fragment ("I 1") — poisons the whole table (None) rather than skewing
    the sum. A benign non-count line ends the run; count-shaped lines found
    beyond that point (wrapped rows, a second per-site table, a multi-state
    letter's nationwide pages) also poison it — a partial sum is a wrong
    answer, not a conservative one.
    """
    rows: list[tuple[str, int]] = []
    saw_subtotal = False
    grace = 3  # substantive non-row lines tolerated before the first row
    resume_at = len(lines)

    for i in range(start + 1, len(lines)):
        line = lines[i].strip()
        if not line or _COUNT_PAGE_LINE_RE.search(line):
            continue
        gm = _COUNT_GRAND_TOTAL_RE.search(line)
        if gm:
            value = int(gm.group(1))
            if 1 <= value <= 9999 and not 1900 <= value <= 2099:
                return value, rows
            continue
        if _COUNT_TABLE_ROW_RE.match(line) and _COUNT_TOTAL_WORD_RE.search(line):
            saw_subtotal = True  # "Assembly Total 57" / "Subtotal 57"
            continue
        m = _COUNT_TABLE_ROW_RE.match(line)
        if m:
            value = int(m.group(2))
            if not 1 <= value <= 999 or _COUNT_ROW_VETO_RE.search(line):
                return None, rows
            rows.append((m.group(1), value))
            continue
        if _COUNT_TRAILING_INT_RE.search(line):
            return None, rows  # count-shaped but not a parseable row
        if not rows:
            grace -= 1
            if grace < 0:
                return None, []
            continue
        resume_at = i  # benign line — the table run ended here
        break

    for line in lines[resume_at:]:
        if _COUNT_PAGE_LINE_RE.search(line):
            continue
        if _COUNT_TRAILING_INT_RE.search(line.strip()):
            return None, rows  # more count-shaped lines past the break

    # A single-row "table" is as likely a stray numbered sentence as a real
    # one-position table; require corroboration.
    if saw_subtotal or len(rows) < 2:
        return None, rows
    total = sum(v for _, v in rows)
    return (total if total <= 9999 else None), rows


def _scan_best_table(lines: list[str]) -> tuple[int | None, list[tuple[str, int]]]:
    """Count + data rows from a positions table: Grand Total row, else the sum.

    Tries each header-looking line in turn: a candidate that yields no data
    rows at all (a prose line that resembled a header) falls through to the
    next, but once a scan has read actual rows its verdict is final — a
    poisoned or ambiguous real table must not be retried against a later
    table in the same letter (per-site tables would produce a partial sum).
    """
    for start, line in enumerate(lines):
        if not _is_table_header(line):
            continue
        result, rows = _scan_table(lines, start)
        if result is not None:
            return result, rows
        if rows:
            return None, []
    return None, []


def _count_from_table(lines: list[str]) -> int | None:
    return _scan_best_table(lines)[0]


def extract_layoff_count(text: str) -> int | None:
    """Conservative affected-employee count from WARN letter text.

    Serves ``backfill-layoff-counts`` (states whose listings publish no
    count). Tiers, most explicit first:

      1. explicit totals ("a total of 73 employees", "number of employees
         affected: 4")
      2. action-adjacent counts ("will affect 205 employees", "laying off
         approximately 530 ... employees")
      3. count+noun inside a sentence mentioning the layoff action
      4. a positions table: Grand Total row, else the count-column sum

    A tier with conflicting values returns None (ambiguous — e.g. per-site
    breakdowns with no stated total); an empty tier falls through. Tables
    rank last because a multi-state letter's table spans every state while
    the prose states the in-state total ("the total number of affected
    employees in West Virginia is one").
    """
    flat = re.sub(r"\s+", " ", text)

    for tier in (_COUNT_TOTAL_RES, _COUNT_ACTION_RES):
        values: set[int] = set()
        for rx in tier:
            for m in rx.finditer(flat):
                value = _count_candidate(m, flat)
                if value is not None:
                    values.add(value)
        if values:
            return values.pop() if len(values) == 1 else None

    values = set()
    for sentence in re.split(r"(?<=[.!?])\s+", flat):
        if not _COUNT_ACTION_CUE.search(sentence):
            continue
        for m in _COUNT_NUM_NOUN_RE.finditer(sentence):
            value = _count_candidate(m, sentence)
            if value is not None:
                values.add(value)
    if values:
        return values.pop() if len(values) == 1 else None

    return _count_from_table(text.splitlines())


# Leading row enumeration ("1. Machinist 12") and stray separator characters
# around a title. The enumeration trim requires the dot/paren so "3D Printer
# Operator" keeps its "3D".
_TITLE_ENUM_RE = re.compile(r"^\d{1,3}[.)]\s+")
# Hyphen, en/em dash (U+2013/U+2014), bullet (U+2022), and column separators.
_TITLE_SEP_CLASS = r"[\s\-*:|" + chr(0x2013) + chr(0x2014) + chr(0x2022) + "]+"
_TITLE_EDGE_RE = re.compile(rf"^{_TITLE_SEP_CLASS}|{_TITLE_SEP_CLASS}$")


def _clean_row_title(raw: str) -> str:
    title = _TITLE_ENUM_RE.sub("", raw)
    return re.sub(r"\s+", " ", _TITLE_EDGE_RE.sub("", title)).strip()


def extract_occupations(text: str) -> list[tuple[str, int]]:
    """Employer-filed ``(job_title, count)`` rows from a positions table.

    The per-row sibling of tier 4 in :func:`extract_layoff_count`: many WARN
    letters carry a "Position Titles / Number Impacted" table naming the
    actual eliminated roles. Rows are trusted only when the same table scan
    yields a valid count AND the rows sum to it — a Grand Total that doesn't
    match the parsed rows means rows were missed (wrapped lines, a second
    page), so per-row data can't be trusted even though the stated total
    can. Duplicate titles (multi-site letters) are merged by summing counts,
    first-seen order preserved. Returns ``[]`` whenever the table is absent,
    poisoned, or inconsistent.
    """
    count, rows = _scan_best_table(text.splitlines())
    if count is None or not rows:
        return []
    if sum(v for _, v in rows) != count:
        return []
    merged: dict[str, tuple[str, int]] = {}  # casefolded title → (display, sum)
    for raw_title, value in rows:
        title = _clean_row_title(raw_title)
        if not title:
            return []  # a row we can't name can't be represented faithfully
        key = title.casefold()
        display, prev = merged.get(key, (title, 0))
        merged[key] = (display, prev + value)
    return list(merged.values())
