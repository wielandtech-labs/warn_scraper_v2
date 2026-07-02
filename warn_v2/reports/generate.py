"""Orchestrate per-state report generation: aggregate → narrate → render → write.

A narrative failure for one state degrades that report to figures-only and
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

from warn_v2.reports.aggregate import compute_state_aggregates
from warn_v2.reports.ollama import NarrativeClient, OllamaUnavailable
from warn_v2.reports.render import render_report
from warn_v2.states import STATE_NAMES

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You write the Sentiment section of a weekly WARN Act layoff report for one US state.

The user message is a JSON object of pre-computed figures: current vs prior
90-day totals overall, by county, and by NAICS sector, plus a 12-month monthly
series and year-over-year totals.

Hard rules:
- Use ONLY numbers present in the JSON. Never compute, extrapolate, or invent
  figures, counties, industries, companies, or causes.
- 150-300 words of plain prose. No headings, no bullet lists, no tables.
- Describe where layoff activity is rising or easing geographically (counties)
  and by industry (sectors), and how the current window compares with the
  prior window and the year-over-year context.
- If naics_coverage_pct is below 50, caveat that industry figures cover only a
  minority of notices.
- Neutral, analytical tone — an economic bulletin, not news copy.
"""


def write_report(reports_dir: Path, state: str, content: str) -> Path:
    """Atomically replace {STATE}.md — the API serves these files concurrently."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{state}.md"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)
    return path


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
