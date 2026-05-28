"""Build ``warn_v2/geo/_data/zcta.json.gz`` from the US Census ZCTA gazetteer.

The Census Bureau publishes a free national gazetteer of ZIP Code Tabulation
Areas (ZCTAs) with internal-point lat/lon. Run this once (or after a Census
update) and commit the resulting JSON.gz to the repo.

Usage::

    python -m warn_v2.scripts.fetch_zip_centroids
    python -m warn_v2.scripts.fetch_zip_centroids --year 2024
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
OUT_PATH = Path(__file__).resolve().parents[1] / "geo" / "_data" / "zcta.json.gz"


def _fetch(url: str) -> bytes:
    log.info("Fetching %s", url)
    req = Request(url, headers={"User-Agent": "warn_v2-zcta-fetcher/1.0"})
    with urlopen(req, timeout=60) as resp:
        return resp.read()


def _extract_tsv(zip_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.endswith(".txt")]
        if not names:
            raise RuntimeError("No .txt file found in Census ZCTA archive")
        with zf.open(names[0]) as fh:
            return fh.read().decode("latin-1")


def _parse(tsv: str) -> dict[str, list[float]]:
    """Parse the Census ZCTA gazetteer.

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


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    url = GAZETTEER_URL.format(year=args.year)
    archive = _fetch(url)
    tsv = _extract_tsv(archive)
    centroids = _parse(tsv)
    if not centroids:
        log.error("No ZCTA rows parsed; aborting.")
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(centroids, fh, separators=(",", ":"), sort_keys=True)
    log.info("Wrote %d centroids to %s (%.1f KB)",
             len(centroids), args.output, args.output.stat().st_size / 1024)
    return 0


if __name__ == "__main__":
    sys.exit(main())
