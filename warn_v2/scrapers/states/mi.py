"""Michigan WARN scraper.

Source: Michigan LEO (Labor and Economic Opportunity) Sitecore search API.
URL: https://www.michigan.gov/leo/bureaus-agencies/wd/data-public-notices/warn-notices

The public search page uses a Sitecore SXA search component. Calling the search
API endpoint directly with httpx (p=200) returns all WARN records in a single JSON
response — no Playwright needed.

API response: {"Count": 101, "Results": [{"Id": ..., "Html": "<div>...</div>"}, ...]}

Each HTML fragment contains:
  <a class="content-title-link">Company Name</a>
  <p>
    <strong>Type of company action:</strong> Layoff<br/>
    <strong>City:</strong> Novi, Michigan<br/>
    <strong>County:</strong> Oakland<br/>
    <strong>Layoff date:</strong> January 6, 2026<br/>
    <strong>Number of jobs impacted:</strong> 29
  </p>

Historical archive (backfill, 2000-2024): michigan.gov purged pre-2025 notices
from the Sitecore index mid-2025, but the state's Labor Market Information site
milmi.org published the same data and the Wayback Machine holds it (live
milmi.org/warn now redirects to the pruned LEO page; the files 404 live).
Two presentations, one 5-column schema
(Company Name | City | Date Received | Incident Type | Number of Layoffs):

  * 2016-2024 — per-year HTML tables on the archived /warn/archive page
    (``parse_mi_archive_html``).
  * 2000-2015 — one annual report PDF per year, warn2000.pdf-warn2015.pdf,
    with a clean text layer (``parse_mi_archive_pdf``). 2000-2006 print the
    Incident Type as a numeric code (legend: "1" = Facility Closure,
    "2" = Layoff Event); rescinded incidents stay listed with a count of 0.

Unlike the live cards (which only publish the layoff-occurrence date), the
archive carries the real filing date — archive rows store Date Received as
``notice_date`` and leave ``effective_date`` unset.
"""
from __future__ import annotations

import io
import json
import re
from datetime import date

import httpx
import pdfplumber
from bs4 import BeautifulSoup, NavigableString

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_API_URL = "https://www.michigan.gov/leo/sxa/search/results/"
_API_PARAMS = {
    "v": "{1FFFCC21-5151-4A2B-ABFC-F7FE4E5C9783}",
    "s": "{8E97AB1D-D2D4-47F8-8CC4-3F1039C8854F}",
    "p": 300,  # request more than current total to get everything in one call
    "autoFireSearch": "true",
    "itemid": "{BE81F7C2-36A8-4FDE-853C-B05B6E090055}",
}

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

SOURCE_URL = "https://www.michigan.gov/leo/bureaus-agencies/wd/data-public-notices/warn-notices"

# Strip state suffix from city values: "Novi, Michigan" → "Novi"
_STATE_SUFFIX_RE = re.compile(r",\s*(Michigan|MI)\s*$", re.IGNORECASE)

# Extract first M/D/YY or M/D/YYYY from prose date strings like "Beginning April 21, 2025"
_DATE_SLASH_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")


def _extract_date(raw: str) -> date | None:
    """Parse a date from raw strings that may contain prose prefixes or ranges.

    Handles:
      - "Beginning April 21, 2025" → strip first word → pandas parses "April 21, 2025"
      - "5/9/26-6/19/26"           → extract first slashed date "5/9/26"
      - "12/5/25, 1/16/26, ..."    → extract first slashed date "12/5/25"
      - "Commencing June 2025"     → strip first word → pandas parses "June 2025" as June 1
    """
    if not raw:
        return None
    d = as_date(raw)
    if d is not None:
        return d
    # Extract first M/D/YY or M/D/YYYY pattern (handles ranges and comma-lists)
    m = _DATE_SLASH_RE.search(raw)
    if m:
        return as_date(m.group(0))
    # Strip leading prose word (e.g. "Beginning"/"Commencing") and retry
    parts = raw.strip().split(None, 1)
    if len(parts) == 2:
        return as_date(parts[1])
    return None


