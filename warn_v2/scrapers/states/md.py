"""Maryland WARN scraper.

Source: https://www.dllr.state.md.us/employment/warn.shtml (HTML, one table).

Schema (live as of May 2026):
  Notice Date | NAICS Code | Company | Location | Local Area | Total Employees |
  Effective Date | Type

Location cells contain a multi-line address like:
    4527
    Metropolitan Ct
    Frederick, MD
    21704
We extract city and ZIP from the "City, MD ZIP" trailing portion.

Historical year pages (warn2000.shtml-warn2009.shtml) survive only in the
Wayback Machine; they wrap the data table in banner/legend tables, put a bare
city name in Location, use numeric Type Codes (1 = Plant Closure, 2 = Mass
Layoff per the on-page legend), and carry 4-digit SIC codes in the "NAICS
Code" column through ~2005.
"""
from __future__ import annotations

import re
import time

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://www.dllr.state.md.us/employment/warn.shtml"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

# Street-type suffixes that should NOT be part of the city name.
_STREET_SUFFIXES = frozenset({
    "st", "street", "ave", "avenue", "blvd", "boulevard", "rd", "road",
    "dr", "drive", "ct", "court", "pkwy", "parkway", "hwy", "highway",
    "way", "ln", "lane", "pl", "place", "ter", "terrace", "cir", "circle",
    "sq", "square", "pike", "trail", "tr", "alley",
})


