"""Build ``warn_v2/geo/_data/zcta.json.gz`` from the US Census ZCTA gazetteer.

The Census Bureau publishes a free national gazetteer of ZIP Code Tabulation
Areas (ZCTAs) with internal-point lat/lon. Run this once (or after a Census
update) and commit the resulting JSON.gz to the repo.

GeoNames US postal codes are fetched as a supplement to fill in the ~8k ZIP
codes that aren't in the ZCTA dataset (PO-box ZIPs, unique-address ZIPs, etc.).
Census data takes precedence where both sources have a ZIP.

Usage::

    python -m warn_v2.scripts.fetch_zip_centroids
    python -m warn_v2.scripts.fetch_zip_centroids --year 2024
    python -m warn_v2.scripts.fetch_zip_centroids --no-geonames   # Census only
"""
from __future__ import annotations

import argparse
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
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "{year}_Gazetteer/{year}_Gaz_zcta_national.zip"
)
GEONAMES_URL = "https://download.geonames.org/export/zip/US.zip"
OUT_PATH = Path(__file__).resolve().parents[1] / "geo" / "_data" / "zcta.json.gz"


def _fetch(url: str) -> bytes:
    log.info("Fetching %s", url)
    req = Request(url, headers={"User-Agent": "warn_v2-zcta-fetcher/1.0"})
    with urlopen(req, timeout=120) as resp:
        return resp.read()


def _extract_txt(zip_bytes: bytes, name: str | None = None, encoding: str = "latin-1") -> str:
    """Extract a text file from a ZIP archive.

    If *name* is given, extract that specific file.  Otherwise extract the
    first ``.txt`` file found (useful when the archive has exactly one data
    file).
    """
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        if name is not None:
            with zf.open(name) as fh:
                return fh.read().decode(encoding)
        names = [n for n in zf.namelist() if n.endswith(".txt")]
        if not names:
            raise RuntimeError("No .txt file found in archive")
        with zf.open(names[0]) as fh:
            return fh.read().decode(encoding)


def _parse_census(tsv: str) -> dict[str, list[float]]:
    """Parse the Census ZCTA gazetteer TSV.

    Schema (tab-separated, first line is header):
      GEOID  ALAND  AWATER  ALAND_SQMI  AWATER_SQMI  INTPTLAT  INTPTLONG
    """
    out: dict[str, list[float]] = {}
    lines = tsv.splitlines()
    if not lines:
        raise RuntimeError("Empty TSV from Census")
    header = [c.strip().upper() for c in lines[0].split("\t")]
    try:
        i_geoid = header.index("GEOID")
        i_lat = header.index("INTPTLAT")
        i_lon = header.index("INTPTLONG")
    except ValueError as e:
        raise RuntimeError(f"Unexpected Census header columns: {header}") from e

    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= max(i_geoid, i_lat, i_lon):
            continue
        zip5 = cols[i_geoid].strip()
        if not (zip5.isdigit() and len(zip5) == 5):
            continue
        try:
            lat = float(cols[i_lat])
            lon = float(cols[i_lon])
        except ValueError:
            continue
        # Round to 4 decimal places (~11 m precision) to shrink the file.
        out[zip5] = [round(lat, 4), round(lon, 4)]
    return out


def _parse_geonames(tsv: str) -> dict[str, list[float]]:
    """Parse GeoNames US postal codes TSV.

    Schema (tab-separated, NO header line):
      0: country_code  1: postal_code  2: place_name  3: admin_name1
      4: admin_code1   5: admin_name2  6: admin_code2 7: admin_name3
      8: admin_code3   9: latitude    10: longitude  11: accuracy
    """
    # Accumulate lat/lon sums so we can average when a ZIP has multiple places.
    sums: dict[str, list[float]] = {}  # zip5 → [lat_sum, lon_sum, count]

    for line in tsv.splitlines():
        cols = line.split("\t")
        if len(cols) < 11:
            continue
        country = cols[0].strip()
        if country != "US":
            continue
        zip5 = cols[1].strip()
        if not (zip5.isdigit() and len(zip5) == 5):
            continue
        try:
            lat = float(cols[9])
            lon = float(cols[10])
        except ValueError:
            continue
        if zip5 in sums:
            sums[zip5][0] += lat
            sums[zip5][1] += lon
            sums[zip5][2] += 1
        else:
            sums[zip5] = [lat, lon, 1]

    out: dict[str, list[float]] = {}
    for zip5, (lat_sum, lon_sum, count) in sums.items():
        out[zip5] = [round(lat_sum / count, 4), round(lon_sum / count, 4)]
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    parser.add_argument(
        "--no-geonames",
        action="store_true",
        help="Skip GeoNames supplemental fetch (Census ZCTAs only)",
    )
    args = parser.parse_args()

    # --- Census ZCTAs (primary) ---
    census_url = GAZETTEER_URL.format(year=args.year)
    census_archive = _fetch(census_url)
    census_tsv = _extract_txt(census_archive)
    census = _parse_census(census_tsv)
    log.info("Census: %d ZCTA centroids parsed", len(census))

    # --- GeoNames (supplemental, fills in non-ZCTA ZIPs) ---
    geonames: dict[str, list[float]] = {}
    if not args.no_geonames:
        try:
            gn_archive = _fetch(GEONAMES_URL)
            # GeoNames US.zip contains readme.txt + US.txt; request US.txt explicitly.
            gn_tsv = _extract_txt(gn_archive, name="US.txt", encoding="utf-8")
            geonames = _parse_geonames(gn_tsv)
            log.info("GeoNames: %d US ZIP centroids parsed", len(geonames))
        except Exception as exc:
            log.warning("GeoNames fetch failed (%s); using Census data only", exc)

    # --- Merge: GeoNames first, then Census overwrites for accuracy ---
    merged = {**geonames, **census}
    geonames_only = len([z for z in merged if z not in census])
    log.info(
        "Merged: %d total centroids (%d from Census, %d GeoNames-only)",
        len(merged), len(census), geonames_only,
    )

    if not merged:
        log.error("No centroids parsed; aborting.")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(merged, fh, separators=(",", ":"), sort_keys=True)
    log.info(
        "Wrote %d centroids to %s (%.1f KB)",
        len(merged), args.output, args.output.stat().st_size / 1024,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
