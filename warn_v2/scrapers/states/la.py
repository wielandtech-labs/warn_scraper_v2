"""Louisiana WARN scraper.

Source: https://www.laworks.net/Downloads/WFD/WarnNotices{year}.pdf (PDF).

Two layout eras (both lattice tables, one file per year):
  2026+: title banner row, then header
         Company Name | Address | Notice Date | Layoff Date |
         Employees Affected | (empty) | Industry
  2025:  no banner, header repeated on every page, and NO Address column —
         the Company Name cell holds "employer\\nstreet\\ncity, LA zip" on
         separate lines (address lines start with a street number).

parse() detects the header row (first row containing "company name") instead of
assuming fixed banner/header positions, so both eras parse. City and ZIP are
extracted from the address (format: "street, city, LA zip").

Note: URL uses www (not www2) as of 2026. Falls back to prior year on failure.
laworks.net prunes old files — only 2025+ resolve (pre-2025 → records request);
`backfill-historical --state LA` ingests the still-published years.
"""
from __future__ import annotations

import re
from datetime import date

import httpx
import pdfplumber

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_PDF_URL = "https://www.laworks.net/Downloads/WFD/WarnNotices{year}.pdf"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

_STREET_SUFFIXES = frozenset({
    "st", "street", "ave", "avenue", "blvd", "boulevard", "rd", "road",
    "dr", "drive", "ct", "court", "pkwy", "parkway", "hwy", "highway",
    "way", "ln", "lane", "pl", "place", "ter", "terrace", "cir", "circle",
    "sq", "square", "pike", "trail", "tr", "alley",
})


def _source_url(year: int) -> str:
    return _PDF_URL.format(year=year)


def _fetch_la_year(year: int) -> bytes | None:
    """Download one year's PDF for backfill-historical.

    Returns None when the file is gone — laworks.net prunes old years
    (2020-2023 verified 404 on 2026-06-12), so LA history bottoms out at
    whatever the site still serves.
    """
    url = _source_url(year)
    try:
        r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {url}: {e}") from e
    if r.status_code != 200 or b"%PDF" not in r.content[:8]:
        return None
    return r.content