class MDScraper:
    state = "MD"
    source_url = SOURCE_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(SOURCE_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {SOURCE_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        # 2000-2009 archive pages wrap the data table in banner/legend tables,
        # so pick the first table whose header row mentions "company".
        table = None
        for candidate in soup.find_all("table"):
            tr = candidate.find("tr")
            if tr and any(
                "company" in _text(c).lower() for c in tr.find_all(["td", "th"])
            ):
                table = candidate
                break
        if table is None:
            raise ParseFailed("no WARN data <table> found on MD page")

        all_trs = table.find_all("tr")
        if not all_trs:
            raise ParseFailed("MD table has no rows")

        # The header row uses <td> cells (not <th>) on this page; detect it by content.
        # Normalize each cell: replace \xa0 with space, collapse whitespace, lowercase.
        header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
        if not header_cells or "company" not in header_cells:
            raise ParseFailed(
                f"unexpected MD table header: {header_cells[:6]}"
            )
        col = {name: i for i, name in enumerate(header_cells)}

        def _idx(*names: str) -> int | None:
            """First matching column index; archive pages (2010+) use older
            header names ('type code' for 'type', 'wia code' for 'local area')."""
            return next((col[n] for n in names if n in col), None)

        i_company = _idx("company")
        i_notice = _idx("notice date")
        if i_company is None or i_notice is None:
            raise ParseFailed(f"MD table missing required columns: {header_cells}")
        i_location = _idx("location")
        i_effective = _idx("effective date")
        i_count = _idx("total employees")
        i_type = _idx("type", "type code")
        i_area = _idx("local area")
        i_naics = _idx("naics code")

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue

            def _cell(i: int | None, _cells=cells) -> str:
                return _text(_cells[i]) if i is not None and i < len(_cells) else ""

            employer = as_str(_cell(i_company))
            if not employer:
                continue
            notice_date = _md_date(_cell(i_notice))
            if notice_date is None:
                continue

            location_text = _cell(i_location)
            city, zip_code = _city_zip(location_text)

            industry_code = as_str(_cell(i_naics)) or ""
            # Through mid-2005 the "NAICS Code" column actually held 4-digit
            # SIC codes; from 2006 a 4-digit value is a NAICS industry group.
            extra = (
                {"sic_code": industry_code}
                if industry_code.isdigit()
                and len(industry_code) == 4
                and notice_date.year <= 2005
                else {"naics": industry_code}
            )

            rows.append(
                NoticeRow(
                    state="MD",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_cell(i_effective)),
                    layoff_count=as_int(_cell(i_count)),
                    closure_type=_closure_type(_cell(i_type)),
                    city=city,
                    county=as_str(_cell(i_area)),
                    zip=zip_code,
                    address=as_str(location_text),
                    source_url=SOURCE_URL,
                    extra=extra,
                )
            )
        return rows


# 2000-2009 pages were pruned from dllr.state.md.us; these are the latest
# complete Wayback captures per year (verified 2026-07-10, all post-year).
_MD_WAYBACK_TS = {
    2000: "20160825213318",
    2001: "20160825213317",
    2002: "20160825213316",
    2003: "20160825213315",
    2004: "20160825213314",
    2005: "20160825192616",
    2006: "20160825192615",
    2007: "20160825192614",
    2008: "20160825192613",
    2009: "20160825192612",
}
_MD_WAYBACK_DELAY = 3  # seconds between Wayback fetches
_MD_WAYBACK_BACKOFF = 30


def _md_year_url(year: int) -> str:
    """Live URL for 2010+; pinned Wayback `id_` replay URL for 2000-2009."""
    live = f"https://www.dllr.state.md.us/employment/warn{year}.shtml"
    ts = _MD_WAYBACK_TS.get(year)
    if ts is None:
        return live
    return f"https://web.archive.org/web/{ts}id_/{live}"


def _fetch_md_year(year: int) -> bytes | None:
    """Fetch one archived per-year MD WARN page; None when the year has no page.

    2010+ pages live at warn{year}.shtml on dllr.state.md.us; 2000-2009 were
    pruned and come from pinned Wayback captures instead. The current year is
    warn.shtml and is covered by the regular scraper.
    """
    url = _md_year_url(year)
    wayback = "web.archive.org" in url
    for attempt in (1, 2):
        if wayback:
            time.sleep(_MD_WAYBACK_DELAY)
        try:
            r = httpx.get(url, headers=_UA, timeout=120, follow_redirects=True)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            if wayback and attempt == 1:
                time.sleep(_MD_WAYBACK_BACKOFF)
                continue
            raise ScrapeFailed(f"GET {url}: {e}") from e
    return None  # unreachable; keeps type-checkers happy


def _text(cell) -> str:
    """Collapse multi-line cell text into single-spaced text."""
    return " ".join(cell.get_text(" ", strip=True).split())


def _md_date(cell_text: str):
    """as_date plus a repair for the archive pages' 3-digit-year typos
    (e.g. '11/26/003' for 11/26/2003)."""
    d = as_date(cell_text)
    if d is not None:
        return d
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/0*(\d{2})", cell_text.strip())
    if m:
        return as_date(f"{m.group(1)}/{m.group(2)}/{m.group(3)}")
    return None


# On-page legend of the 2000-2009 archive pages: "Type Code: 1 - Plant
# Closure, 2 - Mass Layoff". Later pages spell the type out.
_MD_TYPE_CODES = {"1": "Plant Closure", "2": "Mass Layoff"}


def _closure_type(cell_text: str) -> str | None:
    text = as_str(cell_text)
    if not text:
        return None
    return _MD_TYPE_CODES.get(text.strip().rstrip("*"), text)


def _city_zip(location: str) -> tuple[str | None, str | None]:
    """Extract city + 5-digit zip from a Maryland mailing address.

    Examples handled:
    - '4527 Metropolitan Ct Frederick, MD 21704'        → ('Frederick', '21704')
    - '7125 Troy Hill Dr, Elkridge, MD 21075'           → ('Elkridge', '21075')
    - '3201 Hubbard Road Landover, MD 20785'            → ('Landover', '20785')
    - '8201 Corporate Dr, Hyattsville, MD 20785'        → ('Hyattsville', '20785')
    """
    if not location:
        return None, None
    zip_match = _ZIP_RE.search(location)
    zip_code = zip_match.group(1) if zip_match else None

    # Find the chunk before ", MD" — that contains the city plus any leading
    # address tokens.
    md_idx = location.lower().find(", md")
    if md_idx == -1:
        # 2000-2009 archive pages put a bare city name in Location
        # (e.g. "ELDERSBURG", "Havre de Grace") — no street, state, or ZIP.
        stripped = location.strip()
        if stripped and not any(ch.isdigit() for ch in stripped) and "," not in stripped:
            return stripped, zip_code
        return None, zip_code
    prefix = location[:md_idx]
    # Prefer the chunk after the last comma (street, city, MD ZIP).
    candidate = prefix.rsplit(",", 1)[-1].strip()
    # Walk the tokens backward, keeping capitalized words until we hit a street
    # suffix or a number — those mark the boundary back into the street address.
    city_tokens: list[str] = []
    for token in reversed(candidate.split()):
        bare = token.strip(".,").lower()
        if not bare or not bare.isalpha():
            break
        if bare in _STREET_SUFFIXES and city_tokens:
            break
        if not token[0].isupper():
            break
        city_tokens.insert(0, token)
        if bare in _STREET_SUFFIXES:
            # Loop saw something like "Avenue" before any city tokens —
            # there's nothing useful here.
            city_tokens.clear()
            break
    city = " ".join(city_tokens) if city_tokens else None
    return city, zip_code


register(MDScraper())
