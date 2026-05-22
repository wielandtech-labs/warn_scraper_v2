"""Iowa WARN scraper.

Source: https://workforce.iowa.gov/employers/resources/warn/notices
Data:   Cumulative Excel workbook (ADA-compliant version of the Tableau
        visualization).  The file is hosted at a stable media endpoint.

Excel columns (A-L, row 1 = header):
  Company | Address Line 1 | City | County | St | ZIP |
  Notice Type | Emp # | Notice Date | Layoff Date |
  Local Workforce Area | Industry

Dates are Excel datetime objects (converted natively by openpyxl).
"""
from __future__ import annotations

import io
from datetime import date, datetime

import httpx
import openpyxl

from warn_v2.scrapers._helpers import as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_SOURCE_URL = "https://workforce.iowa.gov/employers/resources/warn/notices"
_XL_URL = "https://workforce.iowa.gov/media/3025/download?inline"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": _SOURCE_URL,
}


def _as_date(val: object) -> date | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    from warn_v2.scrapers._helpers import as_date

    return as_date(str(val))


class IAScraper:
    state = "IA"
    source_url = _SOURCE_URL
    expected_row_range = (50, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(_XL_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"IA: GET {_XL_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        except Exception as e:
            raise ParseFailed(f"IA Excel: could not open: {e}") from e

        ws = wb.active
        rows: list[NoticeRow] = []
        header: dict[str, int] = {}

        for row_idx, row in enumerate(ws.iter_rows(values_only=True)):
            if row_idx == 0:
                for col_idx, val in enumerate(row):
                    if val is not None:
                        header[str(val).strip().upper()] = col_idx
                continue

            def _col(name: str, _r: tuple = row) -> object:
                idx = header.get(name, -1)
                return _r[idx] if 0 <= idx < len(_r) else None

            employer = as_str(_col("COMPANY"))
            if not employer:
                continue

            notice_date = _as_date(_col("NOTICE DATE"))
            if notice_date is None:
                continue

            rows.append(
                NoticeRow(
                    state="IA",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=_as_date(_col("LAYOFF DATE")),
                    layoff_count=(
                        as_int(_col("EMP #"))
                        if _col("EMP #") is not None
                        else None
                    ),
                    city=as_str(_col("CITY")) or None,
                    county=as_str(_col("COUNTY")) or None,
                    closure_type=as_str(_col("NOTICE TYPE")) or None,
                    source_url=_SOURCE_URL,
                    extra={
                        "wda": as_str(_col("LOCAL WORKFORCE AREA")) or None,
                        "industry": as_str(_col("INDUSTRY")) or None,
                    },
                )
            )

        wb.close()
        if not rows:
            raise ParseFailed("IA Excel: no data rows found")
        return rows


register(IAScraper())
