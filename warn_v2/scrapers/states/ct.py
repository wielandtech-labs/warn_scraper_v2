"""Connecticut WARN scraper.

Source: https://dolpublicdocumentlibrary.ct.gov/CsblrCategory
        ?prefix=%2Frapid_response%2Fwarn_documents
Data:   JSON listing of per-notice PDFs from the CT DOL Public Document Library
        (Azure Blob Storage via a .NET MVC API endpoint).

The page uses a JavaScript-powered document library; the underlying REST
endpoint is publicly accessible:
  GET /CsblrCategory/GetPagedBlobs
    ?pageSize=100&pageIndex=N&prefix=/rapid_response/warn_documents&module=WARN

Each item has:
  blobToken  - opaque token used to build the ViewBlob download URL
  name       - Azure blob path: "rapid_response/warn_documents/{year}/{file}.pdf"
  modifiedDate - ISO 8601 upload timestamp (proxy for notice date when the
                  filename contains no parseable date)

The filename encodes employer, optional city, and often the notice date:
  "{Employer} ({City}) M-D-YYYY.pdf"   (most common)
  "{Employer} ({City}).pdf"             (a few older notices, no date)
  "{Employer} M-D-YYYY.pdf"            (no city)

Notice documents are viewable at:
  https://dolpublicdocumentlibrary.ct.gov/advanceSearch/ViewBlob
    ?blobToken={token}&blobName={encoded_name}

The document library only reaches back to 2019. History 1998-2018 comes from
the retired ctdol.state.ct.us HTML report pages via pinned Wayback captures —
see the "Historical archive" section at the bottom of this module.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from warn_v2.scrapers._helpers import as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

log = logging.getLogger(__name__)

_SOURCE_URL = (
    "https://dolpublicdocumentlibrary.ct.gov/CsblrCategory"
    "?prefix=%2Frapid_response%2Fwarn_documents"
)
_API_BASE = "https://dolpublicdocumentlibrary.ct.gov"
_BLOBS_URL = f"{_API_BASE}/CsblrCategory/GetPagedBlobs"
_VIEW_URL = f"{_API_BASE}/advanceSearch/ViewBlob"
_PREFIX = "/rapid_response/warn_documents"
_PAGE_SIZE = 100

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Referer": _SOURCE_URL,
}

# Date at end of filename: " M-D-YYYY" or " M-D-YY"
_DATE_SUFFIX_RE = re.compile(
    r"[\s_](\d{1,2})[.\-](\d{1,2})[.\-](\d{2,4})\s*(?:OCR|_OCR|revised|Final)?\s*$",
    re.I,
)
# City inside trailing parentheses: " (City)"
_CITY_RE = re.compile(r"\s*\(([^)]+)\)\s*$")


def _parse_filename(name: str) -> tuple[str, str | None, date | None]:
    """Return (employer, city, notice_date) parsed from a blob filename.

    *name* is the full blob path; the filename (without extension) is extracted
    from the last path segment.  Both notice_date and city may be None.
    """
    filename = name.rsplit("/", 1)[-1]
    if filename.lower().endswith(".pdf"):
        filename = filename[:-4]

    # Strip junk suffixes (e.g. "_OCR", " (1)")
    filename = re.sub(r"\s*\(\d+\)\s*$", "", filename)

    # Extract notice date from end of filename
    notice_date: date | None = None
    m = _DATE_SUFFIX_RE.search(filename)
    if m:
        month, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        try:
            notice_date = date(yr, month, day)
        except ValueError:
            notice_date = None
        filename = filename[: m.start()]

    # Extract city from trailing parentheses
    city: str | None = None
    m2 = _CITY_RE.search(filename)
    if m2:
        city = m2.group(1).strip() or None
        filename = filename[: m2.start()]

    employer = filename.strip(" -_")
    return employer, city, notice_date


def _modified_date(iso: str) -> date | None:
    """Parse ISO 8601 modifiedDate to a date."""
    try:
        return datetime.fromisoformat(iso).date()
    except (ValueError, TypeError):
        return None


def _view_url(blob_token: str, blob_name: str) -> str:
    return f"{_VIEW_URL}?blobToken={quote(blob_token)}&blobName={quote(blob_name)}"


class CTScraper:
    state = "CT"
    source_url = _SOURCE_URL
    expected_row_range = (10, 5_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        all_items: list[dict] = []
        seen: set[str] = set()
        page = 1

        try:
            with httpx.Client(headers=_UA, follow_redirects=True, timeout=30) as client:
                while True:
                    r = client.get(
                        _BLOBS_URL,
                        params={
                            "pageSize": _PAGE_SIZE,
                            "pageIndex": page,
                            "prefix": _PREFIX,
                            "module": "WARN",
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
                    items = data.get("blobItems", [])
                    if not items:
                        break
                    new_items = [i for i in items if i["name"] not in seen]
                    if not new_items:
                        break
                    for item in new_items:
                        seen.add(item["name"])
                        all_items.append(item)
                    page += 1
        except httpx.HTTPError as e:
            raise ScrapeFailed(f"CT: blob listing error: {e}") from e

        if not all_items:
            raise ScrapeFailed("CT: no blob items returned from document library")
        return json.dumps({"blobItems": all_items}).encode()

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as e:
            raise ParseFailed(f"CT: JSON decode error: {e}") from e

        items = data.get("blobItems", [])
        if not items:
            raise ParseFailed("CT: no blob items in payload")

        rows: list[NoticeRow] = []
        for item in items:
            blob_name = item.get("name", "")
            blob_token = item.get("blobToken", "")

            employer, city, notice_date = _parse_filename(blob_name)
            if not employer:
                continue

            # Fall back to modified date when filename has no parseable date
            if notice_date is None:
                notice_date = _modified_date(item.get("modifiedDate", ""))
            if notice_date is None:
                continue

            notice_url = _view_url(blob_token, blob_name) if blob_token else None

            rows.append(
                NoticeRow(
                    state="CT",
                    employer=employer,
                    notice_date=notice_date,
                    city=as_str(city) or None,
                    raw_notice_url=notice_url,
                    source_url=_SOURCE_URL,
                    extra={"blob_name": blob_name},
                )
            )
        return rows


register(CTScraper())


# ---------------------------------------------------------------------------
# Historical archive (ctdol.state.ct.us via Wayback, 1998-2018).
# ---------------------------------------------------------------------------
#
# Before the Azure document library (2019+), CT DOL published WARN notices as
# hand-edited HTML tables on ctdol.state.ct.us/progsupt/bussrvce/warnreports/:
#
#   * Monthly era 1998-2009: one page per month. Filenames drifted over the
#     years (warn-0198.htm -> warn-99-01.htm -> warn2000-01.htm ->
#     warnreports2005-01.htm) and so did the columns (a Closing Y/N column
#     appears in 2005), but every page is the same conceptual table:
#     WARN Date | Affected Company | Location(s) of Layoffs | Number Affected
#     | Effective Date | [Closing Y/N] | Union Y/N | Union Address.
#   * Yearly era 2010-2018: one cumulative page per year (warn2010.htm ...)
#     with Date(s) of Layoffs / Date of Closing instead of Effective Date.
#
# The live site prunes pre-2019 pages, so each page is fetched from a pinned
# Wayback capture (validated offline against the 2026-07 cache, sha256 per
# capture). Known source holes — all of 2013 (warn2013.htm was never
# captured) and 2009 months other than Aug/Sep — need a FOIA request, not
# more scraping. warn2019.htm+ exist in Wayback but are NOT listed here: the
# live Azure-blob route already covers 2019+ and re-parsing them would mint
# duplicate rows keyed differently.
#
# Wayback lookups are scheme- and default-port-agnostic (SURT
# canonicalization), so the handful of captures whose original URLs carry
# ":80" or "https" replay identically from the normalized base URL below.

_CT_ARCHIVE_BASE = "http://www.ctdol.state.ct.us/progsupt/bussrvce/warnreports/"

# (wayback capture timestamp, path under _CT_ARCHIVE_BASE) — generated from
# the 2026-07 backfill cache manifest; 142 pages = 134 monthly + 8 yearly.
# (Jan 2005 was published twice, as warn2005-01.htm and warnreports2005-01.htm
# with identical rows; only the latter is listed.)
_CT_ARCHIVE_CAPTURES: tuple[tuple[str, str], ...] = (
    # 1998
    ("20040822202818", "warn-0198.htm"),
    ("20040822203247", "warn-0298.htm"),
    ("20040822201652", "warn-0398.htm"),
    ("20040822202517", "warn-0498.htm"),
    ("20040822202619", "warn-0598.htm"),
    ("20040822203024", "warn-0698.htm"),
    ("20040822202044", "warn-0798.htm"),
    ("20040822202442", "warn-0898.htm"),
    ("20040822202706", "warn-0998.htm"),
    ("20040822203123", "warn-1098.htm"),
    ("20040822201501", "warn-1198.htm"),
    ("20040822202257", "warn-1298.htm"),
    # 1999
    ("20040822202903", "warn-99-01.htm"),
    ("20040822203105", "warn-99-02.htm"),
    ("20040822201841", "warn-99-03.htm"),
    ("20040822202601", "warn-99-04.htm"),
    ("20040822202720", "warn-99-05.htm"),
    ("20040626192125", "warn-99-06.htm"),
    ("20040822202015", "warn-99-07.htm"),
    ("20040822202228", "warn-99-08.htm"),
    ("20040822202734", "warn-99-09.htm"),
    ("20040626193009", "warn-99-10.htm"),
    ("20040822201616", "warn-99-11.htm"),
    ("20040822202151", "warn-99-12.htm"),
    # 2000
    ("20040822184751", "warn2000-01.htm"),
    ("20040822191616", "warn2000-02.htm"),
    ("20040822192434", "warn2000-03.htm"),
    ("20040822183325", "warn2000-04.htm"),
    ("20040822184625", "warn2000-05.htm"),
    ("20040822191444", "warn2000-06.htm"),
    ("20040822192530", "warn2000-07.htm"),
    ("20040822184034", "warn2000-08.htm"),
    ("20040822184205", "warn2000-09.htm"),
    ("20040822191756", "warn2000-10.htm"),
    ("20040822192501", "warn2000-11.htm"),
    ("20040822183639", "warn2000-12.htm"),
    # 2001
    ("20040627021221", "warn2001-01.htm"),
    ("20040824165338", "warn2001-02.htm"),
    ("20040627015852", "warn2001-03.htm"),
    ("20040627020425", "warn2001-04.htm"),
    ("20041123084637", "warn2001-05.htm"),
    ("20040627014719", "warn2001-06.htm"),
    ("20040824165230", "warn2001-07.htm"),
    ("20041001073650", "warn2001-08.htm"),
    ("20040627020957", "warn2001-09.htm"),
    ("20041001074906", "warn2001-10.htm"),
    ("20040627015304", "warn2001-11.htm"),
    ("20040824165434", "warn2001-12.htm"),
    # 2002
    ("20040822202907", "warn2002-01.htm"),
    ("20040822202951", "warn2002-02.htm"),
    ("20040822201640", "warn2002-03.htm"),
    ("20040822202142", "warn2002-04.htm"),
    ("20040822202915", "warn2002-05.htm"),
    ("20040627081201", "warn2002-06.htm"),
    ("20040822201636", "warn2002-07.htm"),
    ("20040822202217", "warn2002-08.htm"),
    ("20040822202814", "warn2002-09.htm"),
    ("20040627081504", "warn2002-10.htm"),
    ("20040822202049", "warn2002-11.htm"),
    ("20040822202345", "warn2002-12.htm"),
    # 2003
    ("20040822184735", "warn2003-01.htm"),
    ("20040822191946", "warn2003-02.htm"),
    ("20040822192450", "warn2003-03.htm"),
    ("20040822183659", "warn2003-04.htm"),
    ("20040822184423", "warn2003-05.htm"),
    ("20040822191330", "warn2003-06.htm"),
    ("20040622174210", "warn2003-07.htm"),
    ("20040822183819", "warn2003-08.htm"),
    ("20040822184555", "warn2003-09.htm"),
    ("20040822192032", "warn2003-10.htm"),
    ("20040622152024", "warn2003-11.htm"),
    ("20040822183448", "warn2003-12.htm"),
    # 2004
    ("20040822202806", "warn2004-01.htm"),
    ("20040822203030", "warn2004-02.htm"),
    ("20040822201545", "warn2004-03.htm"),
    ("20040822202104", "warn2004-04.htm"),
    ("20040822202754", "warn2004-05.htm"),
    ("20040626220055", "warn2004-06.htm"),
    ("20040822201829", "warn2004-07.htm"),
    ("20070206141301", "2004%20Warn%20Reports/warn2004-08.htm"),
    ("20070624212703", "2004%20Warn%20Reports/warn2004-09.htm"),
    ("20061003124723", "2004%20Warn%20Reports/warn2004-10.htm"),
    ("20070624212741", "2004%20Warn%20Reports/warn2004-11.htm"),
    ("20061003124751", "2004%20Warn%20Reports/warn2004-12.htm"),
    # 2005
    ("20070624212813", "2005%20Warn%20Reports/warnreports2005-01.htm"),
    ("20070624212823", "2005%20Warn%20Reports/warnreports2005-02.htm"),
    ("20070627084930", "2005%20Warn%20Reports/warnreports2005-03.htm"),
    ("20070624212959", "2005%20Warn%20Reports/warnreports2005-04.htm"),
    ("20070206141438", "2005%20Warn%20Reports/warnreports2005-05.htm"),
    ("20070624212944", "2005%20Warn%20Reports/warnreports2005-06.htm"),
    ("20070625142453", "2005%20Warn%20Reports/warnreports2005-07.htm"),
    ("20070206141511", "2005%20Warn%20Reports/warnreports2005-08.htm"),
    ("20070625142128", "2005%20Warn%20Reports/warnreports2005-09.htm"),
    ("20070206141530", "2005%20Warn%20Reports/warnreports2005-10.htm"),
    ("20070206141540", "2005%20Warn%20Reports/warnreports2005-11.htm"),
    ("20070624212834", "2005%20Warn%20Reports/warnreports2005-12.htm"),
    # 2006
    ("20070625141922", "2006%20Warn%20Reports/warnreports2006-01.htm"),
    ("20070206141618", "2006%20Warn%20Reports/warnreports2006-02.htm"),
    ("20070206141629", "2006%20Warn%20Reports/warnreports2006-03.htm"),
    ("20070625141822", "2006%20Warn%20Reports/warnreports2006-04.htm"),
    ("20070206141648", "2006%20Warn%20Reports/warnreports2006-05.htm"),
    ("20070627084952", "2006%20Warn%20Reports/warnreports2006-06.htm"),
    ("20070627084918", "2006%20Warn%20Reports/warnreports2006-07.htm"),
    ("20070206141721", "2006%20Warn%20Reports/warnreports2006-08.htm"),
    ("20070624212852", "2006%20Warn%20Reports/warnreports2006-09.htm"),
    ("20070625141951", "2006%20Warn%20Reports/warnreports2006-10.htm"),
    ("20070206141751", "2006%20Warn%20Reports/warnreports2006-11.htm"),
    ("20070625142029", "2006%20Warn%20Reports/warnreports2006-12.htm"),
    # 2007
    ("20081214210733", "2007%20Warn%20Reports/warnreports2007-01.htm"),
    ("20081214210738", "2007%20Warn%20Reports/warnreports2007-02.htm"),
    ("20081214210745", "2007%20Warn%20Reports/warnreports2007-03.htm"),
    ("20081214210753", "2007%20Warn%20Reports/warnreports2007-04.htm"),
    ("20081214210759", "2007%20Warn%20Reports/warnreports2007-05.htm"),
    ("20081214210810", "2007%20Warn%20Reports/warnreports2007-06.htm"),
    ("20081214210815", "2007%20Warn%20Reports/warnreports2007-07.htm"),
    ("20081214210835", "2007%20Warn%20Reports/warnreports2007-08.htm"),
    ("20081214210841", "2007%20Warn%20Reports/warnreports2007-09.htm"),
    ("20081214210848", "2007%20Warn%20Reports/warnreports2007-10.htm"),
    ("20081214210903", "2007%20Warn%20Reports/warnreports2007-11.htm"),
    ("20081214210933", "2007%20Warn%20Reports/warnreports2007-12.htm"),
    # 2008
    ("20081214011000", "2008%20Warn%20Reports/warnreports2008-01.htm"),
    ("20081214011006", "2008%20Warn%20Reports/warnreports2008-02.htm"),
    ("20081214011012", "2008%20Warn%20Reports/warnreports2008-03.htm"),
    ("20081214011017", "2008%20Warn%20Reports/warnreports2008-04.htm"),
    ("20081214011023", "2008%20Warn%20Reports/warnreports2008-05.htm"),
    ("20081214011028", "2008%20Warn%20Reports/warnreports2008-06.htm"),
    ("20081214011033", "2008%20Warn%20Reports/warnreports2008-07.htm"),
    ("20081214011039", "2008%20Warn%20Reports/warnreports2008-08.htm"),
    ("20081214011044", "2008%20Warn%20Reports/warnreports2008-09.htm"),
    ("20081212152328", "2008%20Warn%20Reports/warnreports2008-10.htm"),
    ("20081212152333", "2008%20Warn%20Reports/warnreports2008-11.htm"),
    ("20081212152338", "2008%20Warn%20Reports/warnreports2008-12.htm"),
    # 2009
    ("20090927183340", "2009%20Warn%20Reports/warnreports2009-8.htm"),
    ("20090927183345", "2009%20Warn%20Reports/warnreports2009-9.htm"),
    # 2010
    ("20121120053127", "warn2010.htm"),
    # 2011
    ("20120418004148", "warn2011.htm"),
    # 2012
    ("20121220070027", "warn2012.htm"),
    # 2014
    ("20170226004322", "warn2014.htm"),
    # 2015
    ("20250523155521", "warn2015.htm"),
    # 2016
    ("20250702081254", "warn2016.htm"),
    # 2017
    ("20250523155514", "warn2017.htm"),
    # 2018
    ("20250523155510", "warn2018.htm"),
)

# Slash- or dash-separated M/D/YY(YY); the 1999 pages write "8-11-99". A
# 1-digit year (the "9-22-9" typo in warn-99-09) is rejected rather than
# guessed — the row then falls back to its Rec'd date.
_CT_MDY_RE = re.compile(r"(\d{1,2})([/-])(\d{1,2})\2(\d{2,4})\b")
_CT_INT_RE = re.compile(r"\d[\d,]*")
# Amendment annotations are kept out of the employer name (they would break
# dedup against the original notice's employer): "*Amended Notice",
# "(Update to 10/29/10 notice)", "(Amended)".
_CT_NOTE_RE = re.compile(
    r"\*+\s*Amended[^*(]*|\((?:Update|Amended|Updated|Revised)[^)]*\)?", re.I
)
# The pages are cp1252-authored; normalize smart quotes/dashes so employer
# names hash identically however a given year's typist entered them.
_CT_CHAR_MAP = str.maketrans(
    {
        "\u2018": "'",  # left single quote
        "\u2019": "'",  # right single quote (the "Rec'd" byte 0x92)
        "\u201c": '"',  # left double quote
        "\u201d": '"',  # right double quote
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\xa0": " ",
    }
)

_CT_EMPTY_MONTH_RE = re.compile(r"none\s+received|no\s+(?:warn\s+)?notices", re.I)


def _discover_ct_archive_urls() -> list[str]:
    """Static pinned Wayback ``id_`` replay URL list — no discovery pass."""
    from warn_v2.scrapers.wayback import replay_url

    return [replay_url(ts, _CT_ARCHIVE_BASE + tail) for ts, tail in _CT_ARCHIVE_CAPTURES]


def _ct_dates(text: str) -> list[date]:
    """All parseable M/D/YY dates in *text*, in order of appearance."""
    out: list[date] = []
    for m in _CT_MDY_RE.finditer(text):
        mo, dy, yr = int(m.group(1)), int(m.group(3)), int(m.group(4))
        if yr < 100:
            # Data spans 1998-2019; effective dates never reach back to the 80s.
            yr += 1900 if yr >= 90 else 2000
        if not 1990 <= yr <= 2035:
            continue  # source typo, e.g. warn2012's "10/26/120"
        try:
            out.append(date(yr, mo, dy))
        except ValueError:
            continue
    return out


def _ct_cell_text(td) -> str:
    """One cell's text, whitespace-collapsed.

    FrontPage-era markup splits words across adjacent inline tags
    ("<span>S</span><span>murfit-Stone…"), so inline text is joined with NO
    separator; explicit spaces are inserted only at the structural breaks
    (<br>, <p>) that separate the glued "1/16/98 Rec'd 1/20/98" date lines.
    """
    for br in td.find_all("br"):
        br.replace_with(" ")
    for p in td.find_all("p"):
        p.insert_after(" ")
    return " ".join(td.get_text("").translate(_CT_CHAR_MAP).split())


def _ct_row_cells(tr) -> list:
    """Cells belonging to *tr* itself — not to a nested table's rows.

    ``recursive=False`` is not enough on these hand-edited pages: warn2018's
    Sam's Club row wraps its first two ``<td>``s in a stray ``<b>``, which
    would silently shift every column one to the left.
    """
    return [td for td in tr.find_all(["td", "th"]) if td.find_parent("tr") is tr]


def _ct_expand_rows(trs: list) -> list[list[str]]:
    """Expand a table's ``<tr>``s into full text rows, honoring row/colspans.

    warn2010.htm publishes multi-batch and multi-town notices as one row with
    ``rowspan`` on the shared cells (WARN Date, Company, ...) and short
    continuation rows carrying only the per-batch Number Affected /
    Date(s) of Layoffs (Electric Boat) or per-town Location / Number
    (Shaw's Supermarkets). Each expanded row repeats the spanned values, so
    every batch/town parses as its own notice row.
    """
    out: list[list[str]] = []
    carry: dict[int, tuple[str, int]] = {}  # col index -> (text, rows left)
    for tr in trs:
        tds = _ct_row_cells(tr)
        row: list[str] = []
        col = 0
        i = 0
        while i < len(tds) or col in carry:
            if col in carry:
                text, rem = carry.pop(col)
                row.append(text)
                if rem > 1:
                    carry[col] = (text, rem - 1)
                col += 1
                continue
            td = tds[i]
            i += 1
            text = _ct_cell_text(td)
            try:
                rowspan = int(td.get("rowspan", 1))
            except (TypeError, ValueError):
                rowspan = 1
            try:
                colspan = int(td.get("colspan", 1))
            except (TypeError, ValueError):
                colspan = 1
            for c in range(col, col + colspan):
                cell = text if c == col else ""
                row.append(cell)
                if rowspan > 1:
                    carry[c] = (cell, rowspan - 1)
            col += colspan
        if row:
            out.append(row)
    return out


def _ct_header_map(cells: list[str]) -> dict[str, int] | None:
    """Map a candidate header row to column roles; None when not a header.

    Written against every observed header variant (7 across 1998-2018) by
    keyword rather than position, so a column added mid-era (Closing Y/N in
    2005) or renamed (Effective Date -> Date(s) of Layoffs in 2010) lands in
    the right role. Nav/layout tables never satisfy the required roles.
    """
    if "warn" not in " ".join(cells):
        return None
    cols: dict[str, int] = {}
    for i, c in enumerate(cells):
        if "warn" in c and "date" in c:
            cols["warn_date"] = i
        elif "compan" in c:
            cols["employer"] = i
        elif "location" in c:
            cols["location"] = i
        elif "number" in c:
            cols["count"] = i
        elif "effective" in c or "layoff" in c:
            cols["effective"] = i
        elif "closing" in c and "date" not in c:
            cols["closing"] = i
    if {"warn_date", "employer", "location", "count"} <= cols.keys():
        return cols
    return None


def parse_ct_archive(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse one archived monthly/yearly WARN page (all 1998-2018 variants).

    Per-cell notes:

    * WARN Date cells frequently glue the received date on: "1/16/98 Rec'd
      1/20/98". The first date is the notice_date; a second date is kept in
      ``extra["received"]``.
    * Number Affected is free text; a leading/embedded integer is extracted
      and anything that isn't a clean int is preserved in
      ``extra["layoff_count_raw"]`` (count stays None when no digits at all —
      "?", "Not Provided", ...).
    * Effective Date holds ranges ("3/6/98 to 3/27/98") — the first date
      wins; prose-only values ("Third Quarter of 1999") are kept verbatim in
      ``extra["effective_raw"]``.
    * Amendment annotations move from the employer name to ``extra["note"]``;
      different-date amendments therefore stay as separate rows (candidates
      for a later mark-superseded pass). Exact-duplicate rows within one page
      are collapsed here — storage's worksite merge would otherwise SUM their
      counts (that behavior exists for CA-style per-worksite rows).
    * Rows with no parseable WARN date or no employer are logged and skipped
      (page furniture, TOTAL footers, and a handful of source typos).
    """
    text = raw.decode("cp1252", errors="replace")
    soup = BeautifulSoup(text, "html.parser")

    rows: list[NoticeRow] = []
    found_table = False
    seen: set[tuple] = set()

    for table in soup.find_all("table"):
        trs = [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]
        if not trs:
            continue
        cols = _ct_header_map([_ct_cell_text(td).lower() for td in _ct_row_cells(trs[0])])
        if cols is None:
            continue
        found_table = True

        for cells in _ct_expand_rows(trs[1:]):
            if len(cells) <= max(cols.values()):
                if any(cells):
                    log.info(
                        "CT archive %s: short row skipped: %r", source_url, cells
                    )
                continue

            def cell(role: str, cells=cells, cols=cols) -> str:
                i = cols.get(role)
                return cells[i] if i is not None else ""

            dates = _ct_dates(cell("warn_date"))
            employer_raw = cell("employer")

            extra: dict[str, str] = {}
            note = " ".join(
                m.group(0).strip("*() ") for m in _CT_NOTE_RE.finditer(employer_raw)
            )
            employer = as_str(_CT_NOTE_RE.sub("", employer_raw).strip(" -*"))
            if note:
                extra["note"] = note

            if not dates or not employer:
                if employer or employer_raw or cell("warn_date"):
                    log.info(
                        "CT archive %s: unparseable row skipped: date=%r employer=%r",
                        source_url,
                        cell("warn_date"),
                        employer_raw,
                    )
                continue

            if len(dates) > 1:
                extra["received"] = dates[1].isoformat()

            count_raw = cell("count")
            layoff_count = as_int(count_raw)
            if layoff_count is None:
                m = _CT_INT_RE.search(count_raw)
                if m:
                    layoff_count = as_int(m.group(0))
                if count_raw:
                    extra["layoff_count_raw"] = count_raw

            eff_raw = cell("effective")
            eff_dates = _ct_dates(eff_raw)
            effective = eff_dates[0] if eff_dates else None
            if effective is None and eff_raw:
                extra["effective_raw"] = eff_raw

            closing = cell("closing").lower()
            closure_type = None
            if closing.startswith("y"):
                closure_type = "Closure"
            elif closing.startswith("n"):
                closure_type = "Layoff"

            row = NoticeRow(
                state="CT",
                employer=employer,
                notice_date=dates[0],
                effective_date=effective,
                layoff_count=layoff_count,
                closure_type=closure_type,
                city=as_str(cell("location")),
                source_url=source_url,
                extra=extra,
            )
            key = (
                row.employer,
                row.notice_date,
                row.effective_date,
                row.layoff_count,
                row.city,
                row.closure_type,
            )
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

    if not found_table:
        # Zero-notice months publish prose instead of a table ("None
        # received." — Sep 2008); anything else means the format drifted.
        if _CT_EMPTY_MONTH_RE.search(soup.get_text(" ", strip=True)):
            return []
        raise ParseFailed(f"CT archive: no WARN data table found in {source_url}")
    return rows
