"""West Virginia WARN scraper.

Source: https://workforcewv.org/job-seeker/layoffs-downsizing/warn-listing/
Administered by WorkForce West Virginia.

The listing page is Cloudflare-protected so Playwright (headless Chromium) is used
to bypass the JS challenge and render the page.

Each WARN notice is published as a separate PDF download.  The listing page shows
every notice as a hyperlink whose anchor text encodes the company name and filing
date — no structured table exists and individual PDFs are not downloaded.

Anchor-text date patterns:
  "Company Name WARN M-D-YY[YY]"         (most common)
  "Company Name M-D-YY[YY]"              (no WARN keyword)
  "Company_WARN_State_Notice_MM_D_YYYY"  (underscore-separated filename)
  "Company Name 1-21-22 WARN"            (date before keyword)

Only employer name and notice date are reliably available from the listing page.
No city, county, or worker count is captured without downloading individual PDFs.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import fitz
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed
from warn_v2.scrapers.bundled import load_archive
from warn_v2.scrapers.playwright_base import PlaywrightScraper
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://workforcewv.org/job-seeker/layoffs-downsizing/warn-listing/"
_BASE_URL = "https://workforcewv.org"

# Matches M-D-YY, M-D-YYYY, M_D_YYYY (underscore variant in filenames)
_DATE_RE = re.compile(r"\d{1,2}[-_]\d{1,2}[-_]\d{2,4}")

# Keywords that appear in anchor text but are not part of the employer name
_NOISE_RE = re.compile(
    r"\b(WARN|State\s+Notice|r\d+|Notice|Received|Update|Download|PDF)\b",
    re.IGNORECASE,
)


class WVScraper(PlaywrightScraper):
    state = "WV"
    source_url = SOURCE_URL
    expected_row_range = (5, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def _navigate(self, page) -> None:  # type: ignore[override]
        """Navigate to the WARN listing page and wait for PDF links to appear."""
        page.goto(SOURCE_URL, wait_until="load", timeout=60_000)
        # Allow Cloudflare challenge to resolve and content to fully render
        try:
            page.wait_for_selector("a[href*='.pdf']", timeout=20_000)
        except Exception:
            pass  # Proceed even if selector times out; parse() will catch empty results

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        pdf_links = [
            (a.get_text(strip=True), a.get("href", ""))
            for a in soup.find_all("a", href=True)
            if ".pdf" in a.get("href", "").lower()
        ]
        if not pdf_links:
            raise ParseFailed("WV: no PDF links found on WARN listing page")

        rows: list[NoticeRow] = []
        for text, href in pdf_links:
            row = _parse_notice_link(text, href)
            if row is not None:
                rows.append(row)

        if not rows:
            raise ParseFailed("WV: no parseable WARN notice links found")
        return rows


def _parse_notice_link(text: str, href: str) -> NoticeRow | None:
    """Parse one PDF anchor text into a NoticeRow, or return None if unparseable."""
    m = _DATE_RE.search(text)
    if not m:
        return None  # No date in anchor text — skip

    # Replace underscores (from filename-style links) so as_date can parse
    date_str = m.group().replace("_", "/")
    notice_date = as_date(date_str)
    if notice_date is None:
        return None

    # Employer: text preceding the date match, with noise words stripped
    prefix = text[: m.start()].replace("_", " ")
    employer = _NOISE_RE.sub("", prefix).strip(" -,_")
    employer = as_str(" ".join(employer.split()))
    if not employer:
        return None

    raw_notice_url = href if href.startswith("http") else _BASE_URL + href

    return NoticeRow(
        state="WV",
        employer=employer,
        notice_date=notice_date,
        raw_notice_url=raw_notice_url,
        source_url=SOURCE_URL,
    )


register(WVScraper())


# ---------------------------------------------------------------------------
# Historical backfill (bundled Mode 3b): the 2011-2021 cumulative notice log
# ---------------------------------------------------------------------------
# workforcewv.org used to publish one cumulative PDF log of every WARN notice
# (one block of labeled fields per notice, newest first). The last edition —
# ``WV_WARN_Notices_3-1-11_to_6-7-21.pdf``, Mar 2011 → Jun 2021, 137 pages —
# survives only as a Wayback capture that the crawler truncated at exactly
# 1 MiB. The raw capture is bundled as-is in ``wv_archive.tar.gz`` and
# ingested via ``backfill-historical --state WV``.
#
# The truncation costs the embedded font programs (so pdfplumber can't open
# the file, and PyMuPDF's regular ``get_text()`` sees zero-width glyphs and
# collapses repeated characters: "Mass Layoff" -> "Mas Layof", "3/1/11" ->
# "3/1/1" — digits too). The page tree and every page's content stream are
# intact, so ``parse_wv_archive_pdf`` recovers exact text by walking the
# content streams directly: Tm positions each run, Tf tracks the font (for
# width estimates used to re-join kerned fragments), and TJ/Tj carry the
# string bytes (WinAnsi literals, plus CID hex strings for the one embedded
# Type0 font Word used for curly apostrophes).

_ARCHIVE_TGZ = Path(__file__).resolve().parent.parent / "data" / "wv_archive.tar.gz"


def wv_archive_files() -> list[tuple[str, bytes]]:
    """(member_name, bytes) for the bundled WV historical snapshot."""
    return load_archive(_ARCHIVE_TGZ)


# --- content-stream text recovery ------------------------------------------

_TM_RE = re.compile(
    rb"(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+"
    rb"(-?[\d.]+)\s+(-?[\d.]+)\s+Tm"
)
_TF_RE = re.compile(rb"/(\w+)\s+([\d.]+)\s+Tf")
_PDF_STR = rb"\((?:[^()\\]|\\.)*\)|<[0-9A-Fa-f\s]+>"
_SHOW_RE = re.compile(
    rb"\[(?:" + _PDF_STR + rb"|[^\[\]()<>])*\]\s*TJ|(?:" + _PDF_STR + rb")\s*Tj",
    re.DOTALL,
)
_STR_RE = re.compile(rb"\(((?:[^()\\]|\\.)*)\)|<([0-9A-Fa-f\s]+)>", re.DOTALL)

_ESC = {
    b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f",
    b"(": b"(", b")": b")", b"\\": b"\\",
}


def _decode_pdf_string(s: bytes) -> str:
    """Decode a PDF literal string (WinAnsi bytes with backslash escapes)."""
    out = bytearray()
    i = 0
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\":
            nxt = s[i + 1:i + 2]
            if nxt in b"01234567":
                j = i + 1
                digits = b""
                while j < len(s) and len(digits) < 3 and s[j:j + 1] in b"01234567":
                    digits += s[j:j + 1]
                    j += 1
                out.append(int(digits, 8) & 0xFF)
                i = j
                continue
            out += _ESC.get(nxt, nxt)
            i += 2
            continue
        out += c
        i += 1
    return out.decode("cp1252", errors="replace")


def _decode_hex_string(s: bytes) -> str:
    """Decode a ``<...>`` CID hex string from the doc's embedded Type0 font.

    Word switches to an embedded-subset Type0 font for strings containing
    curly apostrophes; its ToUnicode CMap is lost to the truncation, but the
    subset keeps TrueType glyph order, where GID 3 is space and GIDs 4-0x5E
    are ASCII 0x21-0x7E in order (char = GID + 0x1D). Verified against every
    hex run in the bundled file ("Bloomin' Brands", "Eat'n Park",
    "Ammar's Inc.", "Cliff's Logan County Coal, LLC", ...).
    """
    hexdigits = re.sub(rb"\s", b"", s)
    out = ""
    for i in range(0, len(hexdigits) - 3, 4):
        gid = int(hexdigits[i:i + 4], 16)
        if gid == 0x03:
            out += " "
        elif 0x04 <= gid <= 0x5E:
            out += chr(gid + 0x1D)
        elif gid == 0xB1:
            out += "-"
        elif gid == 0xB6:
            out += "\u2019"  # right single quote
    return out


def _builtin_font(basefont: str) -> str:
    """Map a document font to the metrically closest PyMuPDF builtin."""
    bold = "Bold" in basefont or "Black" in basefont
    if "Times" in basefont:
        return "tibo" if bold else "tiro"
    return "hebo" if bold else "helv"


def _page_runs(cont: bytes, fonts: dict[str, str]):
    """(x, y, text, est_width) for every text run, positioned by the last Tm."""
    events: list[tuple[int, str, object]] = []
    for m in _TM_RE.finditer(cont):
        events.append((m.start(), "tm", (float(m.group(5)), float(m.group(6)))))
    for m in _TF_RE.finditer(cont):
        events.append(
            (m.start(), "tf", (m.group(1).decode("ascii"), float(m.group(2))))
        )
    for m in _SHOW_RE.finditer(cont):
        txt = "".join(
            _decode_pdf_string(lit) if lit else _decode_hex_string(hx)
            for lit, hx in _STR_RE.findall(m.group(0))
        )
        events.append((m.start(), "show", txt))
    events.sort(key=lambda e: e[0])
    pos = (0.0, 0.0)
    fontname, size = "helv", 12.0
    for _, kind, payload in events:
        if kind == "tm":
            pos = payload
        elif kind == "tf":
            fontname, size = fonts.get(payload[0], "helv"), payload[1]
        elif payload.strip():
            width = fitz.get_text_length(payload, fontname=fontname, fontsize=size)
            yield pos[0], pos[1], payload, width


def _join_runs(runs: list[tuple[float, str, float]]) -> str:
    """Join x-sorted (x, text, width) runs, inserting spaces only at real gaps.

    Word emits kerned fragments as separate runs ("M"+"arch", "740"+"-"+"338");
    a run whose x starts within ~2pt of the previous run's estimated end is a
    continuation of the same word.
    """
    out = ""
    end_x: float | None = None
    for x, text, width in runs:
        if end_x is not None and x - end_x > 2.0 and not out.endswith(" "):
            out += " "
        out += text
        end_x = x + width
    return " ".join(out.split())


def _page_lines(cont: bytes, fonts: dict[str, str], y_tol: float = 2.5):
    """Body lines (top->bottom) as (label_text, value_text) column pairs.

    The notice log is a two-column table: field labels sit left of x=200 and
    values right of it; page header/footer furniture lives outside y 102-710.
    """
    lines: list[list] = []  # [y, [(x, text, width), ...]]
    for x, y, t, w in _page_runs(cont, fonts):
        if y >= 710 or y <= 102:
            continue
        for line in lines:
            if abs(line[0] - y) < y_tol:
                line[1].append((x, t, w))
                break
        else:
            lines.append([y, [(x, t, w)]])
    lines.sort(key=lambda ln: -ln[0])
    out = []
    for _, runs in lines:
        runs.sort(key=lambda r: r[0])
        label = _join_runs([r for r in runs if r[0] < 200])
        value = _join_runs([r for r in runs if r[0] >= 200])
        out.append((label, value))
    return out


# --- notice-block parsing ---------------------------------------------------

_ARCHIVE_LABELS = {
    "company": "company",
    "company & facilities": "company",  # one 2012 block uses this variant
    "address": "address",
    "contact information": "contact",
    "contact": "contact",  # label cell wrapped over two lines
    "information": "contact",
    "region": "region",
    "county": "county",
    "date of notice": "notice_date",
    "projected date": "effective_date",
    "closure/mass layoff": "closure",
    "closure/mass": "closure",  # label cell wrapped over two lines
    "layoff": "closure",
    "number affected": "count",
}

_DATE_ANY_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
# Annotation lines between blocks, tagging the next notice as a revision of an
# earlier one ("Update to Previous Notice 1/3/14", "Extension of Mass Layoff
# Date - 5/4/12", "Postponement of 6/26/20 Notice", ...).
_ANNOT_RE = re.compile(
    r"\b(update to|extension of|postponement of|supplement to)\b", re.IGNORECASE
)
_MONTH_HDR_RE = re.compile(
    r"^(january|february|march|april|may|june|july|august|september|october|"
    r"november|december)20\d\d$"
)
# "City, WV 25414" / "City, WV" at the start of an address line. Out-of-state
# HQ addresses (e.g. "St. Louis, MO 63042") deliberately don't match — the
# county field carries the WV location for those rows.
_CITY_WV_RE = re.compile(r"^([A-Za-z .'\-]+?)\s*,\s*WV\b\s*,?\s*(\d{5})?")
# Same but the state was omitted in the source ("Martinsburg, 25401") —
# accept only WV-plausible ZIPs (247xx-268xx).
_CITY_ZIP_RE = re.compile(r"^([A-Za-z .'\-]+?)\s*,\s*((?:24[7-9]|2[56]\d)\d\d)\b")
_COUNT_RE = re.compile(r"\d[\d,]*")


def parse_wv_archive_pdf(raw: bytes) -> list[NoticeRow]:
    """Parse the bundled cumulative notice log (see module comment above)."""
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception as e:
        raise ParseFailed(f"WV archive: fitz could not open PDF: {e}") from e

    rows: list[NoticeRow] = []
    block: dict[str, list[str]] = {}
    field: str | None = None

    def flush() -> None:
        nonlocal block
        if block:
            row = _block_to_row(block)
            if row is not None:
                rows.append(row)
        block = {}

    for pno in range(doc.page_count):
        fonts = {
            name: _builtin_font(basefont)
            for _, _, _, basefont, name, _ in doc.get_page_fonts(pno)
        }
        try:
            cont = doc[pno].read_contents()
        except Exception as e:
            raise ParseFailed(f"WV archive: unreadable page {pno + 1}: {e}") from e
        for label, value in _page_lines(cont, fonts):
            key = _ARCHIVE_LABELS.get(label.lower()) if label else None
            if key == "company":
                flush()
            if key is not None:
                field = key
                if value:
                    block.setdefault(field, []).append(value)
                continue
            if label:
                continue  # unknown label-column text — page furniture
            if _MONTH_HDR_RE.match(re.sub(r"[\s,]", "", value).lower()):
                continue  # month section header between blocks
            if _ANNOT_RE.search(value):
                field = None  # inter-block annotation line — ends any open field
                continue
            if field is not None and value:
                block.setdefault(field, []).append(value)

    flush()
    if not rows:
        raise ParseFailed("WV archive: no notice blocks parsed")
    return rows


def _first_date(text: str) -> date | None:
    m = _DATE_ANY_RE.search(re.sub(r"\s", "", text))
    return as_date(m.group()) if m else None


def _block_to_row(block: dict[str, list[str]]) -> NoticeRow | None:
    employer = as_str(" ".join(block.get("company", [])))
    if not employer:
        return None
    notice_date = _first_date(" ".join(block.get("notice_date", [])))
    if notice_date is None:
        return None

    closure = as_str(" ".join(block.get("closure", [])))
    count_text = re.sub(r"\s", "", " ".join(block.get("count", [])))
    # A few source blocks have the two cells swapped ("541" under
    # Closure/Mass Layoff, "Mass Layoff" under Number Affected) — repair.
    if closure and closure.replace(",", "").isdigit() and not _COUNT_RE.search(count_text):
        closure, count_text = " ".join(block.get("count", [])).strip() or None, closure

    # Multi-site notices list one count per site plus a "Total 145" line —
    # prefer the total; otherwise the first number in the cell.
    count = None
    m = re.search(r"total:?([\d,]+)", count_text, re.IGNORECASE) or _COUNT_RE.search(count_text)
    if m:
        count = as_int(m.group(1) if m.lastindex else m.group())

    city = zip_code = None
    for line in block.get("address", []):
        m = _CITY_WV_RE.match(line) or _CITY_ZIP_RE.match(line)
        if m:
            city, zip_code = m.group(1).strip(), m.group(2)
            break

    return NoticeRow(
        state="WV",
        employer=employer,
        notice_date=notice_date,
        effective_date=_first_date(" ".join(block.get("effective_date", []))),
        layoff_count=count,
        closure_type=closure,
        city=city,
        county=as_str(" ".join(block.get("county", []))),
        zip=zip_code,
        address=as_str(" ".join(block.get("address", []))),
        source_url=SOURCE_URL,
    )
