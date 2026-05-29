"""Build ``warn_v2/geo/_data/places.json.gz`` from the US Census Places Gazetteer.

The Census Bureau publishes a free national gazetteer of Incorporated Places
and Census-Designated Places (CDPs) with internal-point lat/lon. Run this
once (or after a Census update) and commit the resulting JSON.gz to the repo.

Output key format: ``"{STATE}|{city_normalized}"`` where
``city_normalized = city.lower().strip()``.

When multiple Census entries share the same (state, city_normalized) key
(e.g. a city and its CDP have the same name), their coordinates are averaged.

Usage::

    python -m warn_v2.scripts.fetch_city_centroids
    python -m warn_v2.scripts.fetch_city_centroids --year 2024
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
# Census Gazetteer for incorporated places + CDPs (national, all 50 states + DC)
GAZETTEER_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
    "{year}_Gazetteer/{year}_Gaz_place_national.zip"
)
OUT_PATH = (
    Path(__file__).resolve().parents[1] / "geo" / "_data" / "places.json.gz"
)


def _fetch(url: str) -> bytes:
    log.info("Fetching %s", url)
    req = Request(url, headers={"User-Agent": "warn_v2-places-fetcher/1.0"})
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


# Census NAME fields include a legal-type suffix (e.g. "Los Angeles city",
# "Anchorage municipality", "Holtsville cdp").  WARN notices use bare city
# names, so we strip the suffix when building the lookup key.  Longer
# suffixes are listed first to prevent partial matches.
_PLACE_SUFFIXES: tuple[str, ...] = (
    " consolidated government",
    " metro township",
    " municipality",
    " urban county",
    " plantation",
    " township",
    " borough",
    " village",
    " purchase",
    " grant",
    " city",
    " town",
    " cdp",
)


def _strip_place_suffix(name_lower: str) -> str:
    """Remove the trailing Census legal-type suffix from a lowercased place name."""
    for suffix in _PLACE_SUFFIXES:
        if name_lower.endswith(suffix):
            return name_lower[: -len(suffix)].strip()
    return name_lower


def _parse_places(tsv: str) -> dict[str, list[float]]:
    """Parse the Census Places Gazetteer TSV.

    Header (tab-separated, first line):
      USPS  GEOID  ANSICODE  NAME  LSAD  FUNCSTAT  ALAND  AWATER
      ALAND_SQMI  AWATER_SQMI  INTPTLAT  INTPTLONG

    We need: USPS (state), NAME (place name), INTPTLAT, INTPTLONG.

    The Census NAME field includes a legal designation suffix
    (e.g. "Los Angeles city", "Anchorage municipality").  We strip that
    suffix so that the key ``"CA|los angeles"`` matches what WARN notices
    actually report.
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

    # Accumulate sums to average duplicate (state, city_norm) pairs.
    sums: dict[str, list[float]] = {}  # key → [lat_sum, lon_sum, count]

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

        city_norm = _strip_place_suffix(name.lower())
        key = f"{state}|{city_norm}"
        if key in sums:
            sums[key][0] += lat
            sums[key][1] += lon
            sums[key][2] += 1
        else:
            sums[key] = [lat, lon, 1.0]

    out: dict[str, list[float]] = {}
    for key, (lat_sum, lon_sum, count) in sums.items():
        out[key] = [round(lat_sum / count, 4), round(lon_sum / count, 4)]
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
    places = _parse_places(tsv)

    if not places:
        log.error("No place centroids parsed; aborting.")
        return 1

    log.info("Parsed %d place centroids", len(places))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(places, fh, separators=(",", ":"), sort_keys=True)
    log.info(
        "Wrote %d city centroids to %s (%.1f KB)",
        len(places),
        args.output,
        args.output.stat().st_size / 1024,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
