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
import re
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
- HARD LIMIT: 250 words. Cover only the biggest movers - at most three
  geographic areas and three industry rows. Plain prose; no headings, no
  bullet lists, no tables.
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
- bls_context (optional): official BLS month-over-month changes in total
  nonfarm payroll employment (thousands, seasonally adjusted) and the latest
  unemployment rate, for the same months.

Structure the prose in three short movements:
1. Headline: national current-window job losses with BOTH comparisons — vs
   the prior window (momentum) and vs the same window last year (seasonally
   comparable change). If they point in different directions, say so plainly;
   use the trailing-12-month totals for the long-run picture.
2. Industry: which NAICS sectors are being hit hardest and which are easing.
3. Geography: which states account for the biggest shifts.
If bls_context is present, close with ONE sentence of macro context
attributed to BLS ("BLS reports...") — whether overall payrolls rose or fell
while these WARN losses occurred, and the unemployment rate. If it is absent,
do not mention BLS.

Hard rules:
- Use ONLY numbers present in the JSON. Never compute, extrapolate, or invent
  figures, states, industries, companies, or causes. Cite percentages only
  from the pct_change fields.
- Never combine, net, or arithmetically compare BLS payroll figures with WARN
  figures — they measure different things at different scales.
- HARD LIMIT: 250 words. Cover only the biggest movers - at most three
  geographic areas and three industry rows. Plain prose; no headings, no
  bullet lists, no tables.
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
- bls_context (optional): official BLS month-over-month payroll changes
  (thousands, seasonally adjusted) for the closest matching BLS industry —
  see its industry field; it can be broader than this NAICS sector.

Structure the prose in three short movements:
1. Headline: whether layoff pressure in this sector is rising or easing,
   using BOTH comparisons — vs the prior window (momentum) and vs the same
   window last year (seasonally comparable change) — plus the trailing-12-month
   totals for the long-run picture. Reference the score and grade only as
   given — do not recompute or reinterpret them.
2. Geography: which states drive the pressure.
3. Subsectors: which 3-digit subsectors drive it.
If bls_context is present, close with ONE sentence of macro context
attributed to BLS ("BLS reports...") — whether payrolls in that BLS industry
rose or fell over these months, naming the BLS industry as given. If it is
absent, do not mention BLS.

Hard rules:
- Use ONLY numbers present in the JSON. Never compute, extrapolate, or invent
  figures, states, subsectors, companies, or causes. Cite percentages only
  from the pct_change fields.
- Never combine, net, or arithmetically compare BLS payroll figures with WARN
  figures — they measure different things at different scales.
- HARD LIMIT: 250 words. Cover only the biggest movers - at most three
  geographic areas and three industry rows. Plain prose; no headings, no
  bullet lists, no tables.
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


# The prompts ban growth vocabulary for job losses (they read as good news);
# the 20b model still slips occasionally (US report 2026-07-10: "Florida added
# 5,504 more jobs", "Manufacturing grew"). Corrective retries fix most
# slips; a persistent one is logged and shipped rather than degrading the
# report to figures-only over a word choice.
_BANNED_RE = re.compile(
    r"\b(add(?:s|ed|ing)?|grow(?:s|ing|n)?|grew|gain(?:s|ed|ing)?)\b", re.IGNORECASE
)
_BANNED_RETRY_NOTE = """

IMPORTANT: your previous draft used a banned word (a form of add/grow/gain).
Rewrite the section now with none of those words in any form. These figures
are workers losing their jobs — never describe them as something added,
grown, or gained.
"""

# ~250 words is ~1,700 chars; only re-ask when the draft would visibly
# truncate at render time (MAX_NARRATIVE_CHARS is 4,000).
_RETRY_LENGTH_CHARS = 2600
_LENGTH_RETRY_NOTE = """

IMPORTANT: your previous draft was far too long and would be cut off.
Rewrite the section in no more than 250 words, covering only the biggest
movers.
"""

# One corrective retry let ~4% of scorecard narratives ship a banned-word
# slip (2026-07-10 rerun: 2 of 56); a second pass catches those.
_MAX_CORRECTIVE_RETRIES = 2


def _narrate_checked(client: NarrativeClient, system: str, payload: str) -> str:
    """Narrate with self-healing: a client failure (transport dead, or empty
    content after its own retries) gets one fresh attempt; a draft with
    banned growth vocabulary or visible-truncation length gets up to
    _MAX_CORRECTIVE_RETRIES corrective rewrites. A failed corrective call
    keeps the current flawed draft — better than degrading to figures-only."""
    try:
        narrative = client.narrate(system=system, prompt=payload)
    except OllamaUnavailable as exc:
        log.warning("narrative attempt failed (%s); retrying once", exc)
        narrative = client.narrate(system=system, prompt=payload)
    for _ in range(_MAX_CORRECTIVE_RETRIES):
        notes = []
        banned = _BANNED_RE.search(narrative)
        if banned:
            log.warning("banned word %r in narrative; retrying", banned.group())
            notes.append(_BANNED_RETRY_NOTE)
        if len(narrative) > _RETRY_LENGTH_CHARS:
            log.warning("narrative too long (%d chars); retrying", len(narrative))
            notes.append(_LENGTH_RETRY_NOTE)
        if not notes:
            return narrative
        try:
            narrative = client.narrate(system=system + "".join(notes), prompt=payload)
        except OllamaUnavailable as exc:
            log.warning("corrective retry failed (%s); keeping current draft", exc)
            return narrative
    banned = _BANNED_RE.search(narrative)
    if banned:
        log.warning("banned word %r persisted after retries", banned.group())
    return narrative


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
            narrative = _narrate_checked(
                client, SYSTEM_PROMPT, json.dumps(agg.to_prompt_payload())
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
    bls: dict | None = None,
) -> tuple[str, str]:
    """Build the US-wide report. Same return shape as generate_state_report.
    `bls` is an optional fetch_bls_context() result; its national block is
    added to the LLM payload as macro context (never to the tables)."""
    agg = compute_national_aggregates(session, as_of=as_of)
    narrative: str | None = None
    if not agg.sufficient:
        status = "insufficient_data"
    elif client is None:
        status = "skipped"
    else:
        payload = agg.to_prompt_payload()
        if bls and bls.get("national"):
            payload["bls_context"] = bls["national"]
        try:
            narrative = _narrate_checked(
                client, NATIONAL_SYSTEM_PROMPT, json.dumps(payload)
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
    bls: dict | None = None,
) -> tuple[str, str, SectorAggregates]:
    """Build one sector's scorecard. Returns (markdown, narrative_status,
    aggregates) — the aggregates feed the industries.json summary. `bls` is
    an optional fetch_bls_context() result; this sector's block (if the
    sector has CES coverage) is added to the LLM payload."""
    agg = compute_sector_aggregates(session, sector, as_of=as_of)
    narrative: str | None = None
    if not agg.sufficient:
        status = "insufficient_data"
    elif client is None:
        status = "skipped"
    else:
        payload = agg.to_prompt_payload()
        if bls and bls.get("sectors", {}).get(sector):
            payload["bls_context"] = bls["sectors"][sector]
        try:
            narrative = _narrate_checked(
                client, INDUSTRY_SYSTEM_PROMPT, json.dumps(payload)
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
    bls: dict | None = None,
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
            session, client, sector, as_of=as_of, bls=bls
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
