"""Tests for the DB-backed Prometheus collector.

Focus: warn_scrape_last_success_timestamp_seconds, the per-state freshness gauge
that drives the WarnScraperStatePerStateStale alert. A state's value must reflect
its most recent *ok* run, and a state that has never succeeded must be absent
(so blocked sources don't generate a false page).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from warn_v2.db.models import ScraperRun
from warn_v2.observability.collector import WarnCollector

_GAUGE = "warn_scrape_last_success_timestamp_seconds"


def _add(session: Session, state: str, status: str, started: datetime) -> None:
    session.add(
        ScraperRun(
            state=state,
            started_at=started,
            finished_at=started + timedelta(seconds=30),
            rows_scraped=5 if status == "ok" else 0,
            rows_new=0,
            status=status,
        )
    )


def _samples(name: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for family in WarnCollector().collect():
        if family.name != name:
            continue
        for sample in family.samples:
            out[sample.labels["state"]] = sample.value
    return out


def test_last_success_timestamp_uses_latest_ok_run(
    db_session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    with db_session_factory() as s:
        # CA: an older ok run and a newer ok run — gauge should pick the newer.
        _add(s, "CA", "ok", now - timedelta(days=2))
        _add(s, "CA", "ok", now - timedelta(hours=1))
        # CA also failed most recently; that must NOT regress the success gauge.
        _add(s, "CA", "fetch_failed", now)
        s.commit()

    samples = _samples(_GAUGE)
    assert "CA" in samples
    expected = (now - timedelta(hours=1)).timestamp()
    assert abs(samples["CA"] - expected) < 2  # within clock/serialization slop


def test_never_succeeded_state_is_absent(
    db_session_factory: sessionmaker[Session],
) -> None:
    now = datetime.now(UTC)
    with db_session_factory() as s:
        # OK (the state) only ever fails — a blocked source. Must not appear,
        # so `time() - <gauge>` can't fire a false staleness alert for it.
        _add(s, "OK", "fetch_failed", now - timedelta(hours=3))
        _add(s, "OK", "fetch_failed", now)
        _add(s, "TX", "ok", now)
        s.commit()

    samples = _samples(_GAUGE)
    assert "OK" not in samples
    assert "TX" in samples
