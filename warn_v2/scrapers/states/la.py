"""Louisiana WARN scraper.

Source: https://www.laworks.net/Downloads/WFD/WarnNotices{year}.pdf (PDF).

Two layout eras (both lattice tables, one file per year):
  2026+:     title banner row, then header
             Company Name | Address | Notice Date | Layoff Date |
             Employees Affected | (empty) | Industry
  2007-2025: no banner, header repeated on every page, and NO Address column —
             the Company Name cell holds "employer\\nstreet\\ncity, LA zip" on
             separate lines (address lines start with a street number).

parse() detects the header row (first row containing "company name") instead of
assuming fixed banner/header positions, so both eras parse. Header cells are
matched on alpha-only keys because many archive years (2010, 2012-2021) carry
inter-letter spacing artifacts ("E m p loyees Affected"). City and ZIP are
extracted from the address (format: "street, city, LA zip").

Note: URL uses www (not www2) as of 2026. Falls back to prior year on failure.
laworks.net prunes old files — only 2025+ resolve live (2020-2023 verified 404
on 2026-06-12); `backfill-historical --state LA` fetches 2007-2024 from pinned
Wayback captures of the same per-year URLs (see _WAYBACK_TS).
"""
from __future__ import annotations

import re
from datetime import date

import httpx
import pdfplumber

from warn_v2.scrapers import wayback
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


# Latest Wayback capture of each pruned per-year PDF (2026-07 sweep). All are
# post-year (full-year) captures except 2024, captured 2024-08-12 — Sep-Dec
# 2024 is published nowhere (the live file was pruned before year end).
_WAYBACK_TS: dict[int, str] = {
    2007: "20231011195653",
    2008: "20231011195656",
    2009: "20231011195824",
    2010: "20231011195828",
    2011: "20231011195701",
    2012: "20231011190356",
    2013: "20231011195703",
    2014: "20231011190400",
    2015: "20231011190402",
    2016: "20231011190405",
    2017: "20231011195704",
    2018: "20231011195731",
    2019: "20231011195709",
    2020: "20231011195653",
    2021: "20231011195737",
    2022: "20231011190409",
    2023: "20240513101539",
    2024: "20240812071345",
}


def _live_url(year: int) -> str:
    return _PDF_URL.format(year=year)


def _source_url(year: int) -> str:
    """Row-provenance URL for one year: the live laworks.net file for years
    the site still serves, the pinned Wayback replay for pruned 2007-2024."""
    ts = _WAYBACK_TS.get(year)
    url = _live_url(year)
    return wayback.replay_url(ts, url) if ts else url


def _fetch_la_year(year: int) -> bytes | None:
    """Download one year's PDF for backfill-historical.

    laworks.net prunes old years (2020-2023 verified 404 on 2026-06-12), so
    2007-2024 fetch straight from the pinned Wayback captures — deterministic,
    and the bytes then match the replay source_url the rows carry. 2025+ stays
    live; None means the year is unavailable.
    """
    ts = _WAYBACK_TS.get(year)
    if ts:
        raw = wayback.fetch(wayback.replay_url(ts, _live_url(year)))
        if raw is not None and b"%PDF" not in raw[:8]:
            raise ScrapeFailed(f"LA {year}: Wayback capture {ts} is not a PDF")
        return raw
    url = _live_url(year)
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
            url = _live_url(yr)
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

    # Header position varies by era (2026 has a banner row above it; earlier
    # years repeat it on every page) — detect it by content, skip every
    # repeat. Keys are alpha-only because many archive years render the header
    # with inter-letter spaces ("E m p loyees Affected").
    col: dict[str, int] = {}
    rows: list[NoticeRow] = []
    for raw_row in all_rows:
        header = [_header_key(c) for c in raw_row]
        if "companyname" in header:
            if not col:
                col = {name: i for i, name in enumerate(header) if name}
            continue
        if not col:
            continue  # banner/preamble rows before the first header

        if "address" in col:
            employer = as_str(_norm(raw_row[col["companyname"]]))
            address = _norm(raw_row[col["address"]])
        else:
            # 2007-2025 era: employer + address share the Company Name cell,
            # one per line — address starts at the first street-number line.
            employer, address = _split_company_address(raw_row[col["companyname"]])
        if not employer:
            continue
        notice_cell = _norm(raw_row[col["noticedate"]])
        notice_date = as_date(notice_cell) or _first_date(notice_cell)
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
                effective_date=_layoff_date(raw_row[col["layoffdate"]]),
                layoff_count=_employee_count(raw_row[col["employeesaffected"]]),
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


def _header_key(cell) -> str:
    """Alpha-only header key: 'E m p loyees\\nAffected' → 'employeesaffected'."""
    return re.sub(r"[^a-z]", "", str(cell or "").lower())


_DATE_TOKEN_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def _first_date(cell) -> date | None:
    """Parse a date cell that isn't a lone date.

    Archive files pile amendments into one cell — notice dates like
    '5/1/20 6/4/20' (original + UPDATE dates) or '4/10/23 (Updated 7/12/23)',
    layoff dates like '7/31/25 to 12/31/25', en-dash ranges (2024) or
    '6/26/15- 7/10/2015 8/7/2015'. The first date is the original filing /
    range start, so take the first token that parses.
    """
    for token in _DATE_TOKEN_RE.findall(_norm(cell)):
        parsed = as_date(token)
        if parsed is not None:
            return parsed
    return None


def _layoff_date(cell) -> date | None:
    """Parse a Layoff Date cell; ranges and amended cells use the first date."""
    text = _norm(cell)
    parsed = as_date(text)
    if parsed is None:
        parsed = _first_date(text)
    return parsed


_COUNT_RE = re.compile(r"\d[\d,]*")


def _employee_count(cell) -> int | None:
    """Parse an Employees Affected cell.

    Archive years annotate counts in-cell — '125* *Only one employee
    affected in Louisiana', '1 (Louisiana)', or amended '114 +112' — so fall
    back to the first number (the originally noticed count) when the whole
    cell isn't one.
    """
    text = _norm(cell)
    count = as_int(text)
    if count is None:
        m = _COUNT_RE.search(text)
        count = as_int(m.group()) if m else None
    return count


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
