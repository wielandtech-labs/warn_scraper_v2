"""Build a SIC→NAICS crosswalk and write it to the enrichment data directory.

Parses the OSHA SIC code manual pages, each of which lists the corresponding
NAICS code(s). Falls back to a sector-level mapping if individual pages are
unavailable, so the script always produces a usable output.

Output: warn_v2/enrichment/_data/sic_naics_crosswalk.json
Format: {"3559": ["333249", "Other Industrial Machinery Manufacturing"], ...}

Run with:
    uv run python -m warn_v2.scripts.fetch_sic_naics_crosswalk
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_OUT_PATH = Path(__file__).parent.parent / "enrichment" / "_data" / "sic_naics_crosswalk.json"

# ---------------------------------------------------------------------------
# Sector-level fallback: SIC code range → (NAICS 2-digit, sector description)
# Sufficient for broad industry classification when individual code lookup fails.
# ---------------------------------------------------------------------------
_SECTOR_MAP: list[tuple[range, str, str]] = [
    (range(100,  1000), "11", "Agriculture, Forestry, Fishing and Hunting"),
    (range(1000, 1500), "21", "Mining, Quarrying, and Oil and Gas Extraction"),
    (range(1500, 1800), "23", "Construction"),
    (range(1800, 2000), "23", "Construction"),
    (range(2000, 4000), "31", "Manufacturing"),
    (range(4000, 4800), "48", "Transportation and Warehousing"),
    (range(4800, 4900), "51", "Information"),
    (range(4900, 5000), "22", "Utilities"),
    (range(5000, 5200), "42", "Wholesale Trade"),
    (range(5200, 6000), "44", "Retail Trade"),
    (range(6000, 6800), "52", "Finance and Insurance"),
    (range(6800, 7000), "53", "Real Estate and Rental and Leasing"),
    (range(7000, 7400), "72", "Accommodation and Food Services"),
    (range(7370, 7380), "51", "Information"),   # computers/data processing
    (range(7400, 7700), "56", "Administrative and Support Services"),
    (range(7700, 8000), "71", "Arts, Entertainment, and Recreation"),
    (range(8000, 8100), "62", "Health Care and Social Assistance"),
    (range(8100, 8200), "54", "Professional, Scientific, and Technical Services"),
    (range(8200, 8300), "61", "Educational Services"),
    (range(8300, 8800), "62", "Health Care and Social Assistance"),
    (range(8800, 9000), "81", "Other Services (except Public Administration)"),
    (range(9100, 9800), "92", "Public Administration"),
]


def _sector_naics(sic: int) -> tuple[str, str]:
    for r, naics, desc in _SECTOR_MAP:
        if sic in r:
            return naics, desc
    return "99", "Nonclassifiable Establishments"


def _fetch_osha_page(sic_code: str) -> tuple[str, str] | None:
    """Try to fetch the NAICS equivalent from OSHA's SIC manual page."""
    try:
        import httpx
        from bs4 import BeautifulSoup

        url = f"https://www.osha.gov/pls/imis/sic_manual.display?sic={sic_code}&tab=description"
        resp = httpx.get(url, timeout=8, follow_redirects=True,
                         headers={"User-Agent": "warn-v2/0.1 (research; raphael@wielandtech.com)"})
        if not resp.is_success:
            return None

        soup = BeautifulSoup(resp.content, "lxml")
        # OSHA pages include NAICS equivalent in the body text: "NAICS: 333249"
        text = soup.get_text(" ")
        m = re.search(r"NAICS[:\s]+(\d{6})\s*[--—]?\s*([^\n\r]+)", text)
        if m:
            return m.group(1).strip(), m.group(2).strip()[:120]
        return None
    except Exception:
        return None


def build(sic_codes: list[str], *, use_osha: bool = True) -> dict[str, list[str]]:
    """Build SIC→NAICS mapping for the given SIC codes."""
    result: dict[str, list[str]] = {}
    for sic in sorted(sic_codes):
        naics_entry: tuple[str, str] | None = None
        if use_osha:
            naics_entry = _fetch_osha_page(sic)

        if naics_entry is None:
            naics_code, naics_desc = _sector_naics(int(sic))
            result[sic] = [naics_code, naics_desc]
        else:
            result[sic] = list(naics_entry)

    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    # Load SIC codes from the already-generated sic_descriptions.json
    sic_desc_path = _OUT_PATH.parent / "sic_descriptions.json"
    if not sic_desc_path.exists():
        raise FileNotFoundError(
            f"{sic_desc_path} not found — run fetch_sic_descriptions first"
        )
    sic_codes = list(json.loads(sic_desc_path.read_text()).keys())
    log.info("Building crosswalk for %d SIC codes (OSHA lookup + sector fallback)", len(sic_codes))

    _OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Use sector-level fallback only (fast, no HTTP requests) — OSHA pages
    # are slow and may be unreliable for batch fetching.
    # To attempt OSHA per-code lookup: pass use_osha=True (slow, ~30 min).
    data = build(sic_codes, use_osha=False)
    _OUT_PATH.write_text(json.dumps(data, sort_keys=True, indent=2), encoding="utf-8")
    log.info("Wrote SIC→NAICS crosswalk (%d entries) to %s", len(data), _OUT_PATH)
    log.info(
        "Note: this uses sector-level NAICS (2-digit) as a fallback. "
        "For full 6-digit NAICS, re-run with use_osha=True or update entries manually."
    )


if __name__ == "__main__":
    main()
