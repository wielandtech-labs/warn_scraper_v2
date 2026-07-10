"""Tests for the DB-backed Prometheus collector.

Focus: warn_scrape_last_success_timestamp_seconds, the per-state freshness gauge
that drives the WarnScraperStatePerStateStale alert. A state's value must reflect
its most recent *ok* run, and a state that has never succeeded must be absent
(so blocked sources don't generate a false page).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prometheus_client import CollectorRegistry, generate_latest
from sqlalchemy.orm import Session, sessionmaker

from warn_v2.db.models import Notice, ScraperRun, Subscription
from warn_v2.observability.collector import WarnCollector

_GAUGE = "warn_scrape_last_success_timestamp_seconds"
_SUBS = "warn_subscriptions"


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
        # AR only ever fails — a blocked source. Must not appear,
        # so `time() - <gauge>` can't fire a false staleness alert for it.
        _add(s, "AR", "fetch_failed", now - timedelta(hours=3))
        _add(s, "AR", "fetch_failed", now)
        _add(s, "TX", "ok", now)
        s.commit()

    samples = _samples(_GAUGE)
    assert "AR" not in samples
    assert "TX" in samples


def test_generate_latest_renders_duration_summary(
    db_session_factory: sessionmaker[Session],
) -> None:
    # Regression: SummaryMetricFamily.add_metric is (labels, count, sum) — passing
    # a quantiles dict as count made generate_latest() raise TypeError and 500 the
    # whole /metrics endpoint. Render the full registry and assert it succeeds.
    now = datetime.now(UTC)
    with db_session_factory() as s:
        _add(s, "CA", "ok", now - timedelta(hours=1))
        _add(s, "TX", "ok", now - timedelta(minutes=30))
        s.commit()

    registry = CollectorRegistry()
    registry.register(WarnCollector())

    output = generate_latest(registry).decode()
    assert "warn_scrape_duration_seconds_count" in output
    assert "warn_scrape_duration_seconds_sum" in output


_NOTICES = "warn_notices"
_WORKERS = "warn_workers_affected"


def _notice(
    session: Session,
    notice_id: str,
    state: str,
    layoff_count: int | None,
) -> None:
    session.add(
        Notice(
            notice_id=notice_id,
            state=state,
            employer=f"Employer {notice_id}",
            layoff_count=layoff_count,
        )
    )


def test_notices_and_workers_gauges_by_state(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as s:
        # CA: two notices, 100 + 50 workers. NM: one notice with NULL count
        # (workers unknown) — must count as a notice but add 0 workers, not a
        # phantom 0-worker row that skews averages elsewhere.
        _notice(s, "ca-1", "CA", 100)
        _notice(s, "ca-2", "CA", 50)
        _notice(s, "nm-1", "NM", None)
        s.commit()

    notices = _samples(_NOTICES)
    assert notices == {"CA": 2, "NM": 1}

    workers = _samples(_WORKERS)
    assert workers["CA"] == 150
    assert workers["NM"] == 0  # NULL layoff_count excluded, coalesced to 0


def test_notices_gauges_absent_when_empty_but_registry_renders(
    db_session_factory: sessionmaker[Session],
) -> None:
    # No notices: both gauges yield no samples, but the full registry must
    # still render (the metric name appears via HELP/TYPE lines).
    registry = CollectorRegistry()
    registry.register(WarnCollector())
    assert _samples(_NOTICES) == {}
    assert _samples(_WORKERS) == {}
    output = generate_latest(registry).decode()
    assert "warn_notices" in output
    assert "warn_workers_affected" in output


def _sub(
    session: Session,
    email: str,
    *,
    state: str | None = None,
    frequency: str = "daily",
    confirmed: bool = False,
) -> None:
    now = datetime.now(UTC)
    session.add(
        Subscription(
            email=email,
            state=state,
            frequency=frequency,
            confirmed_at=now if confirmed else None,
            confirm_token=f"c-{email}",
            unsubscribe_token=f"u-{email}",
        )
    )


def _sub_samples() -> dict[tuple[str, str, str], float]:
    out: dict[tuple[str, str, str], float] = {}
    for family in WarnCollector().collect():
        if family.name != _SUBS:
            continue
        for sample in family.samples:
            key = (
                sample.labels["state"],
                sample.labels["frequency"],
                sample.labels["confirmed"],
            )
            out[key] = sample.value
    return out


def test_subscriptions_grouped_by_state_frequency_and_confirmation(
    db_session_factory: sessionmaker[Session],
) -> None:
    with db_session_factory() as s:
        # Two confirmed CA-daily, one pending CA-daily, one confirmed with no
        # state filter ("any"), one confirmed CA-weekly.
        _sub(s, "a@x.com", state="CA", confirmed=True)
        _sub(s, "b@x.com", state="CA", confirmed=True)
        _sub(s, "c@x.com", state="CA", confirmed=False)
        _sub(s, "d@x.com", state=None, confirmed=True)
        _sub(s, "e@x.com", state="CA", frequency="weekly", confirmed=True)
        s.commit()

    samples = _sub_samples()
    assert samples[("CA", "daily", "true")] == 2
    assert samples[("CA", "daily", "false")] == 1
    assert samples[("any", "daily", "true")] == 1
    assert samples[("CA", "weekly", "true")] == 1


def test_subscriptions_metric_renders_and_is_absent_when_empty(
    db_session_factory: sessionmaker[Session],
) -> None:
    # No subscriptions: the gauge yields no samples (an empty family), but the
    # full registry must still render without error.
    registry = CollectorRegistry()
    registry.register(WarnCollector())
    assert _sub_samples() == {}
    assert "warn_subscriptions" in generate_latest(registry).decode()
