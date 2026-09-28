"""Official BLS employment context for the national and industry narratives.

Turns CES payroll levels and the CPS unemployment rate into a compact
`bls_context` payload block: month-over-month payroll change (thousands,
seasonally adjusted) keyed by "YYYY-MM", so the LLM can situate WARN layoff
trends against the official jobs backdrop without doing any arithmetic.

The HTTP client lives in `warn_v2.labor.bls_api` and the series ids in
`warn_v2.labor.catalog`, shared with the `fetch-bls` ingestion job that backs
the site's indicator charts. This module keeps only the narrative shaping.

Strictly fail-open: any API problem logs a warning and returns None, and the
reports render exactly as they did before this module existed. That is the
opposite of the ingester, which raises — there, fetching is the whole job.
"""
from __future__ import annotations

import logging
from datetime import date
from itertools import pairwise

import httpx

from warn_v2.labor.bls_api import BLS_API_URL, fetch_series
from warn_v2.labor.catalog import (
    NATIONAL_PAYROLL_SERIES,
    SECTOR_CES_SERIES,
    US_U3_SERIES,
)

log = logging.getLogger(__name__)

# Re-exported for callers and tests that predate the move into warn_v2.labor.
UNEMPLOYMENT_SERIES = US_U3_SERIES

__all__ = [
    "BLS_API_URL",
    "NATIONAL_PAYROLL_SERIES",
    "SECTOR_CES_SERIES",
    "UNEMPLOYMENT_SERIES",
    "fetch_bls_context",
]

_SOURCE_NOTE = (
    "BLS Current Employment Statistics, all employees, seasonally adjusted; "
    "values are month-over-month payroll changes in thousands of jobs"
)


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
            levels = fetch_series(
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
