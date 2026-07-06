"""Build ``warn_v2/geo/_data/county_employment.json.gz`` from Census CBP.

County Business Patterns (CBP) publishes annual county-level employment.
This script downloads the complete-county flat file (keyless, unlike the
api.census.gov data API which now requires an API key), keeps the
county-total rows (``naics == "------"``), and joins county names from the
Census Gazetteer (the same file ``fetch_county_centroids.py`` uses, since
the CBP file identifies counties by FIPS only). Run it once per CBP release
(annual, ~18 months after the reference year) and commit the resulting
JSON.gz to the repo.

Output format: ``{"year": <year>, "counties": {key: employment}}`` where
key is ``"{STATE}|{county_normalized}"`` with legal-type suffixes
(" county", " parish", " borough", etc.) removed — the same scheme as
``counties.json.gz`` (centroids), so scraper county strings match.

Usage::

    python -m warn_v2.scripts.fetch_county_employment
    python -m warn_v2.scripts.fetch_county_employment --year 2023
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import logging
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

DEFAULT_YEAR = 2023
CBP_URL = (
    "https://www2.census.gov/programs-surveys/cbp/datasets/"
    "{year}/cbp{yy}co.zip"
)
# County names + USPS state codes come from the gazetteer (GEOID → NAME);
# the gazetteer year need not match the CBP year — county FIPS are stable.
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "{year}_Gazetteer/{year}_Gaz_counties_national.zip"
)
GAZETTEER_YEAR = 2023
OUT_PATH = (
    Path(__file__).resolve().parents[1] / "geo" / "_data" / "county_employment.json.gz"
)

# Same suffix list as fetch_county_centroids.py / geo/county_employment.py.
# Longer/more-specific suffixes first to prevent partial matches.
_COUNTY_SUFFIXES: tuple[str, ...] = (
    " city and borough",
    " census area",
    " municipality",
    " city and county",
    " parish",
    " borough",
    " county",
)

# CBP county-total rows carry this pseudo-NAICS code.
_NAICS_TOTAL = "------"


def _fetch(url: str) -> bytes:
    log.info("Fetching %s", url)
    req = Request(url, headers={"User-Agent": "warn_v2-cbp-fetcher/1.0"})
    with urlopen(req, timeout=300) as resp:
        return resp.read()


def _extract_txt(zip_bytes: bytes, encoding: str = "latin-1") -> str:
    """Extract the first .txt file from a ZIP archive."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".txt")]
        if not names:
            raise RuntimeError("No .txt file found in archive")
        with zf.open(names[0]) as fh:
            return fh.read().decode(encoding)


def _strip_county_suffix(name_lower: str) -> str:
    """Remove the trailing Census legal-type suffix from a lowercased county name."""
    for suffix in _COUNTY_SUFFIXES:
        if name_lower.endswith(suffix):
            return name_lower[: -len(suffix)].strip()
    return name_lower


def _parse_gazetteer(tsv: str) -> dict[str, tuple[str, str]]:
    """Parse the Counties Gazetteer TSV into GEOID → (USPS state, NAME)."""
    lines = tsv.splitlines()
    if not lines:
        raise RuntimeError("Empty gazetteer TSV from Census")

    header = [c.strip().upper() for c in lines[0].split("\t")]
    try:
        i_state = header.index("USPS")
        i_geoid = header.index("GEOID")
        i_name = header.index("NAME")
    except ValueError as e:
        raise RuntimeError(f"Unexpected gazetteer header columns: {header}") from e

    out: dict[str, tuple[str, str]] = {}
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= max(i_state, i_geoid, i_name):
            continue
        state = cols[i_state].strip().upper()
        geoid = cols[i_geoid].strip()
        name = cols[i_name].strip()
        if state and geoid and name:
            out[geoid] = (state, name)
    return out


def _parse_cbp(csv_text: str, geo: dict[str, tuple[str, str]]) -> dict[str, int]:
    """Parse the CBP complete-county CSV, keeping county-total employment.

    Columns used: fipstate, fipscty, naics, emp. Rows are kept only when
    ``naics == "------"`` (all-industries total) and ``emp > 0`` (zero means
    the value was withheld/noise-suppressed).
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        raise RuntimeError("Empty CBP CSV from Census")
    fields = {f.strip().lower() for f in reader.fieldnames}
    missing = {"fipstate", "fipscty", "naics", "emp"} - fields
    if missing:
        raise RuntimeError(f"Unexpected CBP CSV columns; missing {sorted(missing)}")

    out: dict[str, int] = {}
    unmatched = 0

    for row in reader:
        if (row.get("naics") or "").strip() != _NAICS_TOTAL:
            continue
        geoid = (row.get("fipstate") or "").strip() + (row.get("fipscty") or "").strip()
        entry = geo.get(geoid)
        if entry is None:
            unmatched += 1
            continue
        try:
            emp = int(row.get("emp") or "")
        except ValueError:
            continue
        if emp <= 0:
            continue

        state, name = entry
        county_norm = _strip_county_suffix(name.lower())
        key = f"{state}|{county_norm}"
        # Counties are unique within a state; guard against duplicates anyway.
        if key not in out:
            out[key] = emp

    if unmatched:
        log.warning("%d CBP county rows had no gazetteer match (skipped)", unmatched)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    geo = _parse_gazetteer(
        _extract_txt(_fetch(GAZETTEER_URL.format(year=GAZETTEER_YEAR)))
    )
    log.info("Parsed %d gazetteer counties", len(geo))

    cbp_url = CBP_URL.format(year=args.year, yy=args.year % 100)
    counties = _parse_cbp(_extract_txt(_fetch(cbp_url)), geo)

    if not counties:
        log.error("No county employment rows parsed; aborting.")
        return 1

    log.info("Parsed %d county employment bases", len(counties))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(
            {"year": args.year, "counties": counties},
            fh,
            separators=(",", ":"),
            sort_keys=True,
        )
    log.info(
        "Wrote %d county employment bases (CBP %d) to %s (%.1f KB)",
        len(counties),
        args.year,
        args.output,
        args.output.stat().st_size / 1024,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
