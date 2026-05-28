"""Louisiana WARN scraper.

Source: https://www.laworks.net/Downloads/WFD/WarnNotices{year}.pdf (PDF).

Schema (live as of May 2026):
  Company Name | Address | Notice Date | Layoff Date | Employees Affected | (empty) | Industry

The PDF has a single page with a single lattice table. Row 0 is a title banner,
row 1 is the header, rows 2+ are data. City and ZIP are extracted from the
Address column (format: "street, city, LA zip").

Note: URL uses www (not www2) as of 2026. Falls back to prior year on failure.
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

        # Row 0 is a title banner, row 1 is the header.
        header = [_norm(c).lower() for c in all_rows[1]]
        col = {name: i for i, name in enumerate(header) if name}
        if "company name" not in col:
            raise ParseFailed(f"LA PDF: unexpected header: {header[:6]}")

        rows: list[NoticeRow] = []
        for raw_row in all_rows[2:]:
            employer_raw = raw_row[col.get("company name", 0)]
            employer = as_str(_norm(employer_raw))
            if not employer:
                continue
            notice_date = as_date(_norm(raw_row[col.get("notice date", 2)]))
            if notice_date is None:
                continue

            address = _norm(raw_row[col.get("address", 1)])
            city, zip_code = _city_zip_la(address)

            industry_idx = col.get("industry", 6)
            industry = as_str(_norm(raw_row[industry_idx])) if industry_idx < len(raw_row) else None

            rows.append(
                NoticeRow(
                    state="LA",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(_norm(raw_row[col.get("layoff date", 3)])),
                    layoff_count=as_int(_norm(raw_row[col.get("employees affected", 4)])),
                    city=city,
                    zip=zip_code,
                    address=as_str(address),
                    source_url=self.source_url,
                    extra={"industry": industry or ""},
                )
            )
        return rows


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
    zip_match = _ZIP_RE.search(address)
    zip_code = zip_match.group(1) if zip_match else None

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
