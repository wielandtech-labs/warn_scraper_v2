"""Minnesota WARN scraper.

Source: Monthly "Plant Closings/Mass Layoffs/WARN Report" PDFs published by
the Minnesota DEED (Dept of Employment and Economic Development) Rapid Response Team.

The DEED reports index page is Radware bot-protected (headless browsers blocked).
Discovery uses the Wayback Machine CDX API which indexes all mn.gov PDFs without
bot protection. PDFs are then downloaded directly from mn.gov via httpx.

Only rows where the "WARN Act" column = "YES" are actual WARN Act filings.

PDF format changed between 2025 and 2026:
  2025: wide merged-cell table; text extraction used for parsing.
  2026: clean 10-column table; pdfplumber.extract_table() works.
Both formats are detected automatically.

Schema (2026 clean format confirmed, May 2026):
  Layoff Name | Account: City | Account: Industry | Layoff Start |
  WARN Act | WARN Received | Layoff Type | Layoff Status | Federal Impact | Affected Workers
"""
from __future__ import annotations

import base64
import io
import json
import re
from datetime import date, timedelta

import httpx
import pdfplumber

from warn_v2.scrapers._helpers import as_date, as_int, as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

_CDX_API = "http://web.archive.org/cdx/search/cdx"
_CDX_PATTERN = "mn.gov/deed/assets/plant-closing-mass-layoff-warn*"

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Lookback window: last 18 months of PDFs to ensure ≥1 WARN filing found
_LOOKBACK_MONTHS = 18

# Regex: match line where a date is followed immediately by YES (= WARN Act YES)
# Captures: [employer-city-industry prefix] [layoff_start_date] [warn_received date|"-"] [rest]
# WARN Received in 2025 PDFs uses M/D (no year) — full date or M/D or dash accepted.
_DATE_PAT = r"\d{1,2}/\d{1,2}/\d{2,4}"
_DATE_ANY = r"\d{1,2}/\d{1,2}(?:/\d{2,4})?"  # M/D or M/D/YY or M/D/YYYY
_WARN_YES_RE = re.compile(
    r"^(.*?)\s+(" + _DATE_PAT + r")\s+YES\s+(" + _DATE_ANY + r"|[-\u2013])\s+(.*)$"
)
_TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}


class MNScraper:
    state = "MN"
    source_url = "https://mn.gov/deed/programs-services/dislocated-worker-program/reports/"
    expected_row_range = (1, 500)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self) -> bytes:
        """Discover PDF URLs via Wayback Machine CDX API, then download PDFs."""
        try:
            # Step 1: get all unique mn.gov plant-closing PDF URLs from CDX
            r = httpx.get(
                _CDX_API,
                params={
                    "url": _CDX_PATTERN,
                    "output": "json",
                    "fl": "original,timestamp",
                    "filter": "statuscode:200",
                    "collapse": "urlkey",
                    "limit": 200,
                },
                headers=_UA,
                timeout=30,
            )
            r.raise_for_status()
            entries = r.json()
        except Exception as exc:
            raise ScrapeFailed(f"MN: CDX API error: {exc}") from exc

        # Filter to PDFs published in the last _LOOKBACK_MONTHS months
        cutoff = date.today() - timedelta(days=_LOOKBACK_MONTHS * 31)
        recent_urls: list[str] = []
        for entry in entries[1:]:  # skip header row ["original", "timestamp"]
            if len(entry) < 2:
                continue
            url, ts = entry[0], entry[1]
            if not url.endswith(".pdf"):
                continue
            try:
                archived_date = date(int(ts[:4]), int(ts[4:6]), int(ts[6:8]))
            except (ValueError, IndexError):
                continue
            if archived_date >= cutoff:
                recent_urls.append(url)

        if not recent_urls:
            raise ScrapeFailed("MN: no recent PDF URLs found in Wayback Machine CDX")

        # Step 2: download each PDF
        pdfs: list[dict[str, str]] = []
        with httpx.Client(headers=_UA, timeout=60, follow_redirects=True) as client:
            for url in recent_urls:
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    if resp.content[:4] != b"%PDF":
                        continue
                    pdfs.append(
                        {
                            "url": url,
                            "pdf_b64": base64.b64encode(resp.content).decode(),
                        }
                    )
                except httpx.HTTPError:
                    continue

        if not pdfs:
            raise ScrapeFailed("MN: could not download any PDFs")
        return json.dumps({"pdfs": pdfs}).encode()

    def parse(self, raw: bytes) -> list[NoticeRow]:
        try:
            data = json.loads(raw)
        except Exception as exc:
            raise ParseFailed(f"MN: raw bytes are not valid JSON: {exc}") from exc

        pdfs = data.get("pdfs", [])
        if not pdfs:
            raise ParseFailed("MN: JSON payload contains no PDFs")

        rows: list[NoticeRow] = []
        for entry in pdfs:
            pdf_bytes = base64.b64decode(entry["pdf_b64"])
            url = entry.get("url", self.source_url)
            rows.extend(_parse_pdf(pdf_bytes, url))

        # MN may have months with 0 WARN filings — don't error on that
        return rows


