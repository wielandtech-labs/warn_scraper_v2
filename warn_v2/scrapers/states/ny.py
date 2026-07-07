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
from bs4 import BeautifulSoup

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


# ---------------------------------------------------------------------------
# Historical backfill (2001-2020): archived details.asp records via Wayback
# ---------------------------------------------------------------------------
# The retired labor.ny.gov ASP portal exposed one page per notice
# (details.asp?id=N) with full fields: date of notice, control number,
# company + street address + "City, NY ZIP", county/WIB/region, business
# type, Number Affected, layoff/closing dates, reason. ~4,300 unique ids
# (3-9536, ~2001-2020) have statuscode-200 Wayback captures (probed
# 2026-07-06, docs/historical-sources.md). Discovery is CDX-driven; ids are
# deduped keeping the latest capture. No overlap with the live scraper (the
# Tableau era starts 2025). Values of "-----" mean not-provided at source.

_CDX_API = "https://web.archive.org/cdx/search/cdx"
_WAYBACK_REPLAY = "https://web.archive.org/web/{ts}id_/{url}"
_WAYBACK_DELAY = 3.0
_WAYBACK_BACKOFF = 30.0

_DETAIL_ID_RE = re.compile(r"details\.asp\?.*?\bid=(\d+)", re.I)
_NY_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}")
# "Rochester, NY  14650" (ZIP optional on the oldest pages).
_NY_CITY_ZIP_RE = re.compile(r"^(.+?),\s*N\.?Y\.?\s*(\d{5})?(?:-\d{4})?\s*$", re.I)
# Trailing control-number tokens on the Company line ("... Office 2008-W287").
_CONTROL_TOKEN_RE = re.compile(r"\s*\b\d{4}-W\d+\b.*$")
# Appendix line: "2008-W288: Employer..., 1999 Lake Avenue, Rochester, NY 14650"
_OTHER_SITE_RE = re.compile(
    r"^(?P<ctl>\d{4}-W\d+)\s*:\s*(?P<body>.+,\s*N\.?Y\.?\s*\d{5}(?:-\d{4})?)\s*$",
    re.I,
)
_AFFECTED_PAREN_RE = re.compile(r"^\((\d[\d,]*)\s+affected\)$", re.I)

# Page labels -> canonical keys. Values may sit inline after the colon.
_DETAIL_LABELS = {
    "date of notice": "notice_date",
    "control number": "control_number",
    "reason stated for filing": "filing_reason",
    "company": "company",
    "county": "county",
    "business type": "business_type",
    "number affected": "number_affected",
    "total employees": "total_employees",
    "layoff date": "layoff_date",
    "closing date": "closing_date",
    "reason for dislocation": "dislocation_reason",
}
_DETAIL_LABEL_RE = re.compile(
    r"^(" + "|".join(re.escape(k) for k in _DETAIL_LABELS) + r")\s*:\s*(.*)$",
    re.I,
)


def _clean_value(v: str | None) -> str | None:
    """Collapse whitespace; '-----' and empties mean not-provided."""
    if v is None:
        return None
    v = " ".join(v.replace("\xa0", " ").split())
    return v if v and set(v) != {"-"} else None


def _discover_ny_detail_urls() -> list[str]:
    """Wayback replay URL of the latest 200 capture per details.asp id."""
    import time

    for attempt in (1, 2):
        time.sleep(_WAYBACK_DELAY)
        try:
            r = httpx.get(
                _CDX_API,
                params={
                    "url": "labor.ny.gov/app/warn",
                    "matchType": "prefix",
                    "output": "json",
                    "fl": "timestamp,original",
                    "filter": "statuscode:200",
                    "collapse": "urlkey",
                    "limit": "100000",
                },
                headers=_UA,
                timeout=120,
            )
            r.raise_for_status()
            captures = r.json()
            break
        except (httpx.HTTPError, ValueError) as e:
            if attempt == 1:
                time.sleep(_WAYBACK_BACKOFF)
                continue
            raise ScrapeFailed(f"NY: CDX query for details.asp captures: {e}") from e
    if not isinstance(captures, list):
        return []
    best: dict[int, tuple[str, str]] = {}
    for cap in captures[1:]:  # row 0 is the field-name header
        if not (isinstance(cap, list) and len(cap) == 2):
            continue
        ts, original = str(cap[0]), str(cap[1])
        m = _DETAIL_ID_RE.search(original)
        if m is None:
            continue
        nid = int(m.group(1))
        # URL variants (scheme/www/&_ga junk) survive urlkey collapse - dedupe
        # by id, keeping the latest capture (amendments accrue over time).
        if nid not in best or ts > best[nid][0]:
            best[nid] = (ts, original)
    return [
        _WAYBACK_REPLAY.format(ts=ts, url=original)
        for _nid, (ts, original) in sorted(best.items())
    ]


