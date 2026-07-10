"""Orchestrate report generation: aggregate → narrate → render → write.

Covers three report groups — per-state, national ("US"), and per-NAICS-sector
scorecards. A narrative failure for one report degrades it to figures-only and
never aborts the run — the deterministic data is refreshed regardless, and the
next weekly run self-heals. Callers decide the exit code from the returned
counters (see the sentiment-report CLI command).
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
from warn_v2.reports.industry import (
    SectorAggregates,
    compute_sector_aggregates,
    scorecard_summary,
)
from warn_v2.reports.ollama import NarrativeClient, OllamaUnavailable
from warn_v2.reports.render import render_industry_report, render_report
from warn_v2.states import STATE_NAMES

log = logging.getLogger(__name__)

INDUSTRIES_JSON = "industries.json"

SYSTEM_PROMPT = """\
You write the Sentiment section of a weekly WARN Act layoff report for one US state.

The user message is a JSON object of pre-computed figures:
- totals: notices and job losses in the current 90-day window vs the prior
  90-day window (short-term momentum).
- same_window_last_year: the same 90-day window one year earlier — the
  seasonal baseline for the current window.
- year_over_year: trailing 12 months vs the 12 months before (long-run trend).
- pct_change: pre-computed percent changes for those three comparisons. A
  null percent means the earlier figure was zero, so no percentage exists —
  describe that as "no comparable activity was recorded", never as a rise.
- top_counties and top_sectors: current vs prior window per row, each with
  delta_layoffs and pct_change (null = nothing in the prior window).
- monthly: the last 12 months; layoffs_year_earlier is the same calendar
  month one year before.
- naics_coverage_pct.

Structure the prose in three short movements:
1. Headline: current-window job losses with BOTH comparisons — vs the prior
   window (momentum) and vs the same window last year (seasonally comparable
   change). If the two point in different directions, say so plainly; use the
   trailing-12-month totals for the long-run picture.
2. Geography: the counties where job losses are concentrated, rising, or easing.
3. Industry: the same for sectors.

Hard rules:
- Use ONLY numbers present in the JSON. Never compute, extrapolate, or invent
  figures, counties, industries, companies, or causes. Cite percentages only
  from the pct_change fields.
- 150-300 words of plain prose. No headings, no bullet lists, no tables.
- If naics_coverage_pct is below 50, caveat that industry figures cover only a
  minority of notices.
- Every layoff figure counts workers losing their jobs. Refer to them as job
  losses; an increase is bad news and a decrease is a sign of relief.
