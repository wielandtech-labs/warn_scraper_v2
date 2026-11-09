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
import functools
import gzip
import io
import re
from collections import Counter
from pathlib import Path

import httpx

from warn_v2.geo.city_centroids import lookup
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
            # `city` is hashed into notice_id, so it keeps the legacy parse; the
            # corrected city goes on the location only (see location_city).
            loc_city = location_city(address_raw)

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
                    location_city=loc_city if loc_city != city else None,
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


# "<head>, NY, <zip>" with the ", NY" and ZIP both optional-ish: the source
# sometimes drops the ZIP ("One Rockwood Road  Sleepy Hollow, NY,").
_HEAD_RE = re.compile(r"^(.*?),?\s*NY\.?,?\s*(?:\d{5}(?:-\d{4})?)?\s*$", re.IGNORECASE)
# A city candidate with these is a list or a street fragment, not one place.
_NOT_A_CITY_RE = re.compile(r"[\d/,;:()&]|branches", re.IGNORECASE)
_MAX_CITY_WORDS = 4
# Street-part words the source sometimes leaves after its double space.
_STREET_WORDS = frozenset({
    "avenue", "ave", "blvd", "boulevard", "building", "bldg", "drive", "floor",
    "fl", "highway", "hwy", "lane", "parkway", "pkwy", "place", "road", "rd",
    "room", "st", "street", "suite", "ste", "turnpike", "unit",
})


def location_city(raw: str | None) -> str | None:
    """Worksite city for the *location*, or None when there is no confident one.

    ``_parse_address`` (whose city feeds notice_id, so it can't change) splits
    at the first double space and, without one, takes every word before ", NY"
    as the city. So "15 W. 43rd  Street  New York, NY" yields "Street  New
    York", and "140 East 45th Street 12th Floor New York, NY" yields "Floor New
    York". Here the city is the text after the *last* double space, or, when
    there is none, the longest trailing run of words that names a known NY
    place: one the source itself spells as a city in a double-spaced address,
    or a Census place. NYC boroughs and neighborhoods aren't Census places,
    which is why the source's own spellings are the main vocabulary.
    """
    m = _HEAD_RE.match((raw or "").strip())
    if not m:
        return None
    head = m.group(1).rstrip(" ,")
    parts = re.split(r"\s{2,}", head)
    if len(parts) > 1:
        return _clean_city(parts[-1].strip())
    words = head.replace(",", " ").split()
    for k in range(min(_MAX_CITY_WORDS, len(words)), 0, -1):
        cand = " ".join(words[-k:])
        if cand.upper() == "NY":
            continue
        if cand.lower() in _known_cities() or lookup("NY", cand) is not None:
            return _clean_city(cand)
    return None


def _is_known_place(name: str) -> bool:
    return name.lower() in _known_cities() or lookup("NY", name) is not None


def _drop_street_words(city: str) -> str:
    """"Street Brooklyn" -> "Brooklyn", but only when what's left is a known place
    ("St James" is a real one, and "James" isn't)."""
    words = city.split()
    while (
        len(words) > 1
        and words[0].rstrip(".,").lower() in _STREET_WORDS
        and _is_known_place(" ".join(words[1:]))
    ):
        words = words[1:]
    return " ".join(words)


def _clean_city(city: str) -> str | None:
    city = _drop_street_words(city)
    if not city or city.upper() == "NY":
        return None
    # Location city matching is case-sensitive, so "MCGRAW" or "brooklyn" must
    # not mint a location beside "McGraw"/"Brooklyn": use the source's usual
    # spelling when it has one, else title-case an all-caps name.
    canonical = _known_cities().get(city.lower())
    if canonical:
        return canonical
    return city.title() if city.isupper() else city


@functools.cache
def _known_cities() -> dict[str, str]:
    """Cities the source writes after a double space (2006-2026): lower -> usual spelling."""
    spellings: dict[str, Counter[str]] = {}
    for rec in csv.DictReader(io.StringIO(ny_history_csv().decode("utf-8-sig"))):
        addr = next((v for k, v in rec.items() if k and k.strip() == "Impacted Site Address"), "")
        m = _HEAD_RE.match((addr or "").strip())
        parts = re.split(r"\s{2,}", m.group(1).rstrip(" ,")) if m else []
        city = parts[-1].strip() if len(parts) > 1 else ""
        if city and not _NOT_A_CITY_RE.search(city) and len(city.split()) <= _MAX_CITY_WORDS:
            spellings.setdefault(city.lower(), Counter())[city] += 1
    spellings.pop("ny", None)
    # Most common spelling, preferring one that isn't all-caps or all-lowercase.
    return {
        low: max(c, key=lambda s: (not (s.isupper() or s.islower()), c[s]))
        for low, c in spellings.items()
    }


register(NYScraper())


# ---------------------------------------------------------------------------
# Historical backfill: the dol.ny.gov dashboard's full crosstab export
# ---------------------------------------------------------------------------
# The live scraper's default Tableau CSV endpoint returns the current year
# only, but the dashboard's "Download -> Crosstab" export carries the full
# 2006-2026 history in the SAME column schema. That export needs a browser
# session, so a one-time normalized snapshot is bundled here (gzipped) and
# ingested via ``backfill-historical --state NY``, parsed by the same
# ``NYScraper.parse`` the live pipeline uses. Refresh: re-download the
# crosstab and regenerate the .gz (see docs/historical-sources.md).

_HISTORY_GZ = Path(__file__).resolve().parent.parent / "data" / "ny_warn_history.csv.gz"


def ny_history_csv() -> bytes:
    """Decompressed UTF-8 CSV of the bundled 2006-2026 crosstab snapshot."""
    return gzip.decompress(_HISTORY_GZ.read_bytes())
