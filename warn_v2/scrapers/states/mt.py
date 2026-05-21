"""Montana WARN scraper.

Source: https://wsd.dli.mt.gov/wioa/related-links/warn-notice-page
Data:   https://wsd.dli.mt.gov/_docs/wioa/warn-notices-updated-march-2026.xlsx

Schema (live as of May 2026):
  Year | Date of Notice | Name of Company | County | Industry |
  Date of Impact | Number of Employees Affected

Excel download covering 2015-present. The Year column is only populated for
the first notice in each calendar year; subsequent rows leave it None — we
forward-fill it. Date of Impact can be a datetime or a free-text string with
multiple dates.
"""
from __future__ import annotations

import io

import httpx
import openpyxl

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

PAGE_URL = "https://wsd.dli.mt.gov/wioa/related-links/warn-notice-page"
SOURCE_URL = "https://wsd.dli.mt.gov/_docs/wioa/warn-notices-updated-march-2026.xlsx"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}


class MTScraper:
    state = "MT"
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
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw))
        except Exception as e:
            raise ParseFailed(f"MT XLSX: could not open workbook: {e}") from e

        ws = wb.active
        all_rows = list(ws.iter_rows(values_only=True))
        if not all_rows:
            raise ParseFailed("MT XLSX: empty workbook")

        header = [str(h).lower().strip() if h is not None else "" for h in all_rows[0]]
        expected = {"name of company", "date of notice"}
        if not expected.issubset(set(header)):
            raise ParseFailed(f"MT XLSX: unexpected header: {header[:7]}")

        col = {name: i for i, name in enumerate(header)}

        rows: list[NoticeRow] = []
        for raw_row in all_rows[1:]:
            employer = as_str(raw_row[col["name of company"]])
            if not employer:
                continue
            notice_date = as_date(raw_row[col["date of notice"]])
            if notice_date is None:
                continue

            effective_raw = raw_row[col["date of impact"]]
            effective_date = as_date(effective_raw) if effective_raw else None

            county_idx = col.get("county")
            industry_idx = col.get("industry")

            rows.append(
                NoticeRow(
                    state="MT",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=as_int(raw_row[col["number of employees affected"]]),
                    county=as_str(raw_row[county_idx]) if county_idx is not None else None,
                    source_url=SOURCE_URL,
                    extra={
                        "industry": (
                            as_str(raw_row[industry_idx]) or ""
                            if industry_idx is not None else ""
                        ),
                    },
                )
            )
        return rows


register(MTScraper())
