"""Per-state publication-cadence report.

Aggregates ``scraper_runs`` history to answer: how often does each state's
WARN source actually publish new notices?  Used to pick the schedule-tier
lists in the Helm chart (``scraper.hotStates`` / ``scraper.slowStates``).

Metrics per state:

  * total runs / ok runs (``ok`` and ``not_modified`` both count as ok)
  * runs that found new rows (``rows_new > 0``) and the hit rate
  * median gap in days between consecutive *distinct dates* on which new rows
    appeared (distinct dates dedupe manual same-day reruns)
  * average rows_new on hit runs, last run, last time new rows appeared
  * a suggested tier: hot | steady | slow | dormant | insufficient_data | no_data

Caveats (also emitted with the markdown output):

  * Sampling is once per day (the nightly scrape-all), so intra-day publication
    frequency is invisible — "hot" means new rows on most daily runs.
  * ``rows_new`` also counts backfill catch-up after scraper repairs, which
    inflates early-history hit rates; prefer ``--since-days 90``.

Usage::

    warn-v2 cadence-report                    # table for all jurisdictions
    warn-v2 cadence-report --state CA         # one state
    warn-v2 cadence-report --json             # machine-readable
    warn-v2 cadence-report --markdown --since-days 180
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import SCRAPER_SUCCESS_STATUSES, ScraperRun
from warn_v2.scrapers.registry import all_states

# Tier thresholds over the median gap (days) between new-row dates.
_HOT_GAP = 1.5
_STEADY_GAP = 7.0
_SLOW_GAP = 31.0
_DORMANT_AFTER_DAYS = 60   # no new rows for this long -> dormant regardless of gap
_MIN_HITS = 3              # fewer hit runs than this -> insufficient_data

CAVEAT = (
    "Sampling is once per day (the nightly scrape-all), so a `hot` state means "
    "new rows appear on most daily runs — intra-day publication frequency "
    "cannot be detected from this data. `rows_new` also counts backfill "
    "catch-up after scraper repairs, which can inflate early-history hit "
    "rates; prefer `--since-days 90`."
)


@dataclass
class StateCadence:
    """Cadence stats for a single jurisdiction."""

    state: str
    total_runs: int = 0
    ok_runs: int = 0
    runs_with_new: int = 0
    hit_rate: float = 0.0            # runs_with_new / ok_runs
    median_gap_days: float | None = None  # between distinct new-row dates
    last_run_at: datetime | None = None
    last_new_at: datetime | None = None
    avg_rows_new: float | None = None     # mean rows_new over hit runs
    tier: str = "no_data"

    def finalize(self, *, now: datetime) -> None:
        if self.ok_runs:
            self.hit_rate = self.runs_with_new / self.ok_runs
        if self.total_runs == 0:
            self.tier = "no_data"
        elif self.runs_with_new < _MIN_HITS:
            self.tier = "insufficient_data"
        elif (
            self.last_new_at is not None
            and (now.date() - self.last_new_at.date()).days > _DORMANT_AFTER_DAYS
        ):
            self.tier = "dormant"
        elif self.median_gap_days is not None and self.median_gap_days <= _HOT_GAP:
            self.tier = "hot"
        elif self.median_gap_days is not None and self.median_gap_days <= _STEADY_GAP:
            self.tier = "steady"
        elif self.median_gap_days is not None and self.median_gap_days <= _SLOW_GAP:
            self.tier = "slow"
        else:
            self.tier = "dormant"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["hit_rate"] = round(self.hit_rate, 3)
        return d


def cadence_states(
    session: Session,
    *,
    state_filter: str | None = None,
    since: datetime | None = None,
    now: datetime | None = None,
) -> list[StateCadence]:
    """Compute cadence stats for every jurisdiction (or one) in one DB pass."""
    now = now or datetime.now(UTC)

    # Pre-seed every registered state so never-run states still show (no_data).
    results: dict[str, StateCadence] = {}
    for code in all_states():
        if state_filter and code != state_filter.upper():
            continue
        results[code] = StateCadence(state=code)

    def _ensure(code: str) -> StateCadence:
        sc = results.get(code)
        if sc is None:
            sc = StateCadence(state=code)
            results[code] = sc
        return sc

    # Distinct dates on which each state produced new rows, plus sums for means.
    new_dates: dict[str, set] = {}
    new_rows_sum: dict[str, int] = {}

    stmt = select(
        ScraperRun.state,
        ScraperRun.started_at,
        ScraperRun.status,
        ScraperRun.rows_new,
    ).order_by(ScraperRun.state, ScraperRun.started_at)
    if state_filter:
        stmt = stmt.where(ScraperRun.state == state_filter.upper())
    if since is not None:
        stmt = stmt.where(ScraperRun.started_at >= since)

    for state, started_at, status, rows_new in session.execute(stmt).all():
        state = (state or "").upper()
        sc = _ensure(state)
        sc.total_runs += 1
        if sc.last_run_at is None or started_at > sc.last_run_at:
            sc.last_run_at = started_at
        if status not in SCRAPER_SUCCESS_STATUSES:
            continue
        sc.ok_runs += 1
        if rows_new and rows_new > 0:
            sc.runs_with_new += 1
            new_rows_sum[state] = new_rows_sum.get(state, 0) + rows_new
            new_dates.setdefault(state, set()).add(started_at.date())
            if sc.last_new_at is None or started_at > sc.last_new_at:
                sc.last_new_at = started_at

    for state, dates in new_dates.items():
        sc = results[state]
        sc.avg_rows_new = new_rows_sum[state] / sc.runs_with_new
        ordered = sorted(dates)
        if len(ordered) >= 2:
            gaps = [
                (b - a).days for a, b in zip(ordered, ordered[1:], strict=False)
            ]
            sc.median_gap_days = float(statistics.median(gaps))

    for sc in results.values():
        sc.finalize(now=now)

    return [results[k] for k in sorted(results)]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_json(rows: list[StateCadence]) -> str:
    return json.dumps([r.to_dict() for r in rows], indent=2, default=str)


def _fmt_dt(dt: datetime | None) -> str:
    return f"{dt:%Y-%m-%d}" if dt else "-"


def _fmt_num(v: float | None) -> str:
    return f"{v:.1f}" if v is not None else "-"


def render_table(rows: list[StateCadence]) -> str:
    """Compact human-readable table to stdout."""
    header = (
        f"{'ST':<3} {'RUNS':>5} {'OK':>5} {'HITS':>5} {'HIT%':>5} "
        f"{'GAP(d)':>7} {'AVGNEW':>7} {'LASTNEW':>10} {'LASTRUN':>10}  TIER"
    )
    lines = [header, "-" * len(header)]
    for r in rows:
        hit = f"{100 * r.hit_rate:.0f}%" if r.ok_runs else "-"
        lines.append(
            f"{r.state:<3} {r.total_runs:>5} {r.ok_runs:>5} {r.runs_with_new:>5} "
            f"{hit:>5} {_fmt_num(r.median_gap_days):>7} {_fmt_num(r.avg_rows_new):>7} "
            f"{_fmt_dt(r.last_new_at):>10} {_fmt_dt(r.last_run_at):>10}  {r.tier}"
        )
    return "\n".join(lines)


def render_markdown(rows: list[StateCadence]) -> str:
    """Markdown table (with the sampling caveat) for reports/PRs."""
    out = [
        f"> {CAVEAT}",
        "",
        "| State | Runs | OK | Hits | Hit% | Median gap (d) | Avg new | "
        "Last new | Last run | Tier |",
        "|-------|-----:|---:|-----:|-----:|---------------:|--------:|"
        "----------|----------|------|",
    ]
    for r in rows:
        hit = f"{100 * r.hit_rate:.0f}%" if r.ok_runs else "-"
        out.append(
            f"| {r.state} | {r.total_runs} | {r.ok_runs} | {r.runs_with_new} | "
            f"{hit} | {_fmt_num(r.median_gap_days)} | {_fmt_num(r.avg_rows_new)} | "
            f"{_fmt_dt(r.last_new_at)} | {_fmt_dt(r.last_run_at)} | {r.tier} |"
        )
    return "\n".join(out)
