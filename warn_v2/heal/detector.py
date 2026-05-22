"""Pick which scraper_runs need healing."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import ScraperRun

# A state shouldn't be healed more than once per cool-down window — we don't
# want to spam PRs if the source is genuinely broken upstream.
DEFAULT_COOLDOWN = timedelta(hours=12)

HEALABLE_STATUSES = ("parse_failed", "validation_failed")


@dataclass(slots=True)
class HealCandidate:
    state: str
    run_id: int
    snapshot_path: Path
    error: str
    started_at: datetime


def find_candidates(
    session: Session,
    *,
    cooldown: timedelta = DEFAULT_COOLDOWN,
    now: datetime | None = None,
) -> list[HealCandidate]:
    """Return states that have a recent unhealed failure worth working on."""
    now = now or datetime.now(UTC)
    cutoff = now - cooldown

    # Most recent run per state — Postgres has DISTINCT ON; we keep it portable
    # with a Python-side dedup so this works against SQLite in tests too.
    stmt = (
        select(ScraperRun)
        .where(ScraperRun.status.in_(HEALABLE_STATUSES))
        .order_by(ScraperRun.state, ScraperRun.started_at.desc())
    )
    runs: list[ScraperRun] = list(session.execute(stmt).scalars())

    seen: set[str] = set()
    out: list[HealCandidate] = []
    for run in runs:
        if run.state in seen:
            continue
        seen.add(run.state)
        # SQLite returns timezone-naive datetimes even for tz-aware columns;
        # Postgres returns tz-aware.  Normalise before comparing.
        started_at = run.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if started_at < cutoff:
            # Too long ago — assume it's already been looked at.
            continue
        if not run.snapshot_path:
            continue
        path = Path(run.snapshot_path)
        if not path.exists():
            continue
        out.append(
            HealCandidate(
                state=run.state,
                run_id=run.id,
                snapshot_path=path,
                error=run.error or "",
                started_at=run.started_at,
            )
        )
    return out