- The words "add", "added", "grow", "grew", "gain", and "gained" are BANNED
  from your output in any form, even about job losses. For a rise write
  "rose", "climbed", "increased", or "worsened" ("job losses rose to 262 from
  114"); for a fall write "eased", "declined", "fell", or "improved".
- Neutral, analytical tone — an economic bulletin, not news copy.
"""

NATIONAL_SYSTEM_PROMPT = """\
You write the Sentiment section of a weekly WARN Act layoff report for the
United States as a whole.

The user message is a JSON object of pre-computed figures:
- totals: notices and job losses in the current 90-day window vs the prior
  90-day window (short-term momentum).
- same_window_last_year: the same 90-day window one year earlier — the
  seasonal baseline for the current window.
- year_over_year: trailing 12 months vs the 12 months before (long-run trend).
- pct_change: pre-computed percent changes for those three comparisons. A
  null percent means the earlier figure was zero, so no percentage exists —
  describe that as "no comparable activity was recorded", never as a rise.
- top_states and top_sectors: current vs prior window per row, each with
  delta_layoffs and pct_change (null = nothing in the prior window).
- monthly: the last 12 months; layoffs_year_earlier is the same calendar
  month one year before.
- naics_coverage_pct.

Structure the prose in three short movements:
1. Headline: national current-window job losses with BOTH comparisons — vs
   the prior window (momentum) and vs the same window last year (seasonally
   comparable change). If they point in different directions, say so plainly;
   use the trailing-12-month totals for the long-run picture.
2. Industry: which NAICS sectors are being hit hardest and which are easing.
3. Geography: which states account for the biggest shifts.

Hard rules:
- Use ONLY numbers present in the JSON. Never compute, extrapolate, or invent
  figures, states, industries, companies, or causes. Cite percentages only
  from the pct_change fields.
- 150-300 words of plain prose. No headings, no bullet lists, no tables.
- If naics_coverage_pct is below 50, caveat that industry figures cover only a
  minority of notices.
- Every layoff figure counts workers losing their jobs. Refer to them as job
  losses; an increase is bad news and a decrease is a sign of relief.
- The words "add", "added", "grow", "grew", "gain", and "gained" are BANNED
  from your output in any form, even about job losses. For a rise write
  "rose", "climbed", "increased", or "worsened" ("job losses rose to 262 from
  114"); for a fall write "eased", "declined", "fell", or "improved".
- Neutral, analytical tone — an economic bulletin, not news copy.
"""

INDUSTRY_SYSTEM_PROMPT = """\
You write the Sentiment section of a weekly national scorecard for one NAICS
industry sector.

The user message is a JSON object of pre-computed figures for that sector:
- totals: notices and job losses in the current 90-day window vs the prior
  90-day window (short-term momentum).
- same_window_last_year: the same 90-day window one year earlier — the
  seasonal baseline for the current window.
- year_over_year: trailing 12 months vs the 12 months before (long-run trend).
- pct_change: pre-computed percent changes for those three comparisons. A
  null percent means the earlier figure was zero, so no percentage exists —
  describe that as "no comparable activity was recorded", never as a rise.
- score and grade: a pre-computed 0-100 health score (higher = healthier)
  with a letter grade.
- top_states and top_subsectors: current vs prior window per row, each with
  delta_layoffs and pct_change (null = nothing in the prior window).
- monthly: the last 12 months; layoffs_year_earlier is the same calendar
  month one year before.

Structure the prose in three short movements:
1. Headline: whether layoff pressure in this sector is rising or easing,
   using BOTH comparisons — vs the prior window (momentum) and vs the same
   window last year (seasonally comparable change) — plus the trailing-12-month
   totals for the long-run picture. Reference the score and grade only as
   given — do not recompute or reinterpret them.
2. Geography: which states drive the pressure.
3. Subsectors: which 3-digit subsectors drive it.

Hard rules:
- Use ONLY numbers present in the JSON. Never compute, extrapolate, or invent
  figures, states, subsectors, companies, or causes. Cite percentages only
  from the pct_change fields.
- 150-300 words of plain prose. No headings, no bullet lists, no tables.
- Always note that figures cover only NAICS-enriched notices (see
  coverage_note) and are directional, not exhaustive.
- Every layoff figure counts workers losing their jobs. Refer to them as job
  losses; an increase is bad news and a decrease is a sign of relief.
- The words "add", "added", "grow", "grew", "gain", and "gained" are BANNED
  from your output in any form, even about job losses. For a rise write
  "rose", "climbed", "increased", or "worsened" ("job losses rose to 262 from
  114"); for a fall write "eased", "declined", "fell", or "improved".
- Neutral, analytical tone — an economic bulletin, not news copy.
"""


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


def generate_state_report(
    session: Session,
    client: NarrativeClient | None,
    state: str,
    *,
    as_of: date | None = None,
) -> tuple[str, str]:
    """Build one state's report. Returns (markdown, narrative_status) where
    status is ok | insufficient_data | llm_unavailable | skipped."""
    agg = compute_state_aggregates(session, state, as_of=as_of)
    narrative: str | None = None
    if not agg.sufficient:
        status = "insufficient_data"
    elif client is None:
        status = "skipped"
    else:
        try:
            narrative = client.narrate(
                system=SYSTEM_PROMPT, prompt=json.dumps(agg.to_prompt_payload())
            )
            status = "ok"
        except OllamaUnavailable as exc:
            log.warning("narrative failed for %s: %s", agg.state, exc)
            status = "llm_unavailable"
    content = render_report(
        agg, narrative, narrative_status=status, model=getattr(client, "model", None)
    )
    return content, status


def generate_national_report(
    session: Session,
    client: NarrativeClient | None,
    *,
    as_of: date | None = None,
) -> tuple[str, str]:
    """Build the US-wide report. Same return shape as generate_state_report."""
    agg = compute_national_aggregates(session, as_of=as_of)
    narrative: str | None = None
    if not agg.sufficient:
        status = "insufficient_data"
    elif client is None:
        status = "skipped"
    else:
        try:
            narrative = client.narrate(
                system=NATIONAL_SYSTEM_PROMPT, prompt=json.dumps(agg.to_prompt_payload())
            )
            status = "ok"
        except OllamaUnavailable as exc:
            log.warning("narrative failed for %s: %s", agg.state, exc)
            status = "llm_unavailable"
    content = render_report(
        agg, narrative, narrative_status=status, model=getattr(client, "model", None)
    )
    return content, status


def generate_industry_report(
    session: Session,
    client: NarrativeClient | None,
    sector: str,
    *,
    as_of: date | None = None,
) -> tuple[str, str, SectorAggregates]:
    """Build one sector's scorecard. Returns (markdown, narrative_status,
    aggregates) — the aggregates feed the industries.json summary."""
    agg = compute_sector_aggregates(session, sector, as_of=as_of)
    narrative: str | None = None
    if not agg.sufficient:
        status = "insufficient_data"
    elif client is None:
        status = "skipped"
    else:
        try:
            narrative = client.narrate(
                system=INDUSTRY_SYSTEM_PROMPT, prompt=json.dumps(agg.to_prompt_payload())
            )
            status = "ok"
        except OllamaUnavailable as exc:
            log.warning("narrative failed for sector %s: %s", sector, exc)
            status = "llm_unavailable"
    content = render_industry_report(
        agg, narrative, narrative_status=status, model=getattr(client, "model", None)
    )
    return content, status, agg


def generate_reports(
    session: Session,
    client: NarrativeClient | None,
    *,
    reports_dir: Path,
    states: list[str] | None = None,
    dry_run: bool = False,
    as_of: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Generate reports for `states` (default: every STATE_NAMES jurisdiction —
    the browsable-state surface, deliberately wider than the scraper registry so
    states with historical data but a blocked scraper still get a report)."""
    targets = [s.upper() for s in states] if states else sorted(STATE_NAMES)
    counters = {
        "generated": 0,
        "insufficient": 0,
        "narrative_ok": 0,
        "narrative_failed": 0,
        "total": len(targets),
    }
    for code in targets:
        content, status = generate_state_report(session, client, code, as_of=as_of)
        if status == "insufficient_data":
            counters["insufficient"] += 1
        elif status == "ok":
            counters["narrative_ok"] += 1
        elif status == "llm_unavailable":
            counters["narrative_failed"] += 1
        if not dry_run:
            write_report(reports_dir, code, content)
        counters["generated"] += 1
        if progress:
            progress(f"{code} narrative={status} chars={len(content)}")
    return counters


def generate_industry_reports(
    session: Session,
    client: NarrativeClient | None,
    *,
    reports_dir: Path,
    sectors: list[str] | None = None,
    dry_run: bool = False,
    as_of: date | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Generate scorecards for `sectors` (default: every NAICS sector). The
    industries.json summary is rewritten only on a full default run — a
    targeted --industry run must not shrink it to one entry."""
    targets = sectors if sectors is not None else [sid for sid, _, _ in NAICS_SECTORS]
    counters = {
        "generated": 0,
        "insufficient": 0,
        "narrative_ok": 0,
        "narrative_failed": 0,
        "total": len(targets),
    }
    aggs: list[SectorAggregates] = []
    for sector in targets:
        content, status, agg = generate_industry_report(
            session, client, sector, as_of=as_of
        )
        aggs.append(agg)
        if status == "insufficient_data":
            counters["insufficient"] += 1
        elif status == "ok":
            counters["narrative_ok"] += 1
        elif status == "llm_unavailable":
            counters["narrative_failed"] += 1
        if not dry_run:
            _atomic_write(reports_dir, f"industry_{sector}.md", content)
        counters["generated"] += 1
        if progress:
            progress(f"industry {sector} narrative={status} chars={len(content)}")
    if sectors is None and not dry_run:
        _atomic_write(
            reports_dir, INDUSTRIES_JSON, json.dumps(scorecard_summary(aggs), indent=2)
        )
    return counters
