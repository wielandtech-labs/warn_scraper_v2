"""Texas WARN scraper.

Source: https://twc.texas.gov/files/news/warn-act-listings-{year}.xlsx — the URL
templates on the current calendar year, so January runs may need to fall back to
the prior year (TWC sometimes publishes the new year's file a few weeks late).

V1 schema (columns we still see in 2026):
  NOTICE_DATE, JOB_SITE_NAME, COUNTY_NAME, WDA_NAME, TOTAL_LAYOFF_NUMBER,
  LayOff_Date, WFDD_RECEIVED_DATE, CITY_NAME
"""
from __future__ import annotations

import io
from datetime import datetime

import httpx
import pandas as pd

from warn_v2.scrapers._helpers import ColumnMap, as_date, as_int, as_str, norm
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

URL_TEMPLATE = "https://twc.texas.gov/files/news/warn-act-listings-{year}.xlsx"

_COMPANY_KEYS = ("job_site_name", "company", "employer", "company name")
_NOTICE_DATE_KEYS = ("notice_date", "notice date")
_EFFECTIVE_DATE_KEYS = ("layoff_date", "layoff date")
_LAYOFF_COUNT_KEYS = ("total_layoff_number", "total layoff number", "no. of employees")
_CITY_KEYS = ("city_name", "city")
_COUNTY_KEYS = ("county_name", "county", "county/parish")
_TYPE_KEYS = ("warn_type", "warn type", "layoff/closure")


class TXScraper:
    state = "TX"
    expected_row_range = (10, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def __init__(self) -> None:
        self.source_url = URL_TEMPLATE.format(year=datetime.now().year)

    def fetch(self) -> bytes:
        """Try the current year, fall back to previous year on 404."""
        year = datetime.now().year
        last_err: Exception | None = None
        for candidate in (year, year - 1):
            url = URL_TEMPLATE.format(year=candidate)
            try:
                r = httpx.get(url, timeout=60, follow_redirects=True)
                r.raise_for_status()
                self.source_url = url
                return r.content
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    last_err = e
                    continue
                raise ScrapeFailed(f"GET {url}: {e}") from e
            except httpx.HTTPError as e:
                raise ScrapeFailed(f"GET {url}: {e}") from e
        raise ScrapeFailed(f"no TX file found for {year} or {year - 1}: {last_err}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            df = _read_with_header_detection(raw)
        except ParseFailed:
            raise
        except Exception as e:
            raise ParseFailed(f"could not read xlsx: {e}") from e

        col = ColumnMap(df.columns)
        rows: list[NoticeRow] = []
        for _, r in df.iterrows():
            employer = as_str(col.get(r, _COMPANY_KEYS))
            if not employer:
                continue
            notice_date = as_date(col.get(r, _NOTICE_DATE_KEYS))
            layoff_count = as_int(col.get(r, _LAYOFF_COUNT_KEYS))
            if notice_date is None and layoff_count is None:
                continue
            rows.append(
                NoticeRow(
                    state="TX",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(col.get(r, _EFFECTIVE_DATE_KEYS)),
                    layoff_count=layoff_count,
                    closure_type=as_str(col.get(r, _TYPE_KEYS)),
                    city=as_str(col.get(r, _CITY_KEYS)),
                    county=as_str(col.get(r, _COUNTY_KEYS)),
                    source_url=self.source_url,
                )
            )
        return rows


def _read_with_header_detection(raw: bytes) -> pd.DataFrame:
    buf = io.BytesIO(raw)
    probe = pd.read_excel(buf, engine="openpyxl", header=None, nrows=10)
    header_row = None
    for i, row in probe.iterrows():
        cells = [norm(c) for c in row.tolist() if pd.notna(c)]
        if any(k in cells for k in _COMPANY_KEYS):
            header_row = i
            break
    if header_row is None:
        raise ParseFailed("could not locate header row with company column")
    buf.seek(0)
    df = pd.read_excel(buf, engine="openpyxl", header=header_row)
    df = df.dropna(subset=[c for c in df.columns if norm(c) in _COMPANY_KEYS])
    return df


register(TXScraper())
