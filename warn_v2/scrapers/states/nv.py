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
from warn_v2.scrapers.http_cache import conditional_get
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


# ---------------------------------------------------------------------------
# Historical archives for backfill-historical.
#
# The master PDF at the stable URL is rotated to the current year only; DETR
# leaves per-year files behind under Content/Media with era-specific names
# (probed live 2026-07-02). Gaps:
#   * 2021 (WARN_2021.pdf) is a scanned image with no text layer — OCR would
#     be needed; skipped.
#   * 2023 was pruned from the live site — fetched via Wayback replay
#     (through Dec 8, 2023).
#   * the newest dated 2025 snapshot ends June 3, 2025; Jun-Dec 2025 is
#     published nowhere (the live master had already rotated to 2026 when
#     this scraper first ran) → records request.
# ---------------------------------------------------------------------------

_ARCHIVE_SOURCES: dict[int, str] = {
    2017: "https://detr.nv.gov/Content/Media/2017.pdf",
    2018: "https://detr.nv.gov/Content/Media/2018.pdf",
    2019: "https://detr.nv.gov/Content/Media/2019.pdf",
    2020: "https://detr.nv.gov/Content/Media/2020.pdf",
    2022: "https://detr.nv.gov/Content/Media/WARN_and_Non-WARN_Master_12.31.22.pdf",
    2023: (
        "https://web.archive.org/web/20250208173821id_/"
        "https://detr.nv.gov/Content/Media/WARN_and_Non-WARN_Master_w_Logo_12082023.pdf"
    ),
    2024: "https://detr.nv.gov/content/media/WARN_and_Non_WARN_Master_w_Logo_12_30.24.pdf",
    2025: "https://detr.nv.gov/content/media/WARN_and_Non_WARN_Master_w_Logo_05_15.25.pdf",
}

# Column x-boundaries per archive file (upper bound per column, measured from
# each file's body rows — page sizes and column layouts differ per era).
# Order: rcv_date, eff_date, type, count, employer, city, county; words at or
# beyond the county bound are the Notification column (absent in 2022).
_ARCHIVE_XBOUNDS: dict[int, tuple[int, int, int, int, int, int, int]] = {
    2022: (105, 157, 235, 293, 508, 585, 10_000),
    2023: (150, 200, 240, 262, 432, 502, 608),
    2024: (95, 140, 180, 200, 365, 450, 515),
    2025: (120, 175, 228, 279, 525, 600, 680),
}


def _fetch_nv_year(year: int) -> bytes | None:
    """Download one year's archive PDF; None for years with no usable file."""
    url = _ARCHIVE_SOURCES.get(year)
    if url is None:
        return None
    try:
        r = httpx.get(url, headers=_UA, timeout=120, follow_redirects=True)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        raise ScrapeFailed(f"GET {url}: {e}") from e


