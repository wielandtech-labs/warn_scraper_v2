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
"""
from __future__ import annotations

import re

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
        table = soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found on MD WARN page")

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

        rows: list[NoticeRow] = []
        for tr in all_trs[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) < len(header_cells):
                continue
            employer = as_str(_text(cells[col["company"]]))
            if not employer:
                continue
            notice_date = as_date(_text(cells[col["notice date"]]))
            if notice_date is None:
                continue

            location_text = _text(cells[col["location"]])
            city, zip_code = _city_zip(location_text)

            rows.append(
                NoticeRow(
                    state="MD",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_text(cells[col["effective date"]])),
                    layoff_count=as_int(_text(cells[col["total employees"]])),
                    closure_type=as_str(_text(cells[col["type"]])),
                    city=city,
                    county=as_str(_text(cells[col["local area"]])),
                    zip=zip_code,
                    address=as_str(location_text),
                    source_url=SOURCE_URL,
                    extra={"naics": as_str(_text(cells[col["naics code"]])) or ""},
                )
            )
        return rows


def _text(cell) -> str:
    """Collapse multi-line cell text into single-spaced text."""
    return " ".join(cell.get_text(" ", strip=True).split())


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
