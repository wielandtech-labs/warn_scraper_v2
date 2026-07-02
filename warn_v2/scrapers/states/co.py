"""Colorado WARN scraper.

CDLE publishes WARN notices as one Google Sheet per calendar year, all linked
from the "WARN Listings" page:
  https://cdle.colorado.gov/employers/layoff-separations/layoff-warn-list

fetch() scrapes that page (browser UA — it 403s non-browser agents) for the
per-year sheet links, fills gaps from a known-sheet registry, downloads the
CSV export of the two newest sheets (current year, plus the prior year for
late revisions around the boundary), and returns a JSON envelope
``{"sheets": [{"year", "url", "csv"}, ...]}`` so raw snapshots stay replayable.
Older sheets are immutable and ingested once via
``warn-v2 backfill-historical --state CO`` (see ``_fetch_co_year``).

The yearly schemas vary and parse() maps them by header aliases:
  2015-2018  Company Name | Layoff Total | Workforce Region | WARN Date | Reason
  2019       same shape but published with NO header row (positional)
  2020       adds NAICS / Layoff Date(s) / Temp | Perm | Furloughs breakdown
  2021-2023  raw Google-Form response dumps (87-99 columns, one per form field)
  2024-      curated: Company | WARN Date | Total Notified | CO Layoffs |
             NAICS | Workforce Area | # Permanent | #Temp | Begin/End Date |
             Reason for Layoffs

layoff_count prefers the Colorado-specific count (Total CO / CO Layoffs /
CO Notifications) over the notice-wide total, then falls back to perm + temp.
Furlough / reduced-hours / workshare numbers are preserved in `extra`.

The 2021 sheet is an unfiltered public-form dump and contains a few junk
citizen submissions (e.g. "Lizzy Jacobs" dated 7/19/1957); `as_date`'s 1988
lower bound drops the impossible-date ones at parse time.
"""
from __future__ import annotations

import csv
import html
import io
import json
import logging
import re
from datetime import UTC, date, datetime

import httpx

from warn_v2.scrapers._helpers import as_date, as_int, as_str, zip_from
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

log = logging.getLogger(__name__)

SOURCE_URL = "https://cdle.colorado.gov/employers/layoff-separations/layoff-warn-list"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}


def _export_url(sheet_id: str, gid: str | None = None) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    return f"{url}&gid={gid}" if gid else url


# Sheets linked from SOURCE_URL as of 2026-07. Discovery normally finds these
# (plus any new year CDLE adds); the registry is the fallback for when the
# listings page is unreachable or its markup changes.
_KNOWN_SHEETS: dict[int, str] = {
    2026: _export_url("19jmo4Cwj933cmSBKV1t0zZ5O-2H5IpiLIhSH9MF8WF0", "1928499704"),
    2025: _export_url("1aFv4ntRhjnTMFKqBnuzbIkExCWgp6vnblYGm_h9GUeI", "879377649"),
    2024: _export_url("1tDQPJ8jVqmyGbLYs6hUZiiNQIsablkZyLJt8rLIzanY", "879377649"),
    2023: _export_url("1ATu4-rs7Rw59UOYcdN-tNZCuyEe3am59Fm8wKqATl7E"),
    2022: _export_url("1YPKuuH-bU2ARJjXkFufY3f8_S8pnLusHbBY0RtapE3M"),
    2021: _export_url("1HO8Fnm_4xey3Ctt6mYIig61Zx5iNq6_j_dlIaJvBS6o"),
    2020: _export_url("1Km1mSUnCGE3EtZQTnZEUwxbdDTOcDZmNx6bviTwl2jI"),
    2019: _export_url("1GZEh1FUcHFfovdKeagTHFiv_P-PVVx64Bk4Szc963Gs"),
    2018: _export_url("1AsxrFpcg5nDdlezayogQf03Fq0Bkt6c34plqbEFxljI"),
    2017: _export_url("19YAbx8HAC9mfDbAkxVxBwEl8YCPGHhE91QHJAGi7R98"),
    2016: _export_url("1M-jYA2cSbehhp1pbpcAa900PtjAgktCHbU556cSjzc4"),
    2015: _export_url("1dpKX0g31Fkv8Hs3k3cVCJ19ce4RANNlYSCwpEQA2nrI"),
}

