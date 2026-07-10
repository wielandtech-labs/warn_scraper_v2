"""Official BLS employment context for the national and industry narratives.

Fetches Current Employment Statistics (CES) payroll levels and the CPS
unemployment rate from the BLS public API and turns them into a compact
`bls_context` payload block: month-over-month payroll change (thousands,
seasonally adjusted) keyed by "YYYY-MM", so the LLM can situate WARN layoff
trends against the official jobs backdrop without doing any arithmetic.

Strictly fail-open: any API problem logs a warning and returns None, and the
reports render exactly as they did before this module existed. Unkeyed API
limits (25 queries/day, 10 series/query) comfortably cover the weekly run's
two requests; set BLS_API_KEY for headroom if that ever changes.
"""
from __future__ import annotations

import logging
import os
from datetime import date
from itertools import pairwise

import httpx

log = logging.getLogger(__name__)

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# All employees (thousands, seasonally adjusted), total nonfarm.
NATIONAL_PAYROLL_SERIES = "CES0000000001"
# Unemployment rate (percent, seasonally adjusted).
UNEMPLOYMENT_SERIES = "LNS14000000"

# NAICS sector id -> (CES supersector employment series, CES industry name).
# CES supersectors are broader than 2-digit NAICS in places (e.g. NAICS 54/55/56
# all roll into "Professional and business services") — the payload carries the
# CES name so the narrative attributes figures to the right aggregate. NAICS 11
# (Agriculture) has no CES coverage. All series ids verified against the live
# API 2026-07-10.
SECTOR_CES_SERIES: dict[str, tuple[str, str]] = {
    "21": ("CES1000000001", "Mining and logging"),
    "22": ("CES4422000001", "Utilities"),
    "23": ("CES2000000001", "Construction"),
    "31-33": ("CES3000000001", "Manufacturing"),
    "42": ("CES4142000001", "Wholesale trade"),
    "44-45": ("CES4200000001", "Retail trade"),
    "48-49": ("CES4300000001", "Transportation and warehousing"),
    "51": ("CES5000000001", "Information"),
    "52": ("CES5500000001", "Financial activities"),
    "53": ("CES5500000001", "Financial activities"),
    "54": ("CES6000000001", "Professional and business services"),
    "55": ("CES6000000001", "Professional and business services"),
    "56": ("CES6000000001", "Professional and business services"),
    "61": ("CES6500000001", "Private education and health services"),
    "62": ("CES6500000001", "Private education and health services"),
    "71": ("CES7000000001", "Leisure and hospitality"),
    "72": ("CES7000000001", "Leisure and hospitality"),
    "81": ("CES8000000001", "Other services"),
    "92": ("CES9000000001", "Government"),
}

_SOURCE_NOTE = (
    "BLS Current Employment Statistics, all employees, seasonally adjusted; "
    "values are month-over-month payroll changes in thousands of jobs"
)

# Unkeyed API limit; a registration key raises it to 50.
_MAX_SERIES_PER_QUERY = 10


def _fetch_series(
    client: httpx.Client, series_ids: list[str], start_year: int, end_year: int
) -> dict[str, dict[str, float]]:
    """Return {series_id: {"YYYY-MM": value}} for the requested span."""
    out: dict[str, dict[str, float]] = {}
    key = os.getenv("BLS_API_KEY")
    chunk_size = 50 if key else _MAX_SERIES_PER_QUERY
    for i in range(0, len(series_ids), chunk_size):
        body: dict = {
            "seriesid": series_ids[i : i + chunk_size],
            "startyear": str(start_year),
            "endyear": str(end_year),
        }
        if key:
            body["registrationkey"] = key
        resp = client.post(BLS_API_URL, json=body)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API status {payload.get('status')}: "
                               f"{payload.get('message')}")
        for series in payload.get("Results", {}).get("series", []):
            points: dict[str, float] = {}
            for row in series.get("data", []):
                period = row.get("period", "")
                if not period.startswith("M") or period == "M13":  # M13 = annual
                    continue
                try:
                    value = float(row["value"])
                except ValueError:  # BLS placeholder for unavailable, e.g. "-"
                    continue
                points[f"{row['year']}-{period[1:]}"] = value
            out[series["seriesID"]] = points
    return out


def _monthly_changes(levels: dict[str, float], months: int) -> dict[str, float]:
    """Month-over-month deltas for the latest `months` months with a prior."""
    changes = {
        m: round(levels[m] - levels[prev], 1) for prev, m in pairwise(sorted(levels))
    }
    return dict(sorted(changes.items())[-months:])


def fetch_bls_context(
    sectors: list[str],
    *,
    as_of: date | None = None,
    months: int = 12,
    timeout_s: float = 20.0,
) -> dict | None:
    """Build the bls_context payload for the national report and the given
    sectors. Returns None on any failure — narratives simply omit the macro
    sentence, exactly as before this feature."""
    as_of = as_of or date.today()
    wanted = {NATIONAL_PAYROLL_SERIES, UNEMPLOYMENT_SERIES}
    wanted.update(SECTOR_CES_SERIES[s][0] for s in sectors if s in SECTOR_CES_SERIES)
    try:
        with httpx.Client(timeout=timeout_s) as client:
            # One extra look-back year so January still gets a December prior.
            levels = _fetch_series(
                client, sorted(wanted), as_of.year - 2, as_of.year
            )
    except Exception as exc:  # strictly fail-open by design
        log.warning("BLS context unavailable (%s); narrating without it", exc)
        return None

    payroll = levels.get(NATIONAL_PAYROLL_SERIES, {})
    if not payroll:
        log.warning("BLS context empty for national payrolls; narrating without it")
        return None
    national: dict = {
        "source": _SOURCE_NOTE,
        "industry": "Total nonfarm",
        "payroll_change_thousands_by_month": _monthly_changes(payroll, months),
    }
    unemployment = levels.get(UNEMPLOYMENT_SERIES, {})
    if unemployment:
        latest = max(unemployment)
        national["unemployment_rate"] = {"month": latest, "value": unemployment[latest]}

    sector_blocks: dict[str, dict] = {}
    for sector in sectors:
        mapping = SECTOR_CES_SERIES.get(sector)
        if mapping is None:
            continue  # e.g. NAICS 11 — no CES coverage
        series_id, ces_name = mapping
        series_levels = levels.get(series_id, {})
        if not series_levels:
            continue
        sector_blocks[sector] = {
            "source": _SOURCE_NOTE,
            "industry": ces_name,
            "industry_note": (
                "closest BLS industry; broader than this NAICS sector where "
                "several sectors share a BLS aggregate"
            ),
            "payroll_change_thousands_by_month": _monthly_changes(
                series_levels, months
            ),
        }
    return {"national": national, "sectors": sector_blocks}
