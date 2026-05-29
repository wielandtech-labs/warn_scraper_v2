"""Build ``warn_v2/geo/_data/counties.json.gz`` from the US Census County Gazetteer.

The Census Bureau publishes a free national gazetteer of counties and
county-equivalents with internal-point lat/lon. Run this once (or after a
Census update) and commit the resulting JSON.gz to the repo.

Output key format: ``"{STATE}|{county_normalized}"`` where
``county_normalized = county.lower().strip()`` with legal-type suffixes
(" county", " parish", " borough", etc.) removed.  This matches what WARN
scrapers for KY, MT, and similar states report — e.g. ``"KY|madison"``
instead of ``"KY|madison county"``.

Usage::

    python -m warn_v2.scripts.fetch_county_centroids
    python -m warn_v2.scripts.fetch_county_centroids --year 2024
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
    "{year}_Gazetteer/{year}_Gaz_counties_national.zip"
)
OUT_PATH = (
    Path(__file__).resolve().parents[1] / "geo" / "_data" / "counties.json.gz"
)

# Census NAME fields for counties include a legal-type suffix.
# Strip these so "Madison County" → "madison", matching scraper output.
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


def _fetch(url: str) -> bytes:
    log.info("Fetching %s", url)
    req = Request(url, headers={"User-Agent": "warn_v2-county-fetcher/1.0"})
    with urlopen(req, timeout=120) as resp:
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


def _parse_counties(tsv: str) -> dict[str, list[float]]:
    """Parse the Census Counties Gazetteer TSV.

    Header (tab-separated, first line):
      USPS  GEOID  ANSICODE  NAME  ALAND  AWATER  ALAND_SQMI  AWATER_SQMI
      INTPTLAT  INTPTLONG

    We need: USPS (state), NAME (county name), INTPTLAT, INTPTLONG.
    """
    lines = tsv.splitlines()
    if not lines:
        raise RuntimeError("Empty TSV from Census")

    header = [c.strip().upper() for c in lines[0].split("\t")]
    try:
        i_state = header.index("USPS")
        i_name = header.index("NAME")
        i_lat = header.index("INTPTLAT")
        i_lon = header.index("INTPTLONG")
    except ValueError as e:
        raise RuntimeError(f"Unexpected Census header columns: {header}") from e

    out: dict[str, list[float]] = {}

    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= max(i_state, i_name, i_lat, i_lon):
            continue
        state = cols[i_state].strip().upper()
        name = cols[i_name].strip()
        if not state or not name:
            continue
        try:
            lat = float(cols[i_lat])
            lon = float(cols[i_lon])
        except ValueError:
            continue

        county_norm = _strip_county_suffix(name.lower())
        key = f"{state}|{county_norm}"
        # Counties are unique within a state so no averaging needed,
        # but guard against duplicate rows just in case.
        if key not in out:
            out[key] = [round(lat, 4), round(lon, 4)]

    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--output", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    url = GAZETTEER_URL.format(year=args.year)
    archive = _fetch(url)
    tsv = _extract_txt(archive)
    counties = _parse_counties(tsv)

    if not counties:
        log.error("No county centroids parsed; aborting.")
        return 1

    log.info("Parsed %d county centroids", len(counties))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(counties, fh, separators=(",", ":"), sort_keys=True)
    log.info(
        "Wrote %d county centroids to %s (%.1f KB)",
        len(counties),
        args.output,
        args.output.stat().st_size / 1024,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