_ANCHOR_RE = re.compile(
    r'<a[^>]*href="(https://(?:docs|drive)\.google\.com/[^"]+)"[^>]*>(.*?)</a>',
    re.S,
)
_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]+)")
_DRIVE_ID_RE = re.compile(r"[?&]id=([A-Za-z0-9_-]+)")
_GID_RE = re.compile(r"[?#&]gid=(\d+)")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# 'Layoff Date(s)' cells can hold several dates ("3/25/19, 4/24/19") — take the first.
_DATE_TOKEN_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")

# Map our canonical fields → possible source header spellings across all years.
_KEY_MAP = {
    "company": ("company name", "company"),
    "warn_date": ("warn date",),
    "co_total": ("total co", "co layoffs", "co notifications"),
    "total": ("layoff total", "total layoffs", "total notified"),
    "perm": ("total number of permanent layoffs", "# perm", "# permanent", "perm layoffs"),
    "temp": ("total number of temporary layoffs", "#temp", "temp layoffs"),
    "furloughs": ("#furloughs", "furloughs", "total number of furloughs"),
    # short spelling first: the 2022/2023 form dumps have both, data in the short one
    "reduced_hours": ("reduced hours", "total number of employees with reduced hours"),
    "workshare": (
        "include the total number of employees on or expected to be on a workshare plan.",
    ),
    "begin": ("begin date of layoffs", "begin date", "layoff date(s)"),
    "reason": ("reason for layoffs", "reason for layoff"),
    "workforce_area": (
        "select the workforce area",
        "workforce area",
        "workforce region",
        "workforce local area",
        "local area",
    ),
    # the 2022 sheet's NAICS header is corrupted to a stray dropdown value
    "naics": ("naics", "sector 33 (6414) guided missle & space vehicle"),
    "address": ("location address",),
}

# The 2019 sheet has no header row; same columns as 2015-2018 plus
# occupations (5) and layoff date(s) (6).
_2019_INDEX = {
    "company": 0,
    "total": 1,
    "workforce_area": 2,
    "warn_date": 3,
    "reason": 4,
    "begin": 6,
}


