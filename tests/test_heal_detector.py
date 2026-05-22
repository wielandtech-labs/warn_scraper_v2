"""Tests for heal/detector.py — find_candidates() against an in-memory SQLite DB."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from warn_v2.db.models import ScraperRun
from warn_v2.heal.detector import find_candidates

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_run(
    session: Session,
    state: str,
    status: str,
    *,
    snapshot: str | None = None,
    error: str = "ParseFailed: boom",
    minutes_ago: int = 5,
) -> ScraperRun:
    ts = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    run = ScraperRun(
        state=state,
        started_at=ts,
        finished_at=ts,
        status=status,
        error=error,
        snapshot_path=snapshot,
    )
    session.add(run)
    session.flush()
    return run


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_parse_failed_with_snapshot(db, tmp_path: Path) -> None:
    snap = tmp_path / "snap.bin"
    snap.write_bytes(b"rawdata")
    _add_run(db, "CA", "parse_failed", snapshot=str(snap))
    db.commit()

    candidates = find_candidates(db)
    assert len(candidates) == 1
    assert candidates[0].state == "CA"
    assert candidates[0].snapshot_path == snap


def test_returns_validation_failed(db, tmp_path: Path) -> None:
    snap = tmp_path / "snap.bin"
    snap.write_bytes(b"x")
    _add_run(db, "TX", "validation_failed", snapshot=str(snap))
    db.commit()

    candidates = find_candidates(db)
    assert len(candidates) == 1
    assert candidates[0].state == "TX"


def test_ignores_fetch_failed(db) -> None:
    """fetch_failed has no snapshot — not healable by the agent."""
    _add_run(db, "CA", "fetch_failed")
    db.commit()
    assert find_candidates(db) == []


def test_ignores_ok_status(db, tmp_path: Path) -> None:
    snap = tmp_path / "snap.bin"
    snap.write_bytes(b"x")
    _add_run(db, "CA", "ok", snapshot=str(snap))
    db.commit()
    assert find_candidates(db) == []


def test_ignores_missing_snapshot_file(db) -> None:
    """A parse_failed run whose snapshot was deleted or never written is skipped."""
    _add_run(db, "CA", "parse_failed", snapshot="/nonexistent/path/snap.bin")
    db.commit()
    assert find_candidates(db) == []


def test_ignores_run_with_no_snapshot_path(db) -> None:
    _add_run(db, "CA", "parse_failed", snapshot=None)
    db.commit()
    assert find_candidates(db) == []


def test_respects_cooldown_window(db, tmp_path: Path) -> None:
    """A run older than the cooldown window is not returned."""
    snap = tmp_path / "snap.bin"
    snap.write_bytes(b"x")
    _add_run(db, "CA", "parse_failed", snapshot=str(snap), minutes_ago=90)
    db.commit()

    candidates = find_candidates(db, cooldown=timedelta(hours=1))
    assert candidates == []


def test_returns_most_recent_run_per_state(db, tmp_path: Path) -> None:
    """Only the most recent failure per state is returned."""
    snap_old = tmp_path / "old.bin"
    snap_new = tmp_path / "new.bin"
    snap_old.write_bytes(b"a")
    snap_new.write_bytes(b"b")
    _add_run(db, "CA", "parse_failed", snapshot=str(snap_old), minutes_ago=30)
    _add_run(db, "CA", "parse_failed", snapshot=str(snap_new), minutes_ago=5)
    db.commit()

    candidates = find_candidates(db)
    assert len(candidates) == 1
    assert candidates[0].snapshot_path == snap_new


def test_multiple_states_returned(db, tmp_path: Path) -> None:
    snap_ca = tmp_path / "ca.bin"
    snap_tx = tmp_path / "tx.bin"
    snap_ca.write_bytes(b"ca")
    snap_tx.write_bytes(b"tx")
    _add_run(db, "CA", "parse_failed", snapshot=str(snap_ca))
    _add_run(db, "TX", "validation_failed", snapshot=str(snap_tx))
    db.commit()

    candidates = find_candidates(db)
    states = {c.state for c in candidates}
    assert states == {"CA", "TX"}