class LAScraper:
    state = "LA"
    source_url = _PDF_URL.format(year=date.today().year)
    # Small dataset — typically <50 notices per year.
    expected_row_range = (1, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        year = date.today().year
        for yr in (year, year - 1):
            url = _source_url(yr)
            try:
                r = httpx.get(url, headers=_UA, timeout=60, follow_redirects=True)
                if r.status_code == 200 and b"%PDF" in r.content[:8]:
                    self.source_url = url
                    return r.content
            except httpx.HTTPError:
                pass
        raise ScrapeFailed(f"Could not fetch LA WARN PDF for {year} or {year - 1}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        return parse_la_pdf(raw, self.source_url)


def parse_la_pdf(raw: bytes, source_url: str) -> list[NoticeRow]:
    import io

    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"pdfplumber could not open LA PDF: {e}") from e

    with pdf:
        all_rows: list[list] = []
        for page in pdf.pages:
            tbl = page.extract_table(
                table_settings={
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                }
            )
            if tbl:
                all_rows.extend(tbl)

    if len(all_rows) < 2:
        raise ParseFailed(f"LA PDF: too few table rows ({len(all_rows)})")

    # Header position varies by era (2026 has a banner row above it; 2025
    # repeats it on every page) — detect it by content, skip every repeat.
    col: dict[str, int] = {}
    rows: list[NoticeRow] = []
    for raw_row in all_rows:
        header = [_norm(c).lower() for c in raw_row]
        if "company name" in header:
            if not col:
                col = {name: i for i, name in enumerate(header) if name}
            continue
        if not col:
            continue  # banner/preamble rows before the first header

        if "address" in col:
            employer = as_str(_norm(raw_row[col["company name"]]))
            address = _norm(raw_row[col["address"]])
        else:
            # 2025 era: employer + address share the Company Name cell,
            # one per line — address starts at the first street-number line.
            employer, address = _split_company_address(raw_row[col["company name"]])
        if not employer:
            continue
        notice_date = as_date(_norm(raw_row[col["notice date"]]))
        if notice_date is None:
            continue

        city, zip_code = _city_zip_la(address)

        industry_idx = col.get("industry")
        industry = (
            as_str(_norm(raw_row[industry_idx]))
            if industry_idx is not None and industry_idx < len(raw_row)
            else None
        )

        rows.append(
            NoticeRow(
                state="LA",
                employer=employer,
                notice_date=notice_date,
                effective_date=_layoff_date(raw_row[col["layoff date"]]),
                layoff_count=as_int(_norm(raw_row[col["employees affected"]])),
                city=city,
                zip=zip_code,
                address=as_str(address),
                source_url=source_url,
                extra={"industry": industry or ""},
            )
        )
    if not col:
        raise ParseFailed("LA PDF: no header row with 'Company Name' found")
    return rows


def _layoff_date(cell) -> date | None:
    """Parse a Layoff Date cell; ranges like '7/31/25 to 12/31/25' use the start."""
    text = _norm(cell)
    parsed = as_date(text)
    if parsed is None and " to " in text:
        parsed = as_date(text.split(" to ", 1)[0])
    return parsed


_ADDRESS_LINE_RE = re.compile(r"^\(?\d")


def _split_company_address(cell) -> tuple[str | None, str]:
    """Split a merged 'employer\\nstreet\\ncity, LA zip' cell (2025 era).

    Lines up to the first one that starts with a street number (optionally
    parenthesised) are the employer; that line onward is the address. Some
    notices carry no address lines at all.
    """
    lines = [ln.strip() for ln in str(cell or "").splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if i > 0 and _ADDRESS_LINE_RE.match(line):
            return (
                as_str(" ".join(lines[:i])),
                " ".join(" ".join(lines[i:]).split()),
            )
    return as_str(" ".join(lines)), ""


def _norm(cell) -> str:
    """Collapse multi-line cell text (pdfplumber uses \\n for wrapped lines)."""
    if cell is None:
        return ""
    return " ".join(str(cell).replace("\n", " ").split())


def _city_zip_la(address: str) -> tuple[str | None, str | None]:
    """Extract city + ZIP from a Louisiana mailing address.

    Examples:
    - '601 Poydras Street, Suite 1200 New Orleans, LA 70130' → ('New Orleans', '70130')
    - '330 Belden Street Lake Charles, LA 70601'             → ('Lake Charles', '70601')
    - '560 Highway 44 LaPlace, LA 70068'                     → ('LaPlace', '70068')
    """
    if not address:
        return None, None
    # Last match, not first — 5-digit street numbers ("13800 Old Gentilly Rd")
    # would otherwise shadow the real ZIP at the end of the address.
    zip_matches = _ZIP_RE.findall(address)
    zip_code = zip_matches[-1] if zip_matches else None

    la_idx = address.lower().find(", la")
    if la_idx == -1:
        return None, zip_code
    prefix = address[:la_idx].rstrip()
    # Prefer the chunk after the last comma.
    candidate = prefix.rsplit(",", 1)[-1].strip()
    # Walk backwards: collect capitalized alpha words; stop at a number or a
    # street suffix that already has city tokens after it.
    city_tokens: list[str] = []
    for token in reversed(candidate.split()):
        bare = token.strip(".,").lower()
        if not bare or not bare.isalpha():
            break
        if bare in _STREET_SUFFIXES and city_tokens:
            break
        city_tokens.insert(0, token)
        if bare in _STREET_SUFFIXES:
            city_tokens.clear()
            break
    city = " ".join(city_tokens) if city_tokens else None
    return as_str(city), zip_code


register(LAScraper())
