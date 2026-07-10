"""Texas WARN scraper.

Source: https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-{year}-twc.xlsx
The URL templates on the current calendar year; January runs may need to fall
back to the prior year (TWC sometimes publishes the new year's file a few weeks
late).

URL history:
  2021 and earlier: https://twc.texas.gov/files/news/warn-act-listings-{year}.xlsx
  2022+:            https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-{year}-twc.xlsx

V1 schema (columns unchanged since the 2004 files, still seen in 2026):
  NOTICE_DATE, JOB_SITE_NAME, COUNTY_NAME, WDA_NAME, TOTAL_LAYOFF_NUMBER,
  LayOff_Date, WFDD_RECEIVED_DATE, CITY_NAME

Backfill sources (files before 2020 were removed from twc.texas.gov):
  2004-2018: pinned Wayback captures of the old per-year files — legacy
             binary .xls through 2013 (parsed via xlrd), .xlsx 2014+.
             Year files bleed slightly at the edges (e.g. the 2018 file
             heads into Jan 2019) — the content-hash notice_id dedupes
             the overlap.
  2019:      the Socrata dataset https://data.texas.gov/resource/8w53-c4f6
             (starts 2019-01; same columns, snake_case JSON).
"""
from __future__ import annotations

import io
import json
from datetime import datetime

import httpx
import pandas as pd

from warn_v2.scrapers import wayback
from warn_v2.scrapers._helpers import ColumnMap, as_date, as_int, as_str, norm
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.http_cache import conditional_get
from warn_v2.scrapers.registry import register

URL_TEMPLATE = "https://www.twc.texas.gov/sites/default/files/oei/docs/warn-act-listings-{year}-twc.xlsx"

SOCRATA_URL = "https://data.texas.gov/resource/8w53-c4f6.json"

# Pinned Wayback captures of the removed per-year files, all post-year (full
# coverage). 2004-2010 come from one 2016-12-23 crawl of twc.texas.gov;
# 2011-2018 from one 2020-09-07 crawl of the www.twc.state.tx.us mirror.
_WAYBACK_CAPTURES: dict[int, tuple[str, str]] = {
    2004: ("20161223011305", "http://twc.texas.gov/files/news/warn-act-listings-2004.xls"),
    2005: ("20161223011246", "http://twc.texas.gov/files/news/warn-act-listings-2005.xls"),
    2006: ("20161223011225", "http://twc.texas.gov/files/news/warn-act-listings-2006.xls"),
    2007: ("20161223011159", "http://twc.texas.gov/files/news/warn-act-listings-2007.xls"),
    2008: ("20161223011131", "http://twc.texas.gov/files/news/warn-act-listings-2008.xls"),
    2009: ("20161223011110", "http://twc.texas.gov/files/news/warn-act-listings-2009.xls"),
    2010: ("20161223010946", "http://twc.texas.gov/files/news/warn-act-listings-2010.xls"),
    2011: ("20200907075758", "https://www.twc.state.tx.us/files/news/warn-act-listings-2011.xls"),
    2012: ("20200907075716", "https://www.twc.state.tx.us/files/news/warn-act-listings-2012.xls"),
    2013: ("20200907075646", "https://www.twc.state.tx.us/files/news/warn-act-listings-2013.xls"),
    2014: ("20200907075629", "https://www.twc.state.tx.us/files/news/warn-act-listings-2014.xlsx"),
    2015: ("20200907075616", "https://www.twc.state.tx.us/files/news/warn-act-listings-2015.xlsx"),
    2016: ("20200907075605", "https://www.twc.state.tx.us/files/news/warn-act-listings-2016.xlsx"),
    2017: ("20200907075543", "https://www.twc.state.tx.us/files/news/warn-act-listings-2017.xlsx"),
    2018: ("20200907075531", "https://www.twc.state.tx.us/files/news/warn-act-listings-2018.xlsx"),
}

