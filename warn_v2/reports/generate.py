"""Orchestrate report generation: aggregate → render → write.

Covers three report groups — per-state, national ("US"), and per-NAICS-sector
scorecards. The weekly run is fully deterministic: it refreshes the figures,
and exports each report's figures as payloads.json. The written analysis is
produced on demand by the /layoff-sentiment Claude Code skill, which reads
those payloads from /api/reports/payloads.
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
    compute_national_aggregates,
    compute_state_aggregates,
)
from warn_v2.reports.forecast import compute_forecast
from warn_v2.reports.industry import (
    SectorAggregates,
    compute_sector_aggregates,
    scorecard_summary,
)
from warn_v2.reports.render import render_industry_report, render_report
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


def write_report(reports_dir: Path, state: str, content: str) -> Path:
    return _atomic_write(reports_dir, f"{state}.md", content)


def write_payloads(
    reports_dir: Path, *, as_of: date, jurisdictions: dict, industries: dict
) -> Path:
    """payloads.json: every report's figures, for the /layoff-sentiment skill."""
    doc = {
        "schema": 1,
        "as_of": as_of.isoformat(),
        "jurisdictions": jurisdictions,
        "industries": industries,
    }
    return _atomic_write(reports_dir, PAYLOADS_JSON, json.dumps(doc, indent=2))


def _status(sufficient: bool) -> str:
    return "pending" if sufficient else "insufficient_data"


def generate_state_report(
    session: Session,
    state: str,
    *,
    as_of: date | None = None,
) -> tuple[str, str, dict]:
    """Build one state's report. Returns (markdown, status, payload) where
    status is pending | insufficient_data."""
    agg = compute_state_aggregates(session, state, as_of=as_of)
    forecast = compute_forecast(agg.monthly_full, as_of=agg.as_of)
    payload = agg.to_prompt_payload()
    payload["sufficient"] = agg.sufficient
    if forecast is not None:
        payload["forecast"] = forecast.to_payload()
    status = _status(agg.sufficient)
    content = render_report(agg, None, narrative_status=status, forecast=forecast)
    return content, status, payload


def generate_national_report(
    session: Session,
    *,
    as_of: date | None = None,
    bls: dict | None = None,
) -> tuple[str, str, dict]:
    """Build the US-wide report. Same return shape as generate_state_report.
    `bls` is an optional fetch_bls_context() result; its national block is
    added to the payload as macro context (never to the tables)."""
    agg = compute_national_aggregates(session, as_of=as_of)
    forecast = compute_forecast(agg.monthly_full, as_of=agg.as_of)
    payload = agg.to_prompt_payload()
    payload["sufficient"] = agg.sufficient
    if forecast is not None:
        payload["forecast"] = forecast.to_payload()
    if bls and bls.get("national"):
        payload["bls_context"] = bls["national"]
    status = _status(agg.sufficient)
    content = render_report(agg, None, narrative_status=status, forecast=forecast)
    return content, status, payload


def generate_industry_report(
    session: Session,
    sector: str,
    *,
    as_of: date | None = None,
    bls: dict | None = None,
) -> tuple[str, str, dict, SectorAggregates]:
    """Build one sector's scorecard. Returns (markdown, status, payload,
    aggregates) — the aggregates feed the industries.json summary. `bls` is
    an optional fetch_bls_context() result; this sector's block (if the
    sector has CES coverage) is added to the payload."""
    agg = compute_sector_aggregates(session, sector, as_of=as_of)
    payload = agg.to_prompt_payload()
    payload["sufficient"] = agg.sufficient
    if bls and bls.get("sectors", {}).get(sector):
        payload["bls_context"] = bls["sectors"][sector]
    status = _status(agg.sufficient)
    content = render_industry_report(agg, None, narrative_status=status)
    return content, status, payload, agg


def generate_reports(
    session: Session,
    *,
    reports_dir: Path,
    states: list[str] | None = None,
    dry_run: bool = False,
    as_of: date | None = None,
    payloads: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Generate reports for `states` (default: every STATE_NAMES jurisdiction —
    the browsable-state surface, deliberately wider than the scraper registry so
    states with historical data but a blocked scraper still get a report).
    Each report's payload is stored in `payloads` (keyed by code) if given."""
    targets = [s.upper() for s in states] if states else sorted(STATE_NAMES)
    counters = {"generated": 0, "insufficient": 0, "total": len(targets)}
    for code in targets:
        content, status, payload = generate_state_report(session, code, as_of=as_of)
        if payloads is not None:
            payloads[code] = payload
        if status == "insufficient_data":
            counters["insufficient"] += 1
        if not dry_run:
            write_report(reports_dir, code, content)
        counters["generated"] += 1
        if progress:
            progress(f"{code} status={status} chars={len(content)}")
    return counters


def generate_industry_reports(
    session: Session,
    *,
    reports_dir: Path,
    sectors: list[str] | None = None,
    dry_run: bool = False,
    as_of: date | None = None,
    bls: dict | None = None,
    payloads: dict | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Generate scorecards for `sectors` (default: every NAICS sector). The
    industries.json summary is rewritten only on a full default run — a
    targeted --industry run must not shrink it to one entry."""
    targets = sectors if sectors is not None else [sid for sid, _, _ in NAICS_SECTORS]
    counters = {"generated": 0, "insufficient": 0, "total": len(targets)}
    aggs: list[SectorAggregates] = []
    for sector in targets:
        content, status, payload, agg = generate_industry_report(
            session, sector, as_of=as_of, bls=bls
        )
        aggs.append(agg)
        if payloads is not None:
            payloads[sector] = payload
        if status == "insufficient_data":
            counters["insufficient"] += 1
        if not dry_run:
            _atomic_write(reports_dir, f"industry_{sector}.md", content)
        counters["generated"] += 1
        if progress:
            progress(f"industry {sector} status={status} chars={len(content)}")
    if sectors is None and not dry_run:
        _atomic_write(
            reports_dir, INDUSTRIES_JSON, json.dumps(scorecard_summary(aggs), indent=2)
        )
    return counters
