"""Tennessee WARN scraper.

Source: https://www.tn.gov/workforce/general-resources/major-publications0/major-publications-redirect/reports.html

Schema (live as of May 2026):
  Date of Posting | Company | County | Affected Workers |
  Closure/Layoff Date | Notice/Type

The page has two tables: one for the current year and one for the archive.
Both use the same column structure; we parse both and combine them.
Company cell has an anchor tag linking to a per-notice PDF hosted on tn.gov.

Notice/Type contains a notice number (e.g. "#202500055"), not a layoff type;
we capture it in extra["notice_number"].

Note: tn.gov's WAF resets the TLS connection (Errno 104) for non-browser TLS
fingerprints — a plain httpx GET succeeds from a residential browser but is RST
from server/container deployments (same IP, different ClientHello). We fetch via
curl_cffi with ``impersonate="chrome"`` so the handshake matches a real Chrome,
which the WAF accepts.
"""
from __future__ import annotations

import re
import time
from datetime import date

from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from curl_cffi.requests.exceptions import RequestException

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.bundled import DATA_DIR, load_archive
from warn_v2.scrapers.registry import register

SOURCE_URL = (
    "https://www.tn.gov/workforce/general-resources/"
    "major-publications0/major-publications-redirect/reports.html"
)
_BASE_URL = "https://www.tn.gov"

# The WAF still RSTs a fraction (~1 in 4) of otherwise-valid Chrome handshakes,
# so a single GET is flaky even with impersonation; retry a few times.
_FETCH_ATTEMPTS = 4
_FETCH_BACKOFF = 2.0


