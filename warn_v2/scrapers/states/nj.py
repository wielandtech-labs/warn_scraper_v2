"""New Jersey WARN scraper.

NJ publishes a yearly tabular PDF at
  https://www.nj.gov/labor/assets/PDFs/WARN/{year}_WARN_Notice_Archive.pdf

The newer JSP query URL listed on the V1 status sheet
(lwd.state.nj.us/.../warn.jsp) is gated by Incapsula bot protection and
unscrapable without a real browser — so V2 sticks with the PDF source.

Per-page columns (consistent year over year):
  Company | City | Month Posted | Effective Date | Workforce Affected

Quirks:
- multi-line cell text (employer names that wrap across lines)
- multiple effective dates per row ("4/10/26 - 11/26/26", "5/1/26, 6/5/26, ...")
- multi-region workforce counts ("240 (Passaic), 417 (Bergen), ...")

For V2 we keep `effective_date` and `layoff_count` to the first parseable value
in each cell — the raw string is preserved in `extra` for downstream consumers
that need the full nuance.

NJ also publishes a cumulative workbook (WARN_Notice_Archive.xlsx) with one
sheet per year back to 2004, same five columns as the PDF.  The historical
backfill ingests it via parse_nj_archive_xlsx(), which mirrors the PDF
parser's field semantics so overlap years dedupe by notice_id.
"""
from __future__ import annotations

import calendar
import io
import re
from datetime import date, datetime

import httpx
import pdfplumber

from warn_v2.scrapers._helpers import as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

URL_TEMPLATE = "https://www.nj.gov/labor/assets/PDFs/WARN/{year}_WARN_Notice_Archive.pdf"
ARCHIVE_XLSX_URL = "https://www.nj.gov/labor/assets/PDFs/WARN/WARN_Notice_Archive.xlsx"

_MONTH_BY_NAME: dict[str, int] = {
    name.lower(): num for num, name in enumerate(calendar.month_name) if name
}
_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")
_INT_RE = re.compile(r"\d+")


class NJScraper:
    state = "NJ"
    expected_row_range = (10, 5_000)
    required_fields = frozenset({"employer"})  # notice_date is best-effort

    def __init__(self) -> None:
        self._year = datetime.now().year
        self.source_url = URL_TEMPLATE.format(year=self._year)

    def fetch(self) -> bytes:
        """Try current year; fall back to prior year if the new one isn't published yet."""
        last_err: Exception | None = None
        for candidate in (self._year, self._year - 1):
            url = URL_TEMPLATE.format(year=candidate)
            try:
                r = httpx.get(url, timeout=120, follow_redirects=True)
                r.raise_for_status()
                if not r.content.startswith(b"%PDF"):
                    raise httpx.HTTPError(f"response is not a PDF (got {r.content[:8]!r})")
                self._year = candidate
                self.source_url = url
                return r.content
            except httpx.HTTPError as e:
                last_err = e
                continue
        raise ScrapeFailed(f"no NJ PDF for {self._year} or {self._year - 1}: {last_err}")

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            rows = list(self._extract_rows(raw, self._year))
        except ParseFailed:
            raise
        except Exception as e:
            raise ParseFailed(f"could not extract NJ tables: {e}") from e
        return rows

    @staticmethod
    def _extract_rows(raw: bytes, year: int) -> list[NoticeRow]:
        out: list[NoticeRow] = []
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables() or []:
                    for cells in table:
                        if not cells or len(cells) < 5:
                            continue
                        # First row of each page is usually a header echo.
                        first = (cells[0] or "").strip().lower()
                        if first in ("", "company") or first.startswith("company "):
                            continue
                        employer = _clean_cell(cells[0])
                        if not employer:
                            continue
                        city = _clean_cell(cells[1])
                        month_text = _clean_cell(cells[2])
                        effective_text = _clean_cell(cells[3])
                        workforce_text = _clean_cell(cells[4])

                        out.append(
                            NoticeRow(
                                state="NJ",
                                employer=employer,
                                notice_date=_month_to_date(month_text, year),
                                effective_date=_first_date(effective_text),
                                layoff_count=_first_int(workforce_text),
                                city=city or None,
                                source_url=URL_TEMPLATE.format(year=year),
                                extra={
                                    "effective_date_raw": effective_text or "",
                                    "workforce_affected_raw": workforce_text or "",
                                    "month_posted": month_text or "",
                                },
                            )
                        )
        return out


_SHEET_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def parse_nj_archive_xlsx(raw: bytes) -> list[NoticeRow]:
    """Parse the cumulative WARN_Notice_Archive.xlsx (one sheet per year, 2004+).

    Field semantics deliberately mirror the live PDF parser so that overlap
    years produce identical notice_ids: notice_date is the first of the
    "Month Posted" month in the sheet's year, effective_date/layoff_count
    take the first parseable value, raw strings go to ``extra``.

    Sheet quirks handled: footnote rows starting with "*" (2009), all-blank
    padding rows, and a trailing January spillover row duplicated from the
    next year's sheet (2023) — dropped, since dating it with this sheet's
    year would mint a mis-dated near-duplicate.
    """
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception as e:
        raise ParseFailed(f"NJ archive xlsx: could not open: {e}") from e

    out: list[NoticeRow] = []
    for ws in wb.worksheets:
        m = _SHEET_YEAR_RE.search(str(ws.title))
        if not m:
            continue
        year = int(m.group(1))
        seen_december = False
        for values in ws.iter_rows(values_only=True):
            cells = tuple(values) + (None,) * 5
            employer = _clean_cell(cells[0])
            low = employer.lower()
            if not employer or low == "company" or low.startswith(("company ", "*")):
                continue
            month_text = _clean_cell(cells[2])
            month_low = month_text.split()[0].lower() if month_text else ""
            if month_low == "december":
                seen_december = True
            elif month_low == "january" and seen_december:
                continue  # spillover row from the next year's sheet

            effective = cells[3]
            if isinstance(effective, datetime):
                effective_date: date | None = effective.date()
                effective_text = effective.strftime("%m/%d/%Y")
            else:
                effective_text = _clean_cell(effective)
                effective_date = _first_date(effective_text)
            workforce_text = _clean_cell(cells[4])

            out.append(
                NoticeRow(
                    state="NJ",
                    employer=employer,
                    notice_date=_month_to_date(month_text, year),
                    effective_date=effective_date,
                    layoff_count=_first_int(workforce_text),
                    city=_clean_cell(cells[1]) or None,
                    source_url=ARCHIVE_XLSX_URL,
                    extra={
                        "effective_date_raw": effective_text or "",
                        "workforce_affected_raw": workforce_text or "",
                        "month_posted": month_text or "",
                    },
                )
            )
    return out


def _clean_cell(value: object) -> str:
    """Collapse newlines and surrounding whitespace into single spaces."""
    s = as_str(value)
    if not s:
        return ""
    return " ".join(s.split())


def _month_to_date(month_text: str, year: int) -> date | None:
    if not month_text:
        return None
    month_num = _MONTH_BY_NAME.get(month_text.split()[0].lower())
    if month_num is None:
        return None
    return date(year, month_num, 1)


def _first_date(text: str) -> date | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if not m:
        return None
    month, day, year = (int(g) for g in m.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _first_int(text: str) -> int | None:
    if not text:
        return None
    m = _INT_RE.search(text)
    return as_int(m.group(0)) if m else None


register(NJScraper())
