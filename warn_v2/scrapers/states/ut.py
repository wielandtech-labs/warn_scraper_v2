"""Utah WARN scraper.

Source: https://jobs.utah.gov/employer/business/warnnotices.html

Schema (live as of May 2026):
  Date of Notice | Company Name | Location | Affected Workers

Static HTML page holding one table per year back to 2009 (~275 rows total);
no PDF links per row. Older sections carry occasional hand-typed date typos
('08/31//2022', '03/09/2020&', '09/31/10') — repaired in ``_ut_date``.
"""
from __future__ import annotations

import calendar
import re

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://jobs.utah.gov/employer/business/warnnotices.html"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class UTScraper:
    state = "UT"
    source_url = SOURCE_URL
    expected_row_range = (5, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(SOURCE_URL, headers=_UA, timeout=30, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {SOURCE_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        # One table per year back to 2009 — parse every section that carries
        # the WARN header (the page holds the full history, not just the
        # current year).
        tables = [
            t
            for t in soup.find_all("table")
            if (tr := t.find("tr"))
            and any("company name" in _text(c).lower() for c in tr.find_all(["td", "th"]))
        ]
        if not tables:
            raise ParseFailed("no WARN data <table> found on UT page")

        rows: list[NoticeRow] = []
        for table in tables:
            all_trs = table.find_all("tr")
            header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
            col = {name: i for i, name in enumerate(header_cells)}
            if "company name" not in col or "date of notice" not in col:
                raise ParseFailed(f"unexpected UT header: {header_cells[:5]}")

            for tr in all_trs[1:]:
                cells = tr.find_all(["td", "th"])
                if len(cells) < 3:
                    continue
                employer = as_str(_text(cells[col["company name"]]))
                if not employer:
                    continue
                notice_date = _ut_date(_text(cells[col["date of notice"]]))
                if notice_date is None:
                    continue

                rows.append(
                    NoticeRow(
                        state="UT",
                        employer=employer,
                        notice_date=notice_date,
                        layoff_count=as_int(_text(cells[col["affected workers"]])),
                        city=as_str(_text(cells[col["location"]])),
                        source_url=SOURCE_URL,
                    )
                )
        return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def _ut_date(cell_text: str):
    """as_date plus repairs for the older sections' hand-typed typos:
    doubled slashes ('08/31//2022'), trailing junk ('03/09/2020&',
    '03/05/14 Updated'), and out-of-range days ('09/31/10')."""
    d = as_date(cell_text)
    if d is not None:
        return d
    text = re.sub(r"/{2,}", "/", cell_text.strip())
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", text)
    if not m:
        return None
    month, day, year = int(m.group(1)), int(m.group(2)), m.group(3)
    d = as_date(f"{month}/{day}/{year}")
    if d is not None:
        return d
    # day past the end of the month ('09/31/10') → clamp to the last day
    yr = int(year) if len(year) == 4 else 2000 + int(year)
    if 1 <= month <= 12:
        last = calendar.monthrange(yr, month)[1]
        if day > last:
            return as_date(f"{month}/{last}/{year}")
    return None


register(UTScraper())