class TNScraper:
    state = "TN"
    source_url = SOURCE_URL
    expected_row_range = (5, 10_000)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        last_exc: RequestException | None = None
        for attempt in range(1, _FETCH_ATTEMPTS + 1):
            try:
                r = cffi_requests.get(
                    SOURCE_URL, impersonate="chrome", timeout=30, allow_redirects=True
                )
                r.raise_for_status()
                return r.content
            except RequestException as e:
                last_exc = e
                if attempt < _FETCH_ATTEMPTS:
                    time.sleep(_FETCH_BACKOFF)
        raise ScrapeFailed(f"GET {SOURCE_URL}: {last_exc}") from last_exc

    def parse(self, raw: bytes) -> list[NoticeRow]:
        soup = BeautifulSoup(raw, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            raise ParseFailed("no <table> found on TN WARN page")

        rows: list[NoticeRow] = []
        for table in tables:
            rows.extend(_parse_table(table))

        if not rows:
            raise ParseFailed("TN WARN page: no data rows found in any table")
        return rows


def _parse_table(table) -> list[NoticeRow]:
    all_trs = table.find_all("tr")
    if not all_trs:
        return []

    header_cells = [_text(td).lower() for td in all_trs[0].find_all(["td", "th"])]
    if "company" not in header_cells or "county" not in header_cells:
        return []
    col = {name: i for i, name in enumerate(header_cells)}

    rows: list[NoticeRow] = []
    for tr in all_trs[1:]:
        cells = tr.find_all(["td", "th"])
        if len(cells) < 4:
            continue

        company_cell = cells[col["company"]]
        anchor = company_cell.find("a")
        employer = as_str(_text(anchor) if anchor else _text(company_cell))
        if not employer:
            continue
        notice_date = as_date(_text(cells[col["date of posting"]]))
        if notice_date is None:
            continue

        notice_url: str | None = None
        if anchor and anchor.get("href"):
            href = anchor["href"]
            notice_url = href if href.startswith("http") else _BASE_URL + href

        notice_type_idx = col.get("notice/type")
        notice_number = (
            as_str(_text(cells[notice_type_idx])) if notice_type_idx is not None else None
        )

        rows.append(
            NoticeRow(
                state="TN",
                employer=employer,
                notice_date=notice_date,
                effective_date=as_date(_text(cells[col["closure/layoff date"]])),
                layoff_count=as_int(_text(cells[col["affected workers"]])),
                county=as_str(_text(cells[col["county"]])),
                raw_notice_url=notice_url,
                source_url=SOURCE_URL,
                extra={"notice_number": notice_number or ""},
            )
        )
    return rows


def _text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


# ---------------------------------------------------------------------------
# Historical backfill (2017-2024) — bundled Wayback capture
# ---------------------------------------------------------------------------
# The live reports page was pruned to 2025+ in early 2025, but its archive
# section had been cumulative: the 2025-01-16 capture carries every notice
# 2017-2024 as labeled <p> entries ("Date Notice Posted: ... | Company: ... |
# County: ... | Affected Workers: ... | Closure/Layoff Date: ... |
# Notice/Type: #N"), plus a 2024 <table> that duplicates the 2024 entries
# (skipped — same notices, same ids). The linked per-notice WARN letter PDFs
# are also pruned from live tn.gov, so raw_notice_url is Wayback-wrapped.

_ARCHIVE_PATH = DATA_DIR / "tn_archive.tar.gz"
_ARCHIVE_TS = "20250116"

_ARCHIVE_POSTED_RE = re.compile(r"Date Notice Posted\s*:")
# Label spellings drift across years: "Company :", "Counties:", and one
# "Notice Type:" (no slash) all appear.
_ARCHIVE_LABEL_RE = re.compile(
    r"(Date Notice Posted|Compan(?:y|ies)|Count(?:y|ies)|Affected Workers|"
    r"Closure/Layoff Date|Notice[/ ]?Type)\s*:\s*([^|]*?)\s*(?=\||$)"
)
_LABEL_KEYS = {
    "Date Notice Posted": "posted",
    "Affected Workers": "workers",
    "Closure/Layoff Date": "effective",
}
_COUNT_RE = re.compile(r"\d[\d,]*")
# First token naming a full date, for free-text effective values like
# "June 30, 2023 to September 30, 2023", "Beginning in February 2020" or
# "March 20,2020": month-day-year, numeric, or month-year.
_DATE_TOKEN_RE = re.compile(
    r"[A-Z][a-z]+ \d{1,2},\s*\d{4}|\d{1,4}/\s*\d{1,2}/\s*\d{2,4}|[A-Z][a-z]+ \d{4}"
)


def tn_archive_files() -> list[tuple[str, bytes]]:
    return load_archive(_ARCHIVE_PATH)


def parse_tn_archive(raw: bytes) -> list[NoticeRow]:
    """Parse the archived reports page's labeled notice entries.

    Some paragraphs glue several entries together, so entries are split on
    the "Date Notice Posted:" boundary of the flattened text rather than per
    <p>. Same-(employer, posted-date) entries — distinct filings with their
    own Notice/Type numbers, usually one per county — would collide on
    ``notice_id`` (TN rows carry no city/zip), so they are merged: counts
    summed, counties joined, earliest closure/layoff date kept.
    """
    soup = BeautifulSoup(raw, "html.parser")
    paras = []
    seen: set[int] = set()
    for node in soup.find_all(string=_ARCHIVE_POSTED_RE):
        p = node.find_parent("p")
        if p is None or id(p) in seen:
            continue
        seen.add(id(p))
        paras.append(p)

    entries: list[dict] = []
    for p in paras:
        text = " ".join(p.get_text(" ", strip=True).split())
        anchors = [
            (" ".join(a.get_text(" ", strip=True).split()), a["href"])
            for a in p.find_all("a", href=True)
        ]
        starts = [m.start() for m in _ARCHIVE_POSTED_RE.finditer(text)]
        for i, start in enumerate(starts):
            end = starts[i + 1] if i + 1 < len(starts) else len(text)
            chunk = text[start:end]
            fields: dict[str, str] = {}
            for label, value in _ARCHIVE_LABEL_RE.findall(chunk):
                if label.startswith("Compan"):
                    key = "company"
                elif label.startswith("Count"):
                    key = "county"
                elif label.startswith("Notice"):
                    key = "notice_type"
                else:
                    key = _LABEL_KEYS[label]
                fields.setdefault(key, value)

            employer = as_str(fields.get("company"))
            # One 2018 entry reads "2018/4/ 27" — drop spaces around slashes.
            posted = as_date(re.sub(r"\s*/\s*", "/", fields.get("posted", "")))
            if not employer or posted is None:
                raise ParseFailed(f"TN archive: unparseable entry {chunk[:120]!r}")
            m = _COUNT_RE.search(fields.get("workers", ""))
            href = next(
                (
                    h
                    for t, h in anchors
                    if t and (t.lower() in employer.lower() or employer.lower() in t.lower())
                ),
                None,
            )
            entries.append(
                {
                    "employer": employer,
                    "posted": posted,
                    "effective": _parse_archive_effective(fields.get("effective", "")),
                    "count": int(m.group().replace(",", "")) if m else None,
                    "county": as_str(fields.get("county")),
                    "notice_number": as_str(fields.get("notice_type")),
                    "href": href,
                }
            )
    if not entries:
        raise ParseFailed("TN archive: no labeled notice entries found")
    return _merge_archive_collisions(entries)


def _parse_archive_effective(value: str) -> date | None:
    """Effective date from free text; ranges/phased lists keep the first
    dated token (one entry's value is a stray worker count — stays None)."""
    d = as_date(value)
    if d is not None:
        return d
    for token in _DATE_TOKEN_RE.findall(value):
        d = as_date(re.sub(r",(?=\d)", ", ", token))
        if d is not None:
            return d
    return None


def _merge_archive_collisions(entries: list[dict]) -> list[NoticeRow]:
    groups: dict[tuple[str, date], list[dict]] = {}
    for e in entries:
        groups.setdefault((" ".join(e["employer"].lower().split()), e["posted"]), []).append(e)

    rows: list[NoticeRow] = []
    for group in groups.values():
        counts = [e["count"] for e in group if e["count"] is not None]
        effectives = [e["effective"] for e in group if e["effective"] is not None]
        counties = list(dict.fromkeys(e["county"] for e in group if e["county"]))
        numbers = [e["notice_number"] for e in group if e["notice_number"]]
        href = next((e["href"] for e in group if e["href"]), None)
        rows.append(
            NoticeRow(
                state="TN",
                employer=group[0]["employer"],
                notice_date=group[0]["posted"],
                effective_date=min(effectives) if effectives else None,
                layoff_count=sum(counts) if counts else None,
                county="; ".join(counties) or None,
                source_url=SOURCE_URL,
                raw_notice_url=_archive_notice_url(href),
                extra={"notice_number": "; ".join(numbers)},
            )
        )
    return rows


def _archive_notice_url(href: str | None) -> str | None:
    if not href:
        return None
    original = href if href.startswith("http") else _BASE_URL + href
    return f"https://web.archive.org/web/{_ARCHIVE_TS}/{original}"


register(TNScraper())