# The archived 2012 file spells the headers with spaces ("JOB SITE NAME")
# instead of the underscores every other year uses.
_COMPANY_KEYS = ("job_site_name", "job site name", "company", "employer", "company name")
_NOTICE_DATE_KEYS = ("notice_date", "notice date")
_EFFECTIVE_DATE_KEYS = ("layoff_date", "layoff date")
_LAYOFF_COUNT_KEYS = ("total_layoff_number", "total layoff number", "no. of employees")
_CITY_KEYS = ("city_name", "city name", "city")
_COUNTY_KEYS = ("county_name", "county name", "county", "county/parish")
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
                content = conditional_get(url, state=self.state, timeout=60)
                self.source_url = url
                return content
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    last_err = e
                    continue
                raise ScrapeFailed(f"GET {url}: {e}") from e
            except httpx.HTTPError as e:
                raise ScrapeFailed(f"GET {url}: {e}") from e
        raise ScrapeFailed(f"no TX file found for {year} or {year - 1}: {last_err}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        if raw.lstrip()[:1] in (b"[", b"{"):
            return parse_tx_socrata(raw, self.source_url)
        try:
            df = _read_with_header_detection(raw)
        except ParseFailed:
            raise
        except Exception as e:
            raise ParseFailed(f"could not read workbook: {e}") from e

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


def parse_tx_socrata(raw: bytes, source_url: str | None) -> list[NoticeRow]:
    """Socrata JSON rows (data.texas.gov 8w53-c4f6); fields mirror the XLSX
    columns in snake_case."""
    try:
        records = json.loads(raw)
    except ValueError as e:
        raise ParseFailed(f"bad Socrata JSON: {e}") from e
    if not isinstance(records, list):
        raise ParseFailed("Socrata payload is not a JSON array")
    rows: list[NoticeRow] = []
    for rec in records:
        employer = as_str(rec.get("job_site_name"))
        if not employer:
            continue
        rows.append(
            NoticeRow(
                state="TX",
                employer=employer,
                notice_date=as_date(rec.get("notice_date")),
                effective_date=as_date(rec.get("layoff_date")),
                layoff_count=as_int(rec.get("total_layoff_number")),
                city=as_str(rec.get("city_name")),
                county=as_str(rec.get("county_name")),
                source_url=source_url,
            )
        )
    return rows


def _fetch_tx_year(scraper, year: int) -> bytes | None:
    """Fetch one year's data for backfill-historical.

    Files before 2020 have been removed from twc.texas.gov (verified
    2026-06-12; the old `/files/news/` era URLs are dead too), so 2004-2018
    replay pinned Wayback captures and 2019 comes from the Socrata dataset.
    Returns None when no source has the year.
    """
    if year in _WAYBACK_CAPTURES:
        ts, original = _WAYBACK_CAPTURES[year]
        url = wayback.replay_url(ts, original)
        raw = wayback.fetch(url)
        if raw is not None:
            scraper.source_url = url  # parse() stamps rows with self.source_url
        return raw
    if year == 2019:
        return _fetch_tx_socrata_year(scraper, year)
    url = URL_TEMPLATE.format(year=year)
    try:
        r = httpx.get(url, timeout=60, follow_redirects=True)
        if r.status_code == 404:
            return None
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {url}: {e}") from e
    scraper.source_url = url
    return r.content


def _fetch_tx_socrata_year(scraper, year: int) -> bytes:
    """One year of notices from the Socrata dataset, strictly by notice-date
    year (the 2018 Wayback file already tails into Jan 2019)."""
    params = {
        "$where": (
            f"notice_date between '{year}-01-01T00:00:00' "
            f"and '{year}-12-31T23:59:59'"
        ),
        "$order": "notice_date",
        "$limit": "50000",
    }
    try:
        r = httpx.get(SOCRATA_URL, params=params, timeout=60)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {SOCRATA_URL}: {e}") from e
    scraper.source_url = str(r.url)
    return r.content


def _read_with_header_detection(raw: bytes) -> pd.DataFrame:
    # The 2004-2013 archive-era files are legacy OLE2 .xls — route those to
    # xlrd, which converts float date serials to Timestamps like openpyxl.
    engine = "xlrd" if raw[:4] == b"\xd0\xcf\x11\xe0" else "openpyxl"
    buf = io.BytesIO(raw)
    probe = pd.read_excel(buf, engine=engine, header=None, nrows=10)
    header_row = None
    for i, row in probe.iterrows():
        cells = [norm(c) for c in row.tolist() if pd.notna(c)]
        if any(k in cells for k in _COMPANY_KEYS):
            header_row = i
            break
    if header_row is None:
        raise ParseFailed("could not locate header row with company column")
    buf.seek(0)
    df = pd.read_excel(buf, engine=engine, header=header_row)
    df = df.dropna(subset=[c for c in df.columns if norm(c) in _COMPANY_KEYS])
    return df


register(TXScraper())
