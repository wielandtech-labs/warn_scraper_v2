"""Tests for the publication-cadence report (warn_v2/scripts/cadence.py)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner
from sqlalchemy.orm import Session

from warn_v2 import cli
from warn_v2.db.models import ScraperRun
from warn_v2.scripts.cadence import cadence_states, render_markdown

NOW = datetime(2026, 7, 1, 7, 17, tzinfo=UTC)


def _run(
    state: str,
    days_ago: int,
    rows_new: int | None,
    status: str = "ok",
) -> ScraperRun:
    started = NOW - timedelta(days=days_ago)
    return ScraperRun(
        state=state,
        started_at=started,
        finished_at=started + timedelta(minutes=1),
        rows_scraped=rows_new if rows_new is not None else None,
        rows_new=rows_new,
        status=status,
    )


def _daily_runs(state: str, *, days: int, hit_every: int) -> list[ScraperRun]:
    """One run per day for `days` days; new rows every `hit_every` days."""
    return [
        _run(state, d, 3 if d % hit_every == 0 else 0)
        for d in range(1, days + 1)
    ]


def _by_state(session: Session, **kwargs) -> dict:
    return {c.state: c for c in cadence_states(session, now=NOW, **kwargs)}


def test_hot_state_daily_hits(db: Session) -> None:
    db.add_all(_daily_runs("CA", days=30, hit_every=1))
    db.commit()
    ca = _by_state(db)["CA"]
    assert ca.total_runs == 30
    assert ca.ok_runs == 30
    assert ca.runs_with_new == 30
    assert ca.hit_rate == 1.0
    assert ca.median_gap_days == 1.0
    assert ca.avg_rows_new == 3.0
    assert ca.tier == "hot"


def test_steady_state_weekly_hits(db: Session) -> None:
    db.add_all(_daily_runs("ND", days=60, hit_every=7))
    db.commit()
    nd = _by_state(db)["ND"]
    assert nd.median_gap_days == 7.0
    assert nd.tier == "steady"


def test_slow_state_monthly_hits(db: Session) -> None:
    db.add_all(_daily_runs("IL", days=120, hit_every=30))
    db.commit()
    il = _by_state(db)["IL"]
    assert il.median_gap_days == 30.0
    assert il.tier == "slow"


def test_dormant_when_gaps_exceed_slow(db: Session) -> None:
    # Three hits, 40 days apart, most recent one recent enough to not trip
    # the last-new rule — the gap alone should classify dormant.
    db.add_all([_run("MT", d, 2) for d in (10, 50, 90)])
    db.commit()
    assert _by_state(db)["MT"].tier == "dormant"


def test_dormant_when_no_new_rows_for_60_days(db: Session) -> None:
    # Daily hits historically, but nothing new in the last 70 days.
    db.add_all([_run("RI", d, 1) for d in range(70, 100)])
    db.commit()
    ri = _by_state(db)["RI"]
    assert ri.median_gap_days == 1.0
    assert ri.tier == "dormant"


def test_insufficient_data_below_min_hits(db: Session) -> None:
    db.add_all(_daily_runs("NV", days=30, hit_every=20))  # only 1 hit
    db.commit()
    assert _by_state(db)["NV"].tier == "insufficient_data"


def test_registered_but_never_run_state_is_no_data(db: Session) -> None:
    states = _by_state(db)
    assert states["WV"].total_runs == 0
    assert states["WV"].tier == "no_data"


def test_failed_runs_excluded_from_ok_and_hits(db: Session) -> None:
    db.add_all(
        [
            _run("GA", 1, 5, status="fetch_failed"),
            _run("GA", 2, 5),
            _run("GA", 3, None),  # rows_new NULL == no new rows
            _run("GA", 4, 0),
        ]
    )
    db.commit()
    ga = _by_state(db)["GA"]
    assert ga.total_runs == 4
    assert ga.ok_runs == 3
    assert ga.runs_with_new == 1
    assert ga.hit_rate == pytest.approx(1 / 3)


def test_not_modified_counts_as_ok_run(db: Session) -> None:
    db.add_all([_run("TX", 1, None, status="not_modified"), _run("TX", 2, 4)])
    db.commit()
    tx = _by_state(db)["TX"]
    assert tx.ok_runs == 2
    assert tx.runs_with_new == 1


def test_same_day_reruns_dedupe_in_gap_math(db: Session) -> None:
    # Two runs on the same day plus one 2 days later: gap list is [2], not [0, 2].
    db.add_all(
        [
            _run("AK", 3, 1),
            ScraperRun(
                state="AK",
                started_at=NOW - timedelta(days=3, hours=2),
                finished_at=NOW - timedelta(days=3, hours=2),
                rows_scraped=1,
                rows_new=1,
                status="ok",
            ),
            _run("AK", 1, 1),
        ]
    )
    db.commit()
    ak = _by_state(db)["AK"]
    assert ak.runs_with_new == 3
    assert ak.median_gap_days == 2.0


def test_since_filters_out_old_runs(db: Session) -> None:
    db.add_all([_run("VA", d, 1) for d in (1, 2, 3, 200, 201, 202)])
    db.commit()
    va = _by_state(db, since=NOW - timedelta(days=90))["VA"]
    assert va.total_runs == 3


def test_state_filter_limits_output(db: Session) -> None:
    db.add_all([_run("CA", 1, 1), _run("TX", 1, 1)])
    db.commit()
    rows = cadence_states(db, state_filter="ca", now=NOW)
    assert [r.state for r in rows] == ["CA"]


def test_markdown_includes_caveat(db: Session) -> None:
    out = render_markdown(cadence_states(db, now=NOW))
    assert "once per day" in out
    assert "| State |" in out


def test_cli_smoke(db_session_factory) -> None:
    result = CliRunner().invoke(cli.main, ["cadence-report", "--markdown"])
    assert result.exit_code == 0, result.output
    assert "| State |" in result.output
