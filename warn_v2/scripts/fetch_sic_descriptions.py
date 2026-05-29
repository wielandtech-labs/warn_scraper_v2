"""Fetch SIC code descriptions from SEC EDGAR and write to enrichment data dir.

Parses the canonical SEC SIC code list at:
    https://www.sec.gov/info/edgar/siccodes.htm

Output: warn_v2/enrichment/_data/sic_descriptions.json
Format: {"3559": "Special Industry Machinery, NEC", ...}

Run with:
    uv run python -m warn_v2.scripts.fetch_sic_descriptions
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

_SOURCE_URL = "https://www.sec.gov/info/edgar/siccodes.htm"
_OUT_PATH = Path(__file__).parent.parent / "enrichment" / "_data" / "sic_descriptions.json"


def fetch() -> dict[str, str]:
    """Download and parse SIC descriptions from SEC EDGAR."""
    log.info("Fetching SIC descriptions from %s", _SOURCE_URL)
    resp = httpx.get(_SOURCE_URL, timeout=30, follow_redirects=True,
                     headers={"User-Agent": "warn-v2/0.1 (research; raphael@wielandtech.com)"})
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "lxml")
    result: dict[str, str] = {}

    # The page has a table with SIC code and description columns.
    # Rows look like: | 0100 | Agriculture Production - Crops |
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        code = cells[0].get_text(strip=True)
        desc = cells[1].get_text(strip=True)
        if re.fullmatch(r"\d{4}", code) and desc:
            result[code] = desc

    log.info("Parsed %d SIC descriptions", len(result))
    if len(result) < 400:
        raise RuntimeError(f"Expected ≥400 SIC codes, got {len(result)} — page format may have changed")
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = fetch()
    _OUT_PATH.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
    log.info("Wrote %d SIC descriptions to %s", len(data), _OUT_PATH)


if __name__ == "__main__":
    main()