def parse_nv_archive(raw: bytes, year: int) -> list[NoticeRow]:
    """Parse a per-year archive PDF (layout era chosen by year).

    2017-2020 files are lattice tables (`extract_table` works); 2022+ files
    have no grid lines and use word-position parsing like the live master,
    but with per-era column boundaries.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(raw))
    except Exception as e:
        raise ParseFailed(f"NV archive {year}: could not open: {e}") from e

    source_url = _ARCHIVE_SOURCES.get(year, _SOURCE_URL)
    with pdf:
        if year <= 2020:
            dicts = _parse_archive_lattice(pdf)
        else:
            bounds = _ARCHIVE_XBOUNDS[year]
            dicts = []
            for page in pdf.pages:
                dicts.extend(_parse_words_with_bounds(page, bounds))

    if not dicts:
        raise ParseFailed(f"NV archive {year}: no data rows found")
    return _to_notice_rows(dicts, source_url)


def _parse_archive_lattice(pdf) -> list[dict]:
    """2017-2020 era: proper lattice tables, header on every page.

    Columns: Received Date | [Notice Date] | Effective Date | Type |
    Affected Total | Employer | City | County  (no Notification column).
    """
    col: dict[str, int] = {}
    results: list[dict] = []
    for page in pdf.pages:
        tbl = page.extract_table()
        if not tbl:
            continue
        for row in tbl:
            cells = [" ".join(str(c or "").split()) for c in row]
            lower = [c.lower() for c in cells]
            if "received date" in lower:
                if not col:
                    col = {name: i for i, name in enumerate(lower) if name}
                continue
            if not col or not cells[col["received date"]]:
                continue

            def _cell(name: str, _col=col, _cells=cells) -> str | None:
                i = _col.get(name)
                return _cells[i] if i is not None and i < len(_cells) else None

            results.append(
                {
                    "rcv_date": _cell("received date"),
                    "eff_date": _cell("effective date"),
                    "action_type": _cell("type"),
                    "count": _cell("affected total"),
                    "employer": _cell("employer") or "",
                    "city": _cell("city") or "",
                    "county": _cell("county"),
                    "notification": None,
                }
            )
    return results


def _parse_words_with_bounds(
    page: object, bounds: tuple[int, int, int, int, int, int, int]
) -> list[dict]:
    """Word-position parsing with explicit per-era column boundaries.

    Same row-bucketing approach as `_parse_page_rows`, but the archive files
    render count and employer as separate words, so no merged-token handling
    is needed (counts are right-aligned within their own column).
    """
    b_rcv, b_eff, b_type, b_count, b_emp, b_city, b_county = bounds
    words = page.extract_words()  # type: ignore[union-attr]

    row_map: dict[int, list] = defaultdict(list)
    for w in words:
        bucket = round(w["top"] / _ROW_BUCKET) * _ROW_BUCKET
        row_map[bucket].append(w)

    results: list[dict] = []
    for y_key in sorted(row_map.keys()):
        rws = sorted(row_map[y_key], key=lambda w: w["x0"])
        first = rws[0]
        if first["x0"] > b_rcv or not _DATE_FIRST_RE.match(first["text"]):
            continue

        d: dict = {
            "rcv_date": None,
            "eff_date": None,
            "action_type": None,
            "count": None,
            "employer": "",
            "city": "",
            "county": None,
            "notification": None,
        }
        emp_parts: list[str] = []
        city_parts: list[str] = []
        county_parts: list[str] = []
        for w in rws:
            t: str = w["text"]
            x: float = w["x0"]
            if x < b_rcv:
                d["rcv_date"] = t
            elif x < b_eff:
                m = _DATE_TYPE_RE.match(t)
                d["eff_date"] = m.group(1) if m else t
            elif x < b_type:
                d["action_type"] = t
            elif x < b_count:
                d["count"] = (d["count"] or "") + t
            elif x < b_emp:
                emp_parts.append(t)
            elif x < b_city:
                city_parts.append(t)
            elif x < b_county:
                county_parts.append(t)
            else:
                d["notification"] = t
        if not d["rcv_date"]:
            continue
        d["employer"] = " ".join(emp_parts)
        d["city"] = " ".join(city_parts)
        d["county"] = " ".join(county_parts) or None
        results.append(d)
    return results


def _to_notice_rows(dicts: list[dict], source_url: str) -> list[NoticeRow]:
    """Convert parsed row dicts (live or archive) to NoticeRows."""
    rows: list[NoticeRow] = []
    for d in dicts:
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
                source_url=source_url,
                extra={"notification": d["notification"] or ""},
            )
        )
    return rows


class NVScraper:
    state = "NV"
    source_url = _SOURCE_URL
    expected_row_range = (1, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            # Conditional GET: raises NotModified when the master PDF is unchanged.
            return conditional_get(_PDF_URL, state=self.state, headers=_UA, timeout=60)
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
        return _to_notice_rows(page_data, _SOURCE_URL)


register(NVScraper())
