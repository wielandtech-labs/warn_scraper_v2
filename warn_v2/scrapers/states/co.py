"""Colorado WARN scraper.

Colorado collects WARNs via a Google Form and publishes the responses sheet
as a CSV at:
  https://docs.google.com/spreadsheets/d/1HO8Fnm_4xey3Ctt6mYIig61Zx5iNq6_j_dlIaJvBS6o/export?format=csv

The sheet is append-only since 2019. The schema is 87 columns wide because each
form field is a column. We only normalize a handful:
  Company Name | Location Address | WARN Date | Total number of permanent layoffs |
  Total number of temporary layoffs | Begin date of layoffs | End date of layoffs |
  Reason for Layoffs | Select the workforce area | NAICS

layoff_count = permanent + temporary (the displaced-worker count). The
furlough / reduced-hours / workshare numbers are preserved in `extra` for
downstream consumers that need the full breakdown.
"""
from __future__ import annotations

import csv
import io
import re

import httpx

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1HO8Fnm_4xey3Ctt6mYIig61Zx5iNq6_j_dlIaJvBS6o/export?format=csv"
)


def _norm_key(s: str) -> str:
    """Trim trailing whitespace from headers (the form fields have stray spaces)."""
    return " ".join(s.strip().lower().split())


# Map our canonical fields → the set of possible source header spellings.
_KEY_MAP = {
    "company": ("company name",),
    "address": ("location address",),
    "warn_date": ("warn date",),
    "perm_layoffs": ("total number of permanent layoffs",),
    "temp_layoffs": ("total number of temporary layoffs",),
    "furloughs": ("total number of furloughs",),
    "reduced_hours": ("total number of employees with reduced hours",),
    "workshare": (
        "include the total number of employees on or expected to be on a workshare plan.",
    ),
    "begin_layoff": ("begin date of layoffs",),
    "end_layoff": ("end date of layoffs",),
    "reason": ("reason for layoffs",),
    "workforce_area": ("select the workforce area",),
    "naics": ("naics",),
}

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


class COScraper:
    state = "CO"
    source_url = SOURCE_URL
    # CSV is cumulative since 2019 — full sheet is ~50 rows, growing slowly.
    expected_row_range = (1, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(self.source_url, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {self.source_url}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        try:
            headers = next(reader)
        except StopIteration:
            raise ParseFailed("CSV is empty") from None

        key_to_idx = _build_index(headers)
        for canonical in ("company", "warn_date"):
            if canonical not in key_to_idx:
                raise ParseFailed(
                    f"CSV missing required column for {canonical!r}; headers={headers[:10]}..."
                )

        rows: list[NoticeRow] = []
        for record in reader:
            if not record:
                continue
            employer = _get(record, key_to_idx, "company")
            if not employer:
                continue
            warn_date = as_date(_get(record, key_to_idx, "warn_date"))
            if warn_date is None:
                continue
            perm = as_int(_get(record, key_to_idx, "perm_layoffs")) or 0
            temp = as_int(_get(record, key_to_idx, "temp_layoffs")) or 0
            layoff_count = perm + temp if (perm or temp) else None

            address = _get(record, key_to_idx, "address")
            zip_code = None
            if address:
                m = _ZIP_RE.search(address)
                if m:
                    zip_code = m.group(1)

            extra: dict[str, str] = {}
            for field_name in ("furloughs", "reduced_hours", "workshare",
                               "reason", "workforce_area", "naics"):
                val = _get(record, key_to_idx, field_name)
                if val:
                    extra[field_name] = val

            rows.append(
                NoticeRow(
                    state="CO",
                    employer=employer,
                    notice_date=warn_date,
                    effective_date=as_date(_get(record, key_to_idx, "begin_layoff")),
                    layoff_count=layoff_count,
                    closure_type=_get(record, key_to_idx, "reason") or None,
                    zip=zip_code,
                    source_url=SOURCE_URL,
                    extra=extra,
                )
            )
        return rows


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
