"""enrich CLI: exit codes that make a dead provider tier visible to Kubernetes."""
from __future__ import annotations

import signal
import time

import pytest
from click.testing import CliRunner

from warn_v2.cli import main
from warn_v2.db.models import Company
from warn_v2.enrichment.provider import ProviderUnavailable


@pytest.fixture()
def runner():
    return CliRunner()


def _seed(db_session_factory, count: int = 30) -> None:
    with db_session_factory() as session:
        for i in range(count):
            session.add(Company(name=f"Acme Manufacturing {i} Corporation"))
        session.commit()


def _install(monkeypatch, provider) -> None:
    monkeypatch.setattr(
        "warn_v2.enrichment.provider.load_provider", lambda: provider
    )
    monkeypatch.setattr(
        "warn_v2.enrichment.agent.build_anthropic_client", lambda: object()
    )


class _DeadProvider:
    """Raises the way the D&B provider does for every can't-search condition."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def lookup(self, company_name: str, state):
        self.calls.append(company_name)
        raise ProviderUnavailable("lookup failed")

    def close(self) -> None:
        pass


class _MissProvider:
    def lookup(self, company_name: str, state):
        return None

    def close(self) -> None:
        pass


def test_enrich_fails_when_provider_tier_completes_no_searches(
    db_session_factory, runner, monkeypatch
) -> None:
    """The first 2026-09 silent failure: a provider that can't search anything
    used to exit 0, so ~24 consecutive no-op CronJob runs all reported Complete."""
    _seed(db_session_factory)
    provider = _DeadProvider()
    _install(monkeypatch, provider)

    result = runner.invoke(main, ["enrich", "--limit", "30", "--sleep-between", "0"])

    assert result.exit_code == 1, result.output
    assert "provider_errors=3" in result.output
    assert len(provider.calls) == 3  # paused after the failure streak


def test_enrich_fails_when_a_full_batch_hits_nothing(
    db_session_factory, runner, monkeypatch
) -> None:
    """The second 2026-09 silent failure: a broken search returned an empty
    dropdown for every company, which reads as 100 genuine misses. Those exit 0
    under the old rule AND stamp provider_attempted_at, burning the queue."""
    _seed(db_session_factory)
    _install(monkeypatch, _MissProvider())

    result = runner.invoke(main, ["enrich", "--limit", "30", "--sleep-between", "0"])

    assert result.exit_code == 1, result.output
    assert "enriched nothing across 30 companies" in result.output
    assert "provider_miss=30" in result.output


def test_enrich_stays_quiet_for_a_small_run_of_misses(
    db_session_factory, runner, monkeypatch
) -> None:
    """A miss is an expected outcome (stamped + left queued), not a failure.
    Below the alarm floor an all-miss run is an ordinary draw, not evidence."""
    _seed(db_session_factory, count=5)
    _install(monkeypatch, _MissProvider())

    result = runner.invoke(main, ["enrich", "--limit", "5", "--sleep-between", "0"])

    assert result.exit_code == 0, result.output
    assert "provider_miss=5" in result.output
    assert "provider_errors=0" in result.output


@pytest.mark.skipif(
    not hasattr(signal, "SIGALRM"), reason="SIGALRM watchdog is POSIX-only"
)
def test_enrich_does_not_hang_when_the_provider_will_not_close(
    db_session_factory, runner, monkeypatch
) -> None:
    """Shutting the provider down is the other place a wedged browser blocks
    forever — Playwright's close()/stop() wait on processes and take no timeout
    of their own. Without a budget the run finishes its work and then parks the
    pod, which concurrencyPolicy=Forbid turns into a stalled schedule."""
    import warn_v2.enrichment.worker as worker_mod

    monkeypatch.setattr(worker_mod, "_PROVIDER_CLOSE_TIMEOUT_S", 1)

    class _WontCloseProvider(_MissProvider):
        def close(self) -> None:
            time.sleep(30)
            raise AssertionError("close watchdog did not fire")

    _seed(db_session_factory, count=5)
    _install(monkeypatch, _WontCloseProvider())

    started = time.monotonic()
    result = runner.invoke(main, ["enrich", "--limit", "5", "--sleep-between", "0"])
    elapsed = time.monotonic() - started

    assert elapsed < 30  # returned on the watchdog, not on the sleep
    assert "provider_miss=5" in result.output  # the run's own work still reported
