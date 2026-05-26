"""California WARN scraper.

Source: https://edd.ca.gov/Jobs_and_Training/warn/WARN_Report.xlsx
Format: XLSX, header on a row that is *not* row 0 (varies year-to-year).

Vs V1 (which used hardcoded `header=3` and `iloc[:-2, [0,1,2,4,5,8,10,12]]`),
this scraper finds the header row by name-matching and reads columns by name —
so a column reorder or extra blank top rows doesn't break it.
"""
from __future__ import annotations

import io

import httpx
import pandas as pd

from warn_v2.scrapers._helpers import (
    ColumnMap,
    as_date,
    as_int,
    as_str,
    city_from_address,
    norm,
    zip_from,
)
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://edd.ca.gov/Jobs_and_Training/warn/WARN_Report.xlsx"

# Tolerate minor renames; first match wins.
_COMPANY_KEYS = ("company", "employer", "company name")
_NOTICE_DATE_KEYS = ("notice date", "received date", "date received")
_EFFECTIVE_DATE_KEYS = ("effective date", "layoff date")
_LAYOFF_COUNT_KEYS = ("no. of employees", "number of employees", "employees affected")
_COUNTY_KEYS = ("county/parish", "county")
_CITY_KEYS = ("city",)
_ZIP_KEYS = ("zip", "zip code")
_ADDRESS_KEYS = ("address", "location address")
_TYPE_KEYS = ("layoff/closure", "type", "closure type")


class CAScraper:
    state = "CA"
    source_url = SOURCE_URL
    expected_row_range = (10, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(self.source_url, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {self.source_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            df = _read_with_header_detection(raw)
        except Exception as e:
            raise ParseFailed(f"could not read xlsx: {e}") from e

        col = ColumnMap(df.columns)
        rows: list[NoticeRow] = []
        for _, r in df.iterrows():
            employer = col.get(r, _COMPANY_KEYS)
            employer_str = as_str(employer)
            if not employer_str:
                continue
            notice_date = as_date(col.get(r, _NOTICE_DATE_KEYS))
            layoff_count = as_int(col.get(r, _LAYOFF_COUNT_KEYS))
            # Skip footer/summary rows: real notices always have at least one of
            # notice_date or layoff_count. Summary lines ("Total notices: N")
            # have neither.
            if notice_date is None and layoff_count is None:
                continue
            address = col.get(r, _ADDRESS_KEYS)
            row = NoticeRow(
                state="CA",
                employer=employer_str,
                notice_date=notice_date,
                effective_date=as_date(col.get(r, _EFFECTIVE_DATE_KEYS)),
                layoff_count=layoff_count,
                closure_type=as_str(col.get(r, _TYPE_KEYS)),
                county=as_str(col.get(r, _COUNTY_KEYS)),
                city=as_str(col.get(r, _CITY_KEYS)) or city_from_address(address),
                zip=zip_from(col.get(r, _ZIP_KEYS), address),
                source_url=SOURCE_URL,
            )
            rows.append(row)
        return rows


def _read_with_header_detection(raw: bytes) -> pd.DataFrame:
    """Find the header row by scanning the first 10 rows for a known company-column name.

    EDD publishes a multi-sheet workbook (Index, WARN Report Summary,
    Detailed WARN Report). We pick the first sheet whose name contains
    'detail' (case-insensitive), falling back to the last sheet.
    """
    buf = io.BytesIO(raw)
    xf = pd.ExcelFile(buf, engine="openpyxl")
    sheet_name = next(
        (s for s in xf.sheet_names if "detail" in s.lower()),
        xf.sheet_names[-1],
    )
    probe = xf.parse(sheet_name, header=None, nrows=10)
    header_row = None
    for i, row in probe.iterrows():
        cells = [str(c).strip().lower() for c in row.tolist() if pd.notna(c)]
        if any(k in cells for k in _COMPANY_KEYS):
            header_row = i
            break
    if header_row is None:
        raise ParseFailed("could not locate header row containing 'Company'")
    df = xf.parse(sheet_name, header=header_row)
    # Drop trailing summary rows; detect by missing company.
    df = df.dropna(subset=[c for c in df.columns if norm(c) in _COMPANY_KEYS])
    return df


register(CAScraper())
