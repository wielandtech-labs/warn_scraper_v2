"""Florida WARN scraper.

Source: https://reactwarn.floridajobs.org/WarnList/Records?year={year}

Schema (live as of May 2026, unchanged since V1):
  Company Name | State Notification Date | Layoff Date | Employees Affected
    | Industry | Attachment

Per-row layout in the first <td>:
  <b>Company Name</b><br>123 Main St<br>CITY, FL, 32101
A hidden <input type="hidden" value="filename.pdf"> holds the Azure path that
gets appended to the download base URL to fetch the PDF.

Like NY and JobLink, we surface the PDF URL via `raw_notice_url` but do NOT
fetch the PDF here — per-PDF enrichment goes through Phase 4.
"""
from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

URL_TEMPLATE = "https://reactwarn.floridajobs.org/WarnList/Records?year={year}"
DOWNLOAD_BASE = "https://reactwarn.floridajobs.org/WarnList/DownloadAzureFile?file="

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    ),
    "X-Requested-With": "XMLHttpRequest",
}

_ZIP_RE = re.compile(r"(\d{5})(?:-\d{4})?\s*$")


class FLScraper:
    state = "FL"
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def __init__(self) -> None:
        self.source_url = URL_TEMPLATE.format(year=datetime.now().year)

    def fetch(self) -> bytes:
        try:
            r = httpx.get(self.source_url, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {self.source_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        table = soup.find("table", id="DataTable") or soup.find("table")
        if table is None:
            raise ParseFailed("no <table> found in FL DataTable page")

        rows: list[NoticeRow] = []
        body = table.find("tbody") or table
        for tr in body.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue

            employer = _employer_from_cell(cells[0])
            if not employer:
                continue

            notice_date = as_date(cells[1].get_text(strip=True).replace("-", "/"))
            if notice_date is None:
                # Skip header echoes / no-data placeholders
                continue

            effective_text = cells[2].get_text(strip=True)
            effective_date = _first_date(effective_text)

            city, zip_code = _city_zip_from_cell(cells[0])
            layoff_count = as_int(cells[3].get_text(strip=True))
            industry = as_str(cells[4].get_text(strip=True))

            hidden = tr.find("input", attrs={"type": "hidden"})
            raw_notice_url = (
                DOWNLOAD_BASE + hidden.get("value")
                if hidden and hidden.get("value")
                else None
            )

            rows.append(
                NoticeRow(
                    state="FL",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    city=city,
                    zip=zip_code,
                    source_url=self.source_url,
                    raw_notice_url=raw_notice_url,
                    extra={"industry": industry} if industry else {},
                )
            )
        return rows


def _employer_from_cell(cell) -> str | None:
    b = cell.find("b")
    if b is not None and b.get_text(strip=True):
        return b.get_text(strip=True)
    # Fallback: take everything before the first <br>
    text = cell.get_text(" ", strip=True)
    return as_str(text.split(",")[0])


def _city_zip_from_cell(cell) -> tuple[str | None, str | None]:
    """Parse 'ACL Roofing 99 S. McCall Rd ENGLEWOOD, FL, 34223' → ('Englewood', '34223')."""
    text = cell.get_text(" ", strip=True)
    parts = [p.strip() for p in text.split(",")]
    city: str | None = None
    zip_code: str | None = None
    if len(parts) >= 3:
        # The city is in the part before "FL"
        # parts[-3] usually ends with the city, prefixed by address tokens
        city_token = parts[-3].split()
        if city_token:
            city = " ".join(city_token[-2:]).title() if len(city_token) >= 2 else city_token[-1].title()
            # Heuristic: single-word city → just title-case; multi-word → use last 1-2 tokens
            # In practice FL data has city as the last 1 or 2 ALL-CAPS words.
            city = _extract_city(parts[-3])
    m = _ZIP_RE.search(text)
    if m:
        zip_code = m.group(1)
    return city, zip_code


def _extract_city(token: str) -> str:
    """The city is the trailing run of ALL-CAPS words in `token`."""
    words = token.split()
    city_words: list[str] = []
    for w in reversed(words):
        if w.isupper() and w.isalpha():
            city_words.append(w)
        else:
            break
    if not city_words:
        return token.strip().title()
    return " ".join(reversed(city_words)).title()


def _first_date(text: str):
    """Parse the first date from strings like '07-14-26 thru 07-14-26'."""
    if not text:
        return None
    first = text.split("thru")[0].strip().replace("-", "/")
    return as_date(first)


register(FLScraper())
