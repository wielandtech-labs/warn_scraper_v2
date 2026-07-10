"""Build ``warn_v2/labor/_data/oews_staffing.json.gz`` from BLS OEWS.

The BLS Occupational Employment and Wage Statistics program publishes
national industry-specific occupation estimates (annual, May reference
month): for each NAICS industry, the detailed SOC occupations it employs
and each occupation's percent of the industry's employment (``PCT_TOTAL``).
This script downloads the "national industry-specific" research file
(``oesm{yy}in4.zip``), parses the sector / 3-digit / 4-digit workbooks, and
keeps each industry's top detailed occupations — the staffing pattern the
radar applies to a notice's ``layoff_count`` to estimate the occupation mix
of an affected cohort. Run it once per OEWS release (annual, ~May of the
following year) and commit the resulting JSON.gz to the repo.

Notes on the source data:

- bls.gov 403s ``urllib``/plain ``curl`` (Akamai TLS fingerprinting), so the
  download uses ``curl_cffi`` with browser impersonation.
- The sector workbook keys industries by the same range-form sector ids as
  ``warn_v2/companies/naics.py`` ("31-33", "44-45", "48-49"); the 3-/4-digit
  workbooks zero-pad NAICS codes to 6 chars ("311900" = industry group 3119).
- A few OEWS rows aggregate several NAICS industries under one combo code;
  keying by the leading digits treats them as their leading industry — an
  acceptable approximation for a statistical prior.
- Suppressed estimates appear as the string ``"**"`` and are skipped.

Output format::

    {"vintage": "May 2025",
     "occupations": {"51-4041": "Machinists", ...},
     "levels": {
       "sector": {"31-33": {"title": ..., "coverage": 61.3,
                            "occs": [["53-7062", 6.1], ...]}},
       "naics3": {"311": {...}},
       "naics4": {"3119": {...}}}}

Usage::

    python -m warn_v2.scripts.fetch_oews_staffing
    python -m warn_v2.scripts.fetch_oews_staffing --year 2025
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import logging
import sys
import zipfile
from collections.abc import Iterable
from pathlib import Path

from warn_v2.companies.naics import SECTOR_NAME

log = logging.getLogger(__name__)

DEFAULT_YEAR = 2025
OEWS_URL = "https://www.bls.gov/oes/special-requests/oesm{yy}in4.zip"
OUT_PATH = (
    Path(__file__).resolve().parents[1] / "labor" / "_data" / "oews_staffing.json.gz"
)

# (zip-member name fragment, output level key, NAICS key length or None for
# sector ids kept as-is). The archive also ships "_owner_" ownership splits
# — the fragment match below excludes them.
_SHEETS: tuple[tuple[str, str, int | None], ...] = (
    ("natsector_", "sector", None),
    ("nat3d_", "naics3", 3),
    ("nat4d_", "naics4", 4),
)

# Pruning: keep each industry's top occupations by employment share. 12 rows
# at >=0.5% keeps the bundle tiny (~tens of KB gzipped) while covering
# 50-70% of a typical industry's employment.
_TOP_N = 12
_MIN_PCT = 0.5

_REQUIRED_COLUMNS = ("NAICS", "NAICS_TITLE", "O_GROUP", "OCC_CODE", "OCC_TITLE", "PCT_TOTAL")


def _fetch(url: str) -> bytes:
    # bls.gov rejects urllib/plain curl via TLS fingerprinting; impersonate
    # a browser with curl_cffi (already a scraper dependency).
    from curl_cffi import requests as cc_requests

    log.info("Fetching %s", url)
    resp = cc_requests.get(url, impersonate="chrome", timeout=300)
    resp.raise_for_status()
    return resp.content


def _industry_key(naics: object, key_len: int | None) -> str | None:
    """Derive the bundle key for a row's NAICS value, or None to skip.

    Sector workbook (``key_len is None``): the value must be a known sector
    id (this drops the "99" government row and any odd aggregates). Digit
    workbooks: the zero-padded code's leading ``key_len`` digits.
    """
    code = str(naics).strip() if naics is not None else ""
    if key_len is None:
        return code if code in SECTOR_NAME else None
    if not code.isdigit() or len(code) < key_len:
        return None
    return code[:key_len]


def _parse_sheet(
    rows: Iterable[tuple], key_len: int | None
) -> tuple[dict[str, dict], dict[str, str]]:
    """Parse one OEWS workbook's rows into pruned staffing patterns.

    ``rows`` are value tuples with a header row first (the shape
    ``openpyxl`` yields with ``values_only=True``). Returns
    ``(industries, occupation_titles)`` where industries maps the bundle key
    to ``{"title", "coverage", "occs": [[soc, pct], ...]}``.
    """
    it = iter(rows)
    try:
        header = [str(c).strip().upper() if c is not None else "" for c in next(it)]
    except StopIteration:
        raise RuntimeError("Empty OEWS worksheet") from None
    try:
        idx = {col: header.index(col) for col in _REQUIRED_COLUMNS}
    except ValueError as e:
        raise RuntimeError(f"Unexpected OEWS columns: {header}") from e

    raw: dict[str, dict] = {}
    titles: dict[str, str] = {}
    for row in it:
        if len(row) <= max(idx.values()):
            continue
        if str(row[idx["O_GROUP"]] or "").strip().lower() != "detailed":
            continue
        key = _industry_key(row[idx["NAICS"]], key_len)
        if key is None:
            continue
        try:
            pct = float(row[idx["PCT_TOTAL"]])  # suppressed values ("**") raise
        except (TypeError, ValueError):
            continue
        if pct <= 0:
            continue
        soc = str(row[idx["OCC_CODE"]] or "").strip()
        occ_title = str(row[idx["OCC_TITLE"]] or "").strip()
        if not soc or not occ_title:
            continue
        entry = raw.setdefault(
            key, {"title": str(row[idx["NAICS_TITLE"]] or "").strip(), "occs": []}
        )
        entry["occs"].append((soc, occ_title, pct))

    industries: dict[str, dict] = {}
    for key, entry in raw.items():
        top = sorted(entry["occs"], key=lambda o: o[2], reverse=True)[:_TOP_N]
        top = [(soc, title, round(pct, 2)) for soc, title, pct in top if pct >= _MIN_PCT]
        if not top:
            continue
        for soc, title, _pct in top:
            titles.setdefault(soc, title)
        industries[key] = {
            "title": entry["title"],
            "coverage": round(sum(pct for _s, _t, pct in top), 1),
            "occs": [[soc, pct] for soc, _t, pct in top],
        }
    return industries, titles


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    import openpyxl

    zip_bytes = _fetch(OEWS_URL.format(yy=args.year % 100))
    levels: dict[str, dict[str, dict]] = {}
    occupations: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for fragment, level, key_len in _SHEETS:
            names = [
                n
                for n in zf.namelist()
                if fragment in Path(n).name.lower()
                and "owner" not in Path(n).name.lower()
                and n.endswith(".xlsx")
            ]
            if len(names) != 1:
                raise RuntimeError(f"Expected one {fragment}*.xlsx member, found {names}")
            log.info("Parsing %s", names[0])
            wb = openpyxl.load_workbook(
                io.BytesIO(zf.read(names[0])), read_only=True, data_only=True
            )
            rows = wb.worksheets[0].iter_rows(values_only=True)
            industries, titles = _parse_sheet(rows, key_len)
            wb.close()
            log.info("Kept %d %s industries", len(industries), level)
            levels[level] = industries
            occupations.update(titles)

    if not levels.get("sector") or not levels.get("naics4"):
        log.error("Parsed no sector or 4-digit industries; aborting.")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(
            {"vintage": f"May {args.year}", "occupations": occupations, "levels": levels},
            fh,
            separators=(",", ":"),
            sort_keys=True,
        )
    log.info(
        "Wrote %d occupations across %d/%d/%d sector/3d/4d industries "
        "(OEWS May %d) to %s (%.1f KB)",
        len(occupations),
        len(levels["sector"]),
        len(levels["naics3"]),
        len(levels["naics4"]),
        args.year,
        args.output,
        args.output.stat().st_size / 1024,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
