"""Iowa WARN scraper.

Source: https://workforce.iowa.gov/employers/resources/warn/notices
Data:   Cumulative Excel workbook (ADA-compliant version of the Tableau
        visualization).  The file is hosted at a stable media endpoint.

Excel columns (12, A-L):
  Company | Street Address | City | County | State | ZIP |
  Notice Type | Number of Employees Affected | Notice Date | Layoff Date |
  Local Workforce Area | Industry

The header row is located by its labels, not a fixed offset: as of 2026-06 the
workbook prepends a title/source/description banner above the table, and some
columns were relabelled from their earlier names ("Address Line 1" ->
"Street Address", "Emp #" -> "Number of Employees Affected", "St" -> "State").
``parse()`` accepts both the current and legacy labels.

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

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import DATA_DIR, load_archive
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

        for row in ws.iter_rows(values_only=True):
            if not header:
                # Locate the header row. Iowa prepends a title/source/description
                # banner above the table (added 2026-06), so the header is no
                # longer guaranteed to be row 0 — detect it by its column labels.
                labels = {
                    str(val).strip().upper(): col_idx
                    for col_idx, val in enumerate(row)
                    if val is not None
                }
                if "COMPANY" in labels and "NOTICE DATE" in labels:
                    header = labels
                continue

            def _col(*names: str, _r: tuple = row, _h: dict = header) -> object:
                # Accept column-name aliases so the parser handles both the
                # current and legacy Iowa header labels.
                for name in names:
                    idx = _h.get(name, -1)
                    if 0 <= idx < len(_r):
                        return _r[idx]
                return None

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

            emp_raw = _col("NUMBER OF EMPLOYEES AFFECTED", "EMP #")
            rows.append(
                NoticeRow(
                    state="IA",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=_as_date(_col("LAYOFF DATE")),
                    layoff_count=as_int(emp_raw) if emp_raw is not None else None,
                    city=as_str(_col("CITY")) or None,
                    county=as_str(_col("COUNTY")) or None,
                    zip=zip_str,
                    address=as_str(_col("STREET ADDRESS", "ADDRESS LINE 1")) or None,
                    closure_type=as_str(_col("NOTICE TYPE")) or None,
                    source_url=_SOURCE_URL,
                    extra={
                        "wda": as_str(_col("LOCAL WORKFORCE AREA")) or None,
                        "industry": as_str(_col("INDUSTRY")) or None,
                    },
                )
            )

        wb.close()
        if not header:
            raise ParseFailed("IA Excel: header row (Company/Notice Date) not found")
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


# ---------------------------------------------------------------------------
# Historical backfill (Mode 3b): bundled snapshots of the rolling WARN log
# ---------------------------------------------------------------------------
# Iowa publishes ONE cumulative log and prunes old rows from it over time, so
# no live URL carries the full history. Four archived snapshots of that log
# (captured via the Wayback Machine) are bundled as a tar.gz; their union
# covers 2005-07 through the live scraper's 2021+ floor with no interior gap:
#
#   WARN_20150722.pdf   2005-07 .. 2015-07  (PDF era -> parse_ia_archive_pdf)
#   WARN_20171219.xlsx  2011    .. 2017-12  (legacy labels; IAScraper.parse)
#   WARN_20210105.xlsx  2015-08 .. 2021-01  (legacy labels; IAScraper.parse)
#   WARN_20230823.xlsx  2018-09 .. 2023-08  (legacy labels; IAScraper.parse)
#
# The snapshots overlap heavily by design (each pair shares 2-6 years);
# identical rows collapse by notice_id at upsert. "Amendment" rows are kept
# as-is: the live cumulative log carries the same Notice Type value and prod
# already stores them (closure_type="Amendment"); superseded originals are a
# post-ingest `mark-superseded --state IA` concern, not a parse-time one.

_ARCHIVE_TGZ = DATA_DIR / "ia_archive.tar.gz"


def ia_archive_files() -> list[tuple[str, bytes]]:
    """(member_name, bytes) for every snapshot in the bundled archive."""
    return load_archive(_ARCHIVE_TGZ)


def parse_ia_archive_pdf(raw: bytes) -> list[NoticeRow]:
    """Parse the PDF-era snapshot of Iowa's cumulative WARN log.

    Layout: one landscape table per page with the same 10 columns as the
    XLSX era (Company | Address | City | County | State | ZIP |
    Type of Notice | Employees Affected | Notice Date | Layoff Date); the
    header row repeats on every page. Dates are m/d/yyyy strings; the known
    source typo "10/20/1969" (Gleason Corp layoff date) is rejected by
    ``as_date``'s year floor and stored as None.
    """
    import pdfplumber

    def _cell(row: list, header: dict[str, int], name: str) -> str | None:
        idx = header.get(name, -1)
        if not (0 <= idx < len(row)) or row[idx] is None:
            return None
        # Cells wrap long values onto multiple lines — collapse whitespace.
        # The PDF font also renders hyphens as U+2010 (unicode HYPHEN,
        # "McGraw-Hill") where the XLSX-era snapshots use ASCII "-";
        # normalize so overlapping rows hash-collide by notice_id instead
        # of duplicating.
        s = " ".join(str(row[idx]).split()).replace("\u2010", "-")
        return s or None

    rows: list[NoticeRow] = []
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    header: dict[str, int] = {}
                    for raw_row in table:
                        labels = {
                            " ".join(str(v).split()).upper(): i
                            for i, v in enumerate(raw_row)
                            if v is not None
                        }
                        if "COMPANY" in labels and "NOTICE DATE" in labels:
                            header = labels
                            continue
                        if not header:
                            continue
                        employer = _cell(raw_row, header, "COMPANY")
                        if not employer:
                            continue
                        notice_date = as_date(_cell(raw_row, header, "NOTICE DATE"))
                        if notice_date is None:
                            continue
                        rows.append(
                            NoticeRow(
                                state="IA",
                                employer=employer,
                                notice_date=notice_date,
                                effective_date=as_date(
                                    _cell(raw_row, header, "LAYOFF DATE")
                                ),
                                layoff_count=as_int(
                                    _cell(raw_row, header, "EMPLOYEES AFFECTED")
                                ),
                                city=_cell(raw_row, header, "CITY"),
                                county=_cell(raw_row, header, "COUNTY"),
                                zip=_cell(raw_row, header, "ZIP"),
                                address=_cell(raw_row, header, "ADDRESS"),
                                closure_type=_cell(raw_row, header, "TYPE OF NOTICE"),
                                source_url=_SOURCE_URL,
                            )
                        )
    except Exception as e:
        raise ParseFailed(f"IA archive PDF: {e}") from e

    if not rows:
        raise ParseFailed("IA archive PDF: no data rows found")
    # Same ZIP-variance quirk as the XLSX log (early filing without a ZIP,
    # completed record with one) — collapse those pairs here too.
    return _dedup_zip_variance(rows)


register(IAScraper())
