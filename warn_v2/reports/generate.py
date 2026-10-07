"""Orchestrate the weekly report data: aggregate → payloads.json + industries.json.

Covers three report groups — per-state, national ("US"), and per-NAICS-sector
scorecards. The weekly run is fully deterministic: it exports each report's
figures as payloads.json. The reports themselves are written on demand by the
/layoff-sentiment Claude Code skill, which reads those payloads from
/api/reports/payloads and commits markdown to warn_v2/reports/published/.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from warn_v2.companies.naics import NAICS_SECTORS
from warn_v2.reports.aggregate import (
    NATIONAL_CODE,
    compute_national_aggregates,
    compute_state_aggregates,
)
from warn_v2.reports.forecast import compute_forecast
from warn_v2.reports.industry import (
    SectorAggregates,
    compute_sector_aggregates,
    scorecard_summary,
)
from warn_v2.states import STATE_NAMES

log = logging.getLogger(__name__)

INDUSTRIES_JSON = "industries.json"
PAYLOADS_JSON = "payloads.json"


def _atomic_write(reports_dir: Path, filename: str, content: str) -> Path:
    """Atomically replace a file — the API serves these files concurrently."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / filename
    tmp = path.with_name(filename + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


def build_state_payload(session: Session, state: str, *, as_of: date | None = None) -> dict:
    """One state's figures: aggregates, a `sufficient` flag, and the 6-month
    forecast when the history clears the lowest forecast ladder tier."""
    agg = compute_state_aggregates(session, state, as_of=as_of)
    payload = agg.to_prompt_payload()
    payload["sufficient"] = agg.sufficient
    forecast = compute_forecast(agg.monthly_full, as_of=agg.as_of)
    if forecast is not None:
        payload["forecast"] = forecast.to_payload()
    return payload


def build_national_payload(
    session: Session, *, as_of: date | None = None, bls: dict | None = None
) -> dict:
    """The US-wide figures. `bls` is an optional fetch_bls_context() result;
    its national block is added as macro context."""
    agg = compute_national_aggregates(session, as_of=as_of)
    payload = agg.to_prompt_payload()
    payload["sufficient"] = agg.sufficient
    forecast = compute_forecast(agg.monthly_full, as_of=agg.as_of)
    if forecast is not None:
        payload["forecast"] = forecast.to_payload()
    if bls and bls.get("national"):
        payload["bls_context"] = bls["national"]
    return payload


def build_industry_payload(
    session: Session, sector: str, *, as_of: date | None = None, bls: dict | None = None
) -> tuple[dict, SectorAggregates]:
    """One sector's figures, plus the aggregates (they feed industries.json).
    This sector's BLS block, if it has CES coverage, is added as context."""
    agg = compute_sector_aggregates(session, sector, as_of=as_of)
    payload = agg.to_prompt_payload()
    payload["sufficient"] = agg.sufficient
    if bls and bls.get("sectors", {}).get(sector):
        payload["bls_context"] = bls["sectors"][sector]
    return payload, agg


def generate_payloads(
    session: Session,
    *,
    reports_dir: Path,
    as_of: date,
    bls: dict | None = None,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Write payloads.json (every STATE_NAMES jurisdiction — the browsable-state
    surface, deliberately wider than the scraper registry — plus US and every
    NAICS sector) and the industries.json scorecard summary."""
    jurisdictions: dict[str, dict] = {}
    for code in sorted(STATE_NAMES):
        jurisdictions[code] = build_state_payload(session, code, as_of=as_of)
    jurisdictions[NATIONAL_CODE] = build_national_payload(session, as_of=as_of, bls=bls)
    industries: dict[str, dict] = {}
    aggs: list[SectorAggregates] = []
    for sector, _, _ in NAICS_SECTORS:
        industries[sector], agg = build_industry_payload(session, sector, as_of=as_of, bls=bls)
        aggs.append(agg)
    if progress:
        for key, payload in [*jurisdictions.items(), *industries.items()]:
            progress(f"{key} sufficient={payload['sufficient']}")
    if not dry_run:
        doc = {
            "schema": 1,
            "as_of": as_of.isoformat(),
            "jurisdictions": jurisdictions,
            "industries": industries,
        }
        _atomic_write(reports_dir, PAYLOADS_JSON, json.dumps(doc, indent=2))
        _atomic_write(
            reports_dir, INDUSTRIES_JSON, json.dumps(scorecard_summary(aggs), indent=2)
        )
    every = [*jurisdictions.values(), *industries.values()]
    return {
        "total": len(every),
        "insufficient": sum(1 for p in every if not p["sufficient"]),
    }