class MIScraper:
    state = "MI"
    source_url = SOURCE_URL
    expected_row_range = (5, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        try:
            r = httpx.get(
                _API_URL, params=_API_PARAMS, headers=_UA, timeout=60, follow_redirects=True
            )
            r.raise_for_status()
            return r.content
        except httpx.HTTPError as exc:
            raise ScrapeFailed(f"MI: Sitecore API error: {exc}") from exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise ParseFailed(f"MI: response is not valid JSON: {exc}") from exc

        results = data.get("Results", [])
        if not results:
            raise ParseFailed("MI: Sitecore API returned no results")

        rows: list[NoticeRow] = []
        for item in results:
            html_fragment = item.get("Html", "")
            if not html_fragment:
                continue
            row = _parse_card(html_fragment)
            if row is not None:
                rows.append(row)

        if not rows:
            raise ParseFailed("MI: no valid rows parsed from API results")
        return rows


def _parse_card(html: str) -> NoticeRow | None:
    """Parse one Sitecore HTML card fragment into a NoticeRow."""
    soup = BeautifulSoup(html, "html.parser")

    # Company name: prefer <a class="content-title-link"> text, fall back to <h3>.
    # The anchor is frequently present but EMPTY (those cards carry the name in an
    # adjacent <h3>), so a plain `find(a) or find(h3)` latches onto the empty anchor
    # and the h3 fallback never fires — silently dropping the notice. Test the
    # extracted text, not mere element existence, before falling through.
    name_el = soup.find("a", class_="content-title-link")
    employer = as_str(name_el.get_text(strip=True)) if name_el else None
    if not employer:
        h3 = soup.find("h3")
        employer = as_str(h3.get_text(strip=True)) if h3 else None
    if not employer:
        return None

    # Extract labeled fields from <p><strong>Label:</strong> Value<br/>...</p>
    # or from <li><strong>Label:</strong> Value</li>
    labels: dict[str, str] = {}
    for strong in soup.find_all("strong"):
        label_text = strong.get_text(strip=True).rstrip(":").strip()
        # Value follows the strong element as a text node (sibling after br or in same p)
        sibling = strong.next_sibling
        if sibling is None:
            continue
        if isinstance(sibling, NavigableString):
            value = str(sibling).strip().lstrip("\xa0").strip()
        else:
            value = sibling.get_text(strip=True).lstrip("\xa0").strip()
        if label_text and value:
            labels[label_text.lower()] = value

    # Also try <li> format for older cards (site address, county, etc.)
    for li in soup.find_all("li"):
        strong = li.find("strong")
        if not strong:
            continue
        label_text = strong.get_text(strip=True).rstrip(":").strip().lower()
        value = li.get_text(strip=True).replace(strong.get_text(strip=True), "").strip()
        if label_text and value:
            labels.setdefault(label_text, value)

    # Map fields — date key varies across card vintages; values may include prose
    date_raw = (
        labels.get("layoff date")
        or labels.get("layoff dates")
        or labels.get("commencing date")
        or labels.get("closure date")
        or ""
    )
    notice_date = _extract_date(date_raw)
    if notice_date is None:
        return None  # skip cards without a parseable date

    city_raw = labels.get("city", "")
    city = as_str(_STATE_SUFFIX_RE.sub("", city_raw)) if city_raw else None

    county = as_str(labels.get("county", "").replace("\xa0", "").strip())
    closure_type = as_str(labels.get("type of company action", ""))

    # "Number of jobs impacted" is the layoff count field
    count_raw = labels.get("number of jobs impacted", labels.get("number of workers", ""))
    layoff_count = as_int(count_raw)

    # MI's API only publishes the layoff occurrence date ("Layoff date:" label).
    # We store it as both notice_date (for the content-hash dedup key) and
    # effective_date (the semantically correct field).  A separate filing date
    # is not available from this source.
    #
    # The layoff date is frequently in the future, but a notice can't be *filed*
    # in the future.  We deliberately keep notice_date == the layoff date here so
    # the dedup hash stays stable across nightly re-scrapes; storage
    # (warn_v2.pipeline.storage.upsert_notices) clamps the *stored* notice_date to
    # the scrape date on first insert when it's in the future, leaving the real
    # layoff date in effective_date.
    return NoticeRow(
        state="MI",
        employer=employer,
        notice_date=notice_date,
        effective_date=notice_date,
        layoff_count=layoff_count,
        closure_type=closure_type,
        city=city,
        county=county,
        source_url=SOURCE_URL,
    )


register(MIScraper())


# ---------------------------------------------------------------------------
# Historical archive (milmi.org via Wayback) — see module docstring.
# ---------------------------------------------------------------------------

# The one Wayback capture of the /warn/archive page that carries all nine
# 2016-2024 year tables (the fbclid query string is part of the archived URL).
_ARCHIVE_HTML_URL = (
    "https://web.archive.org/web/20250621201936id_/"
    "https://milmi.org/warn/archive"
    "?fbclid=IwAR1_xJ4VsYjaBCqzC3LaK38eCwK6R49zTwUnaRlgB3qZmg3vq5ajCf9QANM"
)

# Annual report PDFs, one per year 2000-2015, all captured 2021-07-15.
_ANNUAL_PDF_URL = (
    "https://web.archive.org/web/20210715id_/"
    "https://www.milmi.org/_docs/publications/warn/warn{year}.pdf"
)

_INCIDENT_CODE_MAP = {"1": "Facility Closure", "2": "Layoff Event"}

_ARCHIVE_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_ARCHIVE_COUNT_RE = re.compile(r"^\d[\d,]*$")
def _discover_mi_archive_urls() -> list[str]:
    """Static Wayback URL list: the 2016-2024 HTML page + 16 annual PDFs."""
    return [_ARCHIVE_HTML_URL] + [
        _ANNUAL_PDF_URL.format(year=y) for y in range(2000, 2016)
    ]


def _archive_row(
    employer: str,
    city: str | None,
    date_raw: str,
    incident: str | None,
    count_raw: str | None,
    source_url: str,
) -> NoticeRow | None:
    notice_date = as_date(date_raw)
    employer = as_str(employer.replace("\xad", "-"))
    if not employer or notice_date is None:
        return None
    return NoticeRow(
        state="MI",
        employer=employer,
        notice_date=notice_date,
        layoff_count=as_int(count_raw) if count_raw else None,
        closure_type=as_str(incident or ""),
        city=as_str(city or ""),
        source_url=source_url,
    )


def parse_mi_archive_html(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse the archived /warn/archive page (per-year tables, 2016-2024)."""
    soup = BeautifulSoup(raw, "html.parser")
    rows: list[NoticeRow] = []
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        hdr = [c.get_text(" ", strip=True).lower() for c in trs[0].find_all(["td", "th"])]
        # Year tables start with "Company Name"; the page's YTD summary
        # tables (header "January 1 through ...") are skipped here.
        if not hdr or "company name" not in hdr[0]:
            continue
        for tr in trs[1:]:
            tds = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
            if len(tds) < 5:
                continue
            # _archive_row drops the per-table "TOTAL:" footer (no date).
            row = _archive_row(tds[0], tds[1], tds[2], tds[3], tds[4], source_url)
            if row is not None:
                rows.append(row)
    if not rows:
        raise ParseFailed("MI archive page: no year-table rows parsed")
    return rows


def parse_mi_archive_pdf(raw: bytes, source_url: str) -> list[NoticeRow]:
    """Parse one annual report PDF (2000-2015) by word positions.

    Notice rows are date-anchored (one Date Received token per line);
    dateless lines are page furniture (totals, notes, the code legend, the
    YTD summary block) and are skipped. Left of the date, Company and City
    split at the inter-column gap nearest the City header x (gap size alone
    is ambiguous: real separators dip to ~7pt while long company names carry
    internal gaps up to ~8pt); where the source truncated a long company
    name at the column edge and its glyphs run into the city with no
    whitespace ("...AsseOrion"), the glued run is character-split at the
    edge. Right of the date, the trailing numeric token is the count and
    the rest is the Incident Type (numeric codes 2000-2006 mapped via the
    legend; unknown codes like the occasional "3"/"4" are kept verbatim).
    Rescinded incidents are listed with a count of 0 (per the reports'
    footnote) and kept that way.
    """
    rows: list[NoticeRow] = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        anchors: dict[str, float] | None = None
        for page in pdf.pages:
            words = page.extract_words()

            # Group words into lines. 1.5pt absorbs the sub-point jitter a
            # row's date/count glyphs can carry (seen: 1.0pt + float noise
            # in warn2007) while staying far under the ~10pt row pitch.
            lines: list[tuple[float, list[dict]]] = []
            for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
                if lines and abs(w["top"] - lines[-1][0]) <= 1.5:
                    lines[-1][1].append(w)
                else:
                    lines.append((w["top"], [w]))

            # Header anchors; continuation pages reuse the previous page's.
            hdr_top = None
            for t, ws in lines:
                texts = {w["text"]: w["x0"] for w in ws}
                if {"Company", "City", "Date"} <= texts.keys():
                    anchors = texts
                    hdr_top = t
                    break
            if anchors is None:
                continue
            city_x = anchors["City"]

            for t, ws in lines:
                if hdr_top is not None and t <= hdr_top + 14:
                    continue
                # Clustering appends jittered words after their line; restore
                # column order (a line's x order IS its column order).
                ws = sorted(ws, key=lambda w: w["x0"])
                date_i = next(
                    (i for i, w in enumerate(ws) if _ARCHIVE_DATE_RE.match(w["text"])),
                    None,
                )
                if date_i is None:
                    continue
                date_w = ws[date_i]
                company, city = _split_company_city(ws[:date_i], city_x, page)

                toks = [w["text"] for w in ws[date_i + 1 :]]
                count_raw = None
                if toks and _ARCHIVE_COUNT_RE.match(toks[-1]):
                    count_raw = toks[-1]
                    toks = toks[:-1]
                incident = " ".join(toks)
                incident = _INCIDENT_CODE_MAP.get(incident, incident)

                row = _archive_row(
                    company, city, date_w["text"], incident, count_raw, source_url
                )
                if row is not None:
                    rows.append(row)
    if not rows:
        raise ParseFailed("MI annual PDF: no notice rows parsed")
    return rows


def _split_company_city(
    words: list[dict], city_x: float, page
) -> tuple[str, str | None]:
    """Split the words left of the date into (company, city).

    Preference order: the >=4pt inter-word gap whose following word starts
    nearest the City header x (within its observed data offset, up to 45pt
    left / 25pt right of the header); then a plain x threshold; then a
    character-level split of a single glyph run crossing the column edge
    (source-truncated company names). Rows whose left side never reaches
    the City column have no city cell in the source.
    """
    if not words:
        return "", None
    candidates = [
        (abs(words[i + 1]["x0"] - city_x), i)
        for i in range(len(words) - 1)
        if words[i + 1]["x0"] - words[i]["x1"] >= 4.0
        and city_x - 45 <= words[i + 1]["x0"] <= city_x + 25
    ]
    if candidates:
        _, best_i = min(candidates)
        company = " ".join(w["text"] for w in words[: best_i + 1])
        city = " ".join(w["text"] for w in words[best_i + 1 :])
        return company, city
    # No gap near the column: words starting at/after the City column.
    city_words = [w for w in words if w["x0"] >= city_x - 12]
    body_words = [w for w in words if w["x0"] < city_x - 12]
    if city_words:
        return (
            " ".join(w["text"] for w in body_words),
            " ".join(w["text"] for w in city_words),
        )
    # A single glyph run crossing the edge: split its characters at the edge.
    crossing = next((w for w in words if w["x0"] < city_x - 2 < w["x1"]), None)
    if crossing is not None:
        chars = [
            c
            for c in page.chars
            if crossing["x0"] - 0.5 <= c["x0"] <= crossing["x1"]
            and abs(c["top"] - crossing["top"]) <= 1.5
        ]
        left = "".join(c["text"] for c in chars if c["x0"] < city_x - 2)
        right = "".join(c["text"] for c in chars if c["x0"] >= city_x - 2)
        if right:
            before = [w["text"] for w in words if w["x0"] < crossing["x0"]]
            after = [w["text"] for w in words if w["x0"] > crossing["x0"]]
            company = " ".join([*before, left]).strip()
            return company, " ".join([right, *after]).strip()
    return " ".join(w["text"] for w in words), None
