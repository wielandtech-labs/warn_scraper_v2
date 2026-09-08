"""enrich CLI: exit codes that make a dead provider tier visible to Kubernetes."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from warn_v2.cli import main
from warn_v2.db.models import Company
from warn_v2.enrichment.provider import ProviderUnavailable


@pytest.fixture()
def runner():
    return CliRunner()


def _seed(db_session_factory, count: int = 5) -> None:
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
    """The 2026-09 silent failure: a provider that can't search anything used to
    exit 0, so ~24 consecutive no-op CronJob runs all reported Complete."""
    _seed(db_session_factory)
    provider = _DeadProvider()
    _install(monkeypatch, provider)

    result = runner.invoke(main, ["enrich", "--sleep-between", "0"])

    assert result.exit_code == 1, result.output
    assert "provider_errors=3" in result.output
    assert len(provider.calls) == 3  # paused after the failure streak


def test_enrich_succeeds_on_a_batch_of_genuine_misses(
    db_session_factory, runner, monkeypatch
) -> None:
    """A miss is an expected outcome (stamped + left queued), not a failure —
    the run searched, so it must not flip the exit code."""
    _seed(db_session_factory)
    _install(monkeypatch, _MissProvider())

    result = runner.invoke(main, ["enrich", "--sleep-between", "0"])

    assert result.exit_code == 0, result.output
    assert "provider_miss=5" in result.output
    assert "provider_errors=0" in result.output