def _first_date(raw: str | None):
    if not raw:
        return None
    m = _NY_DATE_RE.search(raw)
    return as_date(m.group(0)) if m else None


def _other_site_rows(lines: list[str], template: NoticeRow) -> list[NoticeRow]:
    """Rows for the "Other site affected:" appendix.

    Each site is one line - "2008-W288: Eastman Kodak, Kodak Research Labs,
    1999 Lake Avenue, Rochester, NY 14650" - optionally followed by
    "(8 affected)". The comma-separated body splits as [employer parts...,
    street, city] with the state/ZIP tail on the city segment.
    """
    rows: list[NoticeRow] = []
    for i, line in enumerate(lines):
        m = _OTHER_SITE_RE.match(line)
        if m is None:
            continue
        segs = [s.strip() for s in m.group("body").split(",")]
        if len(segs) < 3:
            continue
        zm = re.search(r"(\d{5})(?:-\d{4})?", segs[-1])
        city = segs[-2]
        street_idx = len(segs) - 3
        # The street usually starts with a number; anything before it is the
        # employer name (which may itself contain commas).
        while street_idx > 0 and not segs[street_idx][:1].isdigit():
            street_idx -= 1
        employer = _clean_value(", ".join(segs[:street_idx])) or template.employer
        count = None
        if i + 1 < len(lines):
            am = _AFFECTED_PAREN_RE.match(lines[i + 1])
            if am:
                count = int(am.group(1).replace(",", ""))
        rows.append(
            NoticeRow(
                state="NY",
                employer=employer,
                notice_date=template.notice_date,
                effective_date=template.effective_date,
                layoff_count=count,
                city=_clean_value(city),
                county=template.county,
                zip=zm.group(1) if zm else None,
                address=_clean_value(", ".join(segs[street_idx:-1])),
                closure_type=template.closure_type,
                source_url=template.source_url,
                extra={**template.extra, "control_number": m.group("ctl")},
            )
        )
    return rows


def parse_ny_detail(raw: bytes, url: str) -> list[NoticeRow]:
    """Parse one archived details.asp page into NoticeRow(s)."""
    soup = BeautifulSoup(raw, "html.parser")
    lines = [
        " ".join(ln.replace("\xa0", " ").split())
        for ln in soup.get_text("\n").splitlines()
    ]
    lines = [ln for ln in lines if ln]

    fields: dict[str, str | None] = {}
    addr_lines: list[str] = []
    after_company = False
    for line in lines:
        m = _DETAIL_LABEL_RE.match(line)
        if m:
            key = _DETAIL_LABELS[m.group(1).lower()]
            if key not in fields:  # first occurrence wins (page repeats chrome)
                fields[key] = _clean_value(m.group(2))
            after_company = key == "company"
        elif after_company:
            # Street/city lines sit between Company: and County:.
            addr_lines.append(line)

    employer = fields.get("company")
    if employer:
        employer = _clean_value(_CONTROL_TOKEN_RE.sub("", employer))
    notice_date = _first_date(fields.get("notice_date"))
    if not employer or notice_date is None:
        return []

    city = zip_code = None
    for ln in reversed(addr_lines):
        cm = _NY_CITY_ZIP_RE.match(ln)
        if cm:
            city = _clean_value(cm.group(1).split(",")[-1])
            zip_code = cm.group(2)
            break
    address = _clean_value(", ".join(addr_lines)) or None

    county = region = wib = None
    if fields.get("county"):
        parts = [p.strip() for p in fields["county"].split("|")]
        county = _clean_value(parts[0]) or None
        for p in parts[1:]:
            k, _, v = p.partition(":")
            if k.strip().upper() == "WIB":
                wib = _clean_value(v)
            elif k.strip().upper() == "REGION":
                region = _clean_value(v)

    extra = {
        k: v
        for k, v in (
            ("control_number", fields.get("control_number")),
            ("business_type", fields.get("business_type")),
            ("dislocation_reason", fields.get("dislocation_reason")),
            ("region", region),
            ("wib", wib),
        )
        if v
    }
    # The replay URL wraps the original; keep the original as source.
    source = re.sub(r"^https?://web\.archive\.org/web/[^/]+/", "", url)

    main = NoticeRow(
        state="NY",
        employer=employer,
        notice_date=notice_date,
        effective_date=(
            _first_date(fields.get("layoff_date"))
            or _first_date(fields.get("closing_date"))
        ),
        layoff_count=as_int(fields.get("number_affected")),
        city=city,
        county=county,
        zip=zip_code,
        address=address,
        closure_type=fields.get("filing_reason"),
        source_url=source,
        extra=extra,
    )
    return [main, *_other_site_rows(lines, main)]
