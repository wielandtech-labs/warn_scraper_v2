"""Nevada WARN scraper.

Source: https://detr.nv.gov/Page/Warn_Notices
Data:   Single-page PDF at a stable URL; no date-stamping.

The PDF has no explicit table grid lines.  pdfplumber's default
``extract_table()`` sees only the header row.  We use word-position analysis
instead: each row's words are grouped by vertical proximity, then assigned
to columns by their horizontal (x) coordinate.

Column x-boundaries (measured from a 612-pt wide letter page):
  x <  80  Received Date
  x <  165 Effective Date  (concatenated with Type: "3/15/2026Layoff")
  x <  210 Affected Total  (concatenated with Employer start: "1Spirit")
  x <  385 Employer continuation
  x <  432 City
  x <  495 County
  x >= 495 Notification (WARN / Non-WARN)

The Effective Date and Type are always merged into one text token by the
PDF renderer; we split them with a regex.  The Affected Total and the first
word of the Employer are similarly merged (digits + first word of name).
"""
from __future__ import annotations

import io
import re
from collections import defaultdict

import httpx
import pdfplumber

from warn_v2.scrapers._helpers import as_date, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_PDF_URL = "https://detr.nv.gov/content/media/WARN_and_Non_WARN_Master_w_Logo.pdf"
_SOURCE_URL = "https://detr.nv.gov/Page/Warn_Notices"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) warn-v2/0.1"
    )
}

_DATE_TYPE_RE = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})(Layoff|Closure)?", re.I)
_CNT_EMP_RE = re.compile(r"^(\d+)([A-Za-z(].*)?$")
_DATE_FIRST_RE = re.compile(r"\d{1,2}/\d+/\d{4}")

# Vertical grouping tolerance (points)
_ROW_BUCKET = 5


def _parse_page_rows(page: object) -> list[dict]:
    """Extract structured data from one PDF page using word x-positions."""
    words = page.extract_words()  # type: ignore[union-attr]

    # Group words into visual rows by y-coordinate
    row_map: dict[int, list] = defaultdict(list)
    for w in words:
        bucket = round(w["top"] / _ROW_BUCKET) * _ROW_BUCKET
        row_map[bucket].append(w)

    results: list[dict] = []
    for y_key in sorted(row_map.keys()):
        rws = sorted(row_map[y_key], key=lambda w: w["x0"])

        # Data rows always begin with a date at x < 80
        first = rws[0]
        if first["x0"] > 80:
            continue
        if not _DATE_FIRST_RE.match(first["text"]):
            continue

        rcv_date: str | None = None
        eff_date: str | None = None
        action_type: str | None = None
        count_str: str | None = None
        emp_parts: list[str] = []
        city_parts: list[str] = []
        county: str | None = None
        notification: str | None = None

        for w in rws:
            t: str = w["text"]
            x: float = w["x0"]

            if x < 80:
                # Received Date column
                rcv_date = t
            elif x < 165:
                # Effective Date + Type (merged: "3/15/2026Layoff")
                m = _DATE_TYPE_RE.match(t)
                if m:
                    eff_date = m.group(1)
                    if m.group(2):
                        action_type = m.group(2)
                elif t.lower() in ("layoff", "closure") and action_type is None:
                    action_type = t.capitalize()
            elif x < 210:
                # Affected Total + first Employer word merged ("1Spirit")
                m = _CNT_EMP_RE.match(t)
                if m and m.group(1):
                    count_str = m.group(1)
                    if m.group(2):
                        emp_parts.append(m.group(2))
                else:
                    emp_parts.append(t)
            elif x < 385:
                # Employer name continuation
                emp_parts.append(t)
            elif x < 432:
                # City
                city_parts.append(t)
            elif x < 495:
                # County
                county = t
            else:
                # Notification type (WARN / Non-WARN)
                notification = t

        if not rcv_date:
            continue

        results.append(
            {
                "rcv_date": rcv_date,
                "eff_date": eff_date,
                "action_type": action_type,
                "count": count_str,
                "employer": " ".join(emp_parts),
                "city": " ".join(city_parts),
                "county": county,
                "notification": notification,
            }
        )
    return results


class NVScraper:
    state = "NV"
    source_url = _SOURCE_URL
    expected_row_range = (1, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(_PDF_URL, headers=_UA, timeout=60, follow_redirects=True)
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"GET {_PDF_URL}: {e}") from e

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            pdf = pdfplumber.open(io.BytesIO(raw))
        except Exception as e:
            raise ParseFailed(f"NV PDF: could not open: {e}") from e

        page_data: list[dict] = []
        with pdf:
            for page in pdf.pages:
                page_data.extend(_parse_page_rows(page))

        if not page_data:
            raise ParseFailed("NV PDF: no data rows found")

        rows: list[NoticeRow] = []
        for d in page_data:
            employer = as_str(d["employer"])
            if not employer:
                continue

            notice_date = as_date(d["rcv_date"])
            if notice_date is None:
                continue

            layoff_count: int | None = None
            if d["count"]:
                try:
                    layoff_count = int(d["count"])
                except ValueError:
                    pass

            rows.append(
                NoticeRow(
                    state="NV",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=as_date(d["eff_date"]) if d["eff_date"] else None,
                    layoff_count=layoff_count,
                    closure_type=as_str(d["action_type"]),
                    city=as_str(d["city"]) or None,
                    county=as_str(d["county"]) or None,
                    source_url=_SOURCE_URL,
                    extra={"notification": d["notification"] or ""},
                )
            )
        return rows


register(NVScraper())
