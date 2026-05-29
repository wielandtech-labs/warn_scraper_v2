"""New York WARN scraper.

Source: https://dol.ny.gov/warn-dashboard
Data:   Tableau Public workbook — fetched as CSV directly from public.tableau.com.

The dashboard replaced dol.ny.gov/warn-notices on April 1, 2025 and is backed
by the Tableau Public workbook ``WorkerAdjustmentRetrainingNotificationWARN``.
The underlying data is downloadable as a plain CSV without authentication or a
browser, which means no Playwright is required.

CSV columns (confirmed May 2026):
  Business Legal Name | Date Layoff/Closure Starts | Date of WARN Notice |
  Date Posted | Impacted Site Address | Impacted Site County |
  Layoff or Closure? | Permanent or Temporary Layoff? | Index |
  Number of Affected Workers

The Impacted Site Address field uses a double-space as a separator between the
street portion and the ``City, NY, ZIP`` portion (e.g. ``"1440 Broadway  New
York City, NY, 10018"``), which lets us extract city and ZIP directly without
a geocoding call.
"""
from __future__ import annotations

import csv
import io
import re

import httpx

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

SOURCE_URL = "https://dol.ny.gov/warn-dashboard"

# Tableau Public workbook / sheet identifiers.
_TB_WB   = "WorkerAdjustmentRetrainingNotificationWARN"
_TB_VIEW = "WARN"
_CSV_URL = (
    f"https://public.tableau.com/views/{_TB_WB}/{_TB_VIEW}.csv"
    "?:showVizHome=no"
)

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Matches "Street  City, NY, 10016" — double-space separates street from city.
_ADDR_RE = re.compile(
    r"^(.+?)\s{2,}(.+?),\s*NY,?\s*(\d{5}(?:-\d{4})?)\s*$",
    re.IGNORECASE,
)
# Fallback: last alphabetic word-group (possibly multi-word) before ", NY, ZIP".
# Handles addresses like "456 Johnson Avenue 420 Brooklyn, NY, 11237" where
# there is no double-space separator and no comma after the street number.
_ADDR_FALLBACK_RE = re.compile(
    r"^.+?(?:,\s*|\s+)([A-Za-z][A-Za-z ]+?),\s*NY,?\s*(\d{5}(?:-\d{4})?)\s*$",
    re.IGNORECASE,
)


class NYScraper:
    state = "NY"
    source_url = SOURCE_URL
    expected_row_range = (10, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        """Download the Tableau Public CSV for the NY WARN workbook."""
        try:
            r = httpx.get(_CSV_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"NY: GET {_CSV_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise ParseFailed("NY: CSV has no header row")

        # Strip trailing/leading whitespace from column names (Tableau adds spaces).
        col = {k.strip(): k for k in reader.fieldnames}

        required = {"Business Legal Name", "Date of WARN Notice"}
        missing = required - col.keys()
        if missing:
            raise ParseFailed(f"NY: missing expected columns: {missing}; got {list(col)}")

        rows: list[NoticeRow] = []
        for record in reader:
            # Normalise column access: strip whitespace from each key.
            rec = {k.strip(): v.strip() for k, v in record.items() if k}

            employer = as_str(rec.get("Business Legal Name"))
            if not employer:
                continue

            notice_date = as_date(rec.get("Date of WARN Notice"))
            if notice_date is None:
                continue

            effective_date = as_date(rec.get("Date Layoff/Closure Starts"))
            layoff_count = as_int(rec.get("Number of Affected Workers"))

            address_raw = rec.get("Impacted Site Address") or ""
            address, city, zip_code = _parse_address(address_raw)

            county = as_str(rec.get("Impacted Site County"))
            closure_type = as_str(rec.get("Layoff or Closure?"))
            layoff_type = as_str(rec.get("Permanent or Temporary Layoff?"))

            extra: dict[str, str] = {}
            if layoff_type:
                extra["layoff_type"] = layoff_type

            rows.append(
                NoticeRow(
                    state="NY",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    closure_type=closure_type,
                    address=address if address else None,
                    city=city,
                    zip=zip_code,
                    county=county,
                    source_url=SOURCE_URL,
                    extra=extra,
                )
            )
        return rows


def _parse_address(raw: str) -> tuple[str | None, str | None, str | None]:
    """Return ``(full_address, city, zip)`` from a NY WARN address string.

    The canonical format is ``"Street  City, NY, ZIP"`` (double-space separator).
    A fallback regex handles addresses where the separator is a single comma.
    Returns ``(raw, None, None)`` if no city/ZIP can be extracted.
    """
    raw = raw.strip()
    if not raw:
        return None, None, None

    m = _ADDR_RE.match(raw)
    if m:
        return raw, m.group(2).strip(), m.group(3)

    m = _ADDR_FALLBACK_RE.match(raw)
    if m:
        return raw, m.group(1).strip(), m.group(2)

    return raw, None, None


register(NYScraper())
