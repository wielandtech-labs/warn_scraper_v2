"""California WARN scraper.

Source: https://edd.ca.gov/Jobs_and_Training/warn/WARN_Report.xlsx
Format: XLSX, header on a row that is *not* row 0 (varies year-to-year).

Vs V1 (which used hardcoded `header=3` and `iloc[:-2, [0,1,2,4,5,8,10,12]]`),
this scraper finds the header row by name-matching and reads columns by name —
so a column reorder or extra blank top rows doesn't break it.
"""
from __future__ import annotations

import io
from datetime import date

import httpx
import pandas as pd

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

        col = _ColumnMap(df.columns)
        rows: list[NoticeRow] = []
        for _, r in df.iterrows():
            employer = col.get(r, _COMPANY_KEYS)
            if not employer or not str(employer).strip():
                continue
            row = NoticeRow(
                state="CA",
                employer=str(employer).strip(),
                notice_date=_as_date(col.get(r, _NOTICE_DATE_KEYS)),
                effective_date=_as_date(col.get(r, _EFFECTIVE_DATE_KEYS)),
                layoff_count=_as_int(col.get(r, _LAYOFF_COUNT_KEYS)),
                closure_type=_as_str(col.get(r, _TYPE_KEYS)),
                county=_as_str(col.get(r, _COUNTY_KEYS)),
                city=_as_str(col.get(r, _CITY_KEYS)) or _city_from_address(
                    col.get(r, _ADDRESS_KEYS)
                ),
                zip=_zip_from(col.get(r, _ZIP_KEYS), col.get(r, _ADDRESS_KEYS)),
                source_url=SOURCE_URL,
            )
            rows.append(row)
        return rows


def _read_with_header_detection(raw: bytes) -> pd.DataFrame:
    """Find the header row by scanning the first 10 rows for a known company-column name."""
    buf = io.BytesIO(raw)
    probe = pd.read_excel(buf, engine="openpyxl", header=None, nrows=10)
    header_row = None
    for i, row in probe.iterrows():
        cells = [str(c).strip().lower() for c in row.tolist() if pd.notna(c)]
        if any(k in cells for k in _COMPANY_KEYS):
            header_row = i
            break
    if header_row is None:
        raise ParseFailed("could not locate header row containing 'Company'")
    buf.seek(0)
    df = pd.read_excel(buf, engine="openpyxl", header=header_row)
    # Drop trailing summary rows (V1 hardcoded `iloc[:-2]`); detect by missing company.
    df = df.dropna(subset=[c for c in df.columns if _norm(c) in _COMPANY_KEYS])
    return df


class _ColumnMap:
    """Case/whitespace-insensitive column lookup."""

    def __init__(self, columns: pd.Index) -> None:
        self._map = {_norm(c): c for c in columns}

    def get(self, row: pd.Series, keys: tuple[str, ...]) -> object | None:
        for key in keys:
            actual = self._map.get(key)
            if actual is not None and actual in row.index:
                return row[actual]
        return None


def _norm(s: object) -> str:
    return " ".join(str(s).strip().lower().split())


def _as_date(value: object) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _as_int(value: object) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _as_str(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return s or None


def _city_from_address(address: object) -> str | None:
    s = _as_str(address)
    if not s:
        return None
    # Best-effort: addresses look like "123 Main St, San Diego, CA 92101"
    parts = [p.strip() for p in s.split(",")]
    if len(parts) >= 3:
        return parts[-2]
    return None


def _zip_from(zip_value: object, address: object) -> str | None:
    z = _as_str(zip_value)
    if z:
        return z.split("-", 1)[0][:5]
    s = _as_str(address)
    if not s:
        return None
    tail = s.rsplit(" ", 1)[-1]
    digits = "".join(c for c in tail if c.isdigit())
    return digits[:5] if len(digits) >= 5 else None


register(CAScraper())