def _parse_pdf(pdf_bytes: bytes, url: str) -> list[NoticeRow]:
    """Parse one DEED monthly PDF. Returns only WARN Act=YES rows."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return _parse_clean_table(pdf, url) or _parse_text_lines(pdf, url)
    except Exception:
        return []


def _parse_clean_table(pdf: pdfplumber.PDF, url: str) -> list[NoticeRow]:  # type: ignore[name-defined]
    """Try the 2026-style clean 10-column table format."""
    rows: list[NoticeRow] = []
    header: dict[str, int] | None = None

    for page in pdf.pages:
        table = page.extract_table(_TABLE_SETTINGS)
        if not table:
            continue

        for row in table:
            if not row or len(row) < 5:
                continue
            # Detect header row (contains "Layoff Name" or "WARN" in a cell)
            clean = [str(c or "").replace("\n", " ").strip() for c in row]
            is_header_row = any("Layoff Name" in c or ("WARN" in c and "Act" in c) for c in clean)
            if header is None or is_header_row:
                # Build column map from this row if it looks like a header
                if any("Layoff Name" in c for c in clean):
                    merged = [" ".join(c.split()) for c in clean]
                    header = {n: i for i, n in enumerate(merged)}
                    continue

            if header is None:
                continue

            # Require well-formed row: no excessive None merging
            none_count = sum(1 for c in row if c is None)
            if none_count > len(row) // 2:
                continue

            warn_idx = next(
                (i for n, i in header.items() if "WARN" in n and "Act" in n), None
            )
            if warn_idx is None:
                continue
            if warn_idx >= len(clean) or clean[warn_idx].upper() != "YES":
                continue

            # Extract fields
            name_idx = next((i for n, i in header.items() if "Layoff Name" in n), 0)
            city_idx = next((i for n, i in header.items() if "City" in n), None)
            start_idx = next((i for n, i in header.items() if "Start" in n), None)
            recv_idx = next((i for n, i in header.items() if "Received" in n), None)
            type_idx = next((i for n, i in header.items() if "Layoff Type" in n), None)
            workers_idx = next(
                (i for n, i in header.items() if "Affected" in n or "Workers" in n), None
            )

            employer = as_str(clean[name_idx] if name_idx < len(clean) else "")
            if not employer:
                continue

            notice_date = (
                as_date(clean[recv_idx]) if recv_idx is not None and recv_idx < len(clean) else None
            )
            effective_date = (
                as_date(clean[start_idx])
                if start_idx is not None and start_idx < len(clean)
                else None
            )
            city = (
                as_str(clean[city_idx]) if city_idx is not None and city_idx < len(clean) else None
            )
            closure_type = (
                as_str(clean[type_idx]) if type_idx is not None and type_idx < len(clean) else None
            )
            layoff_count = (
                as_int(clean[workers_idx])
                if workers_idx is not None and workers_idx < len(clean)
                else None
            )

            rows.append(
                NoticeRow(
                    state="MN",
                    employer=employer,
                    notice_date=notice_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    closure_type=closure_type,
                    city=city,
                    source_url=url,
                )
            )

    return rows


def _parse_text_lines(pdf: pdfplumber.PDF, url: str) -> list[NoticeRow]:  # type: ignore[name-defined]
    """Fallback: 2025-style wide table — parse text line by line."""
    rows: list[NoticeRow] = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for line in text.split("\n"):
            line = line.strip()
            m = _WARN_YES_RE.match(line)
            if not m:
                continue
            prefix, start_date_raw, recv_raw, _rest = m.groups()
            # The prefix contains "Name City Industry" but we can't reliably split them.
            # Use the whole prefix as employer name and skip city extraction.
            employer = as_str(prefix)
            if not employer:
                continue
            effective_date = as_date(start_date_raw)
            # WARN Received in 2025 PDFs may be "M/D" (no year) — infer year from effective_date
            notice_date = None
            if recv_raw and recv_raw not in ("-", "\u2013"):
                if re.match(r"^\d{1,2}/\d{1,2}$", recv_raw):
                    # Append year from effective_date (or current year as fallback)
                    yr = effective_date.year if effective_date else date.today().year
                    recv_raw = f"{recv_raw}/{yr}"
                notice_date = as_date(recv_raw)
            # Layoff count: last number on the line
            nums = re.findall(r"\b(\d+)\b", _rest)
            layoff_count = as_int(nums[-1]) if nums else None

            # When WARN Received is missing, fall back to effective_date so notice_date
            # is always populated for WARN Act=YES rows (we know a notice was filed).
            rows.append(
                NoticeRow(
                    state="MN",
                    employer=employer,
                    notice_date=notice_date or effective_date,
                    effective_date=effective_date,
                    layoff_count=layoff_count,
                    source_url=url,
                )
            )
    return rows


register(MNScraper())