def _discover_sheet_urls() -> dict[int, str]:
    """Scrape the CDLE WARN listings page for per-year sheet links.

    Anchors look like "View Real-Time 2026 Warns" / "View 2020 WARN List";
    the year lives in the link text, the spreadsheet id (and sometimes a tab
    gid) in the href. First link per year wins.
    """
    try:
        r = httpx.get(SOURCE_URL, headers=_UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {SOURCE_URL}: {e}") from e

    sheets: dict[int, str] = {}
    for href, inner in _ANCHOR_RE.findall(r.text):
        text = html.unescape(re.sub(r"<[^>]+>", " ", inner))
        if "warn" not in text.lower():
            continue
        year_m = _YEAR_RE.search(text)
        id_m = _SHEET_ID_RE.search(href) or _DRIVE_ID_RE.search(href)
        if not (year_m and id_m):
            continue
        gid_m = _GID_RE.search(href)
        sheets.setdefault(
            int(year_m.group(1)),
            _export_url(id_m.group(1), gid_m.group(1) if gid_m else None),
        )
    return sheets


class COScraper:
    state = "CO"
    source_url = SOURCE_URL
    # Two newest sheets: ~25-100 rows mid-year; low minimum because the
    # current-year sheet is near-empty every January.
    expected_row_range = (5, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            sheets = _discover_sheet_urls()
        except ScrapeFailed as e:
            log.warning("CO: sheet discovery failed (%s); using known registry", e)
            sheets = {}
        if not sheets:
            sheets = dict(_KNOWN_SHEETS)
        else:
            for year, url in _KNOWN_SHEETS.items():
                sheets.setdefault(year, url)

        # Only the two newest sheets: history never changes and is ingested
        # via backfill-historical; the prior year still catches late entries
        # around the year boundary.
        payload: list[dict[str, object]] = []
        for year in sorted(sheets, reverse=True)[:2]:
            url = sheets[year]
            try:
                r = httpx.get(url, timeout=60, follow_redirects=True)
                r.raise_for_status()
            except httpx.HTTPError as e:
                log.warning("CO: %d sheet download failed (%s): %s", year, url, e)
                continue
            payload.append({"year": year, "url": url, "csv": r.text})
        if not payload:
            raise ScrapeFailed("CO: could not download any yearly WARN sheet")
        return json.dumps({"sheets": payload}).encode()

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            # Pre-2026-07 snapshots are the bare CSV of the (then only) 2021 sheet.
            text = raw.decode("utf-8-sig", errors="replace")
            if not text.strip():
                raise ParseFailed("CO: empty snapshot")
            return _parse_sheet(text, 2021, _KNOWN_SHEETS[2021])

        sheets = data.get("sheets", [])
        if not sheets:
            raise ParseFailed("CO: JSON payload contains no sheets")

        rows: list[NoticeRow] = []
        newest_with_rows = 0
        for sheet in sheets:
            year = int(sheet.get("year", 0))
            parsed = _parse_sheet(sheet.get("csv", ""), year, sheet.get("url", SOURCE_URL))
            if parsed:
                newest_with_rows = max(newest_with_rows, year)
            rows.extend(parsed)

        # The failure mode this scraper replaces was quietly re-reading a sheet
        # CDLE had stopped updating (stuck on 2021 until 2026). If the newest
        # sheet with parseable rows lags the calendar by more than a year, the
        # source has moved again — fail loudly instead of reporting "ok".
        if newest_with_rows < datetime.now(UTC).year - 1:
            raise ParseFailed(
                f"CO: newest parseable sheet is {newest_with_rows or 'none'}; "
                "the CDLE source has probably moved"
            )
        return rows


def _fetch_co_year(year: int) -> bytes | None:
    """Download one year's sheet for ``backfill-historical`` (None = no sheet).

    Registry first — the historical sheet set is fixed; discovery only for
    years the registry doesn't know yet.
    """
    url = _KNOWN_SHEETS.get(year)
    if url is None:
        url = _discover_sheet_urls().get(year)
    if url is None:
        return None
    try:
        r = httpx.get(url, timeout=60, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {url}: {e}") from e
    return json.dumps({"sheets": [{"year": year, "url": url, "csv": r.text}]}).encode()


def _parse_co_year(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse one year's envelope without the regular scraper's staleness guard."""
    sheet = json.loads(raw)["sheets"][0]
    return _parse_sheet(sheet["csv"], int(sheet.get("year", year)), sheet["url"])


def _parse_sheet(csv_text: str, year: int, url: str) -> list[NoticeRow]:
    records = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    if not records:
        return []
    idx = _build_index(records[0])
    body = records[1:]
    if "company" not in idx or "warn_date" not in idx:
        if year == 2019:
            idx, body = dict(_2019_INDEX), records
        else:
            log.warning(
                "CO: %s sheet has unrecognized header %s; skipped", year, records[0][:8]
            )
            return []

    rows: list[NoticeRow] = []
    for record in body:
        employer = _get(record, idx, "company")
        if not employer:
            continue
        warn_date = as_date(_get(record, idx, "warn_date"))
        if warn_date is None:
            continue

        layoff_count = as_int(_get(record, idx, "co_total"))
        if layoff_count is None:
            layoff_count = as_int(_get(record, idx, "total"))
        if layoff_count is None:
            perm = as_int(_get(record, idx, "perm")) or 0
            temp = as_int(_get(record, idx, "temp")) or 0
            layoff_count = perm + temp if (perm or temp) else None

        address = _get(record, idx, "address")

        extra: dict[str, str] = {}
        for field_name in ("furloughs", "reduced_hours", "workshare",
                           "reason", "workforce_area", "naics"):
            val = _get(record, idx, field_name)
            if val:
                extra[field_name] = val

        rows.append(
            NoticeRow(
                state="CO",
                employer=employer,
                notice_date=warn_date,
                effective_date=_first_date(_get(record, idx, "begin")),
                layoff_count=layoff_count,
                closure_type=_get(record, idx, "reason") or None,
                zip=zip_from(None, address),
                address=address,
                source_url=url,
                extra=extra,
            )
        )
    return rows


def _first_date(value: str | None) -> date | None:
    if not value:
        return None
    m = _DATE_TOKEN_RE.search(value)
    return as_date(m.group(0)) if m else as_date(value)


def _norm_key(s: str) -> str:
    return " ".join(s.strip().lower().split())


def _build_index(headers: list[str]) -> dict[str, int]:
    """Map our canonical names → column index in the source CSV."""
    norm_headers = [_norm_key(h) for h in headers]
    out: dict[str, int] = {}
    for canonical, variants in _KEY_MAP.items():
        for v in variants:
            if v in norm_headers:
                out[canonical] = norm_headers.index(v)
                break
    return out


def _get(record: list[str], idx_map: dict[str, int], key: str) -> str | None:
    i = idx_map.get(key)
    if i is None or i >= len(record):
        return None
    return as_str(record[i])


register(COScraper())
