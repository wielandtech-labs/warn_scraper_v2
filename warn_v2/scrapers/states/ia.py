"""Iowa WARN scraper.

Source: https://workforce.iowa.gov/employers/resources/warn/notices
Data:   Cumulative Excel workbook (ADA-compliant version of the Tableau
        visualization).  The file is hosted at a stable media endpoint.

Excel columns (A-L, row 1 = header):
  Company | Address Line 1 | City | County | St | ZIP |
  Notice Type | Emp # | Notice Date | Layoff Date |
  Local Workforce Area | Industry

Dates are Excel datetime objects (converted natively by openpyxl).

ZIP-variance deduplication
--------------------------
Iowa's cumulative Excel occasionally lists the same notice twice — once
without a ZIP (early filing) and again with a ZIP (after Iowa staff
complete the record).  ``parse()`` collapses those pairs within a single
download: for any group sharing ``(employer, notice_date, city)``, rows
without a ZIP are dropped when at least one sibling in the group has a ZIP.
Rows where both siblings have distinct non-null ZIPs are kept as-is (they
represent genuinely different sites).
"""
from __future__ import annotations

import io
from collections import defaultdict
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

            zip_raw = _col("ZIP")
            if isinstance(zip_raw, (int, float)):
                zip_str = str(int(zip_raw))
                # Iowa ZIPs may lose their leading zero in numeric cells.
                if len(zip_str) == 4:
                    zip_str = "0" + zip_str
            else:
                zip_str = as_str(zip_raw)

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
                    zip=zip_str,
                    address=as_str(_col("ADDRESS LINE 1")) or None,
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
        return _dedup_zip_variance(rows)


def _dedup_zip_variance(rows: list[NoticeRow]) -> list[NoticeRow]:
    """Drop ZIP-less rows that have a ZIP-bearing sibling with the same key.

    Groups rows by ``(employer_normalized, notice_date, city_normalized)``.
    Within each group, if *any* row has a non-empty ZIP, rows without a ZIP
    are discarded.  Rows where every sibling lacks a ZIP, or where siblings
    have distinct non-null ZIPs (different sites), are kept as-is.
    """
    def _key(r: NoticeRow) -> tuple:
        return (
            " ".join(r.employer.strip().lower().split()),
            r.notice_date,
            " ".join((r.city or "").strip().lower().split()),
        )

    groups: dict[tuple, list[NoticeRow]] = defaultdict(list)
    for r in rows:
        groups[_key(r)].append(r)

    out: list[NoticeRow] = []
    for group in groups.values():
        if len(group) == 1:
            out.append(group[0])
            continue
        has_zip = [r for r in group if r.zip]
        no_zip  = [r for r in group if not r.zip]
        if has_zip and no_zip:
            # Prefer ZIP-bearing rows; drop the ZIP-less duplicates.
            out.extend(has_zip)
        else:
            # All have ZIPs (different sites) or none have ZIPs — keep all.
            out.extend(group)
    return out


register(IAScraper())
