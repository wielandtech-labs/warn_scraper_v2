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
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from urllib.parse import quote

import httpx

from warn_v2.scrapers._helpers import as_str
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import register

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
