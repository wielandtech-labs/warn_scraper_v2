"""Tests for `warn-v2 enrich-notices` exit-code policy.

Rate-limited sources (TCSG) block before the backlog drains on most runs, so a
run that durably banks progress before erroring must exit 0 — otherwise the
nightly Job is marked Failed forever. Once the backlog drains, a healthy run
is mostly skips, so ``skipped`` counts as progress too (the source was
reachable). Only a state with errors and zero work of any kind is a real
failure, judged per state so one state's progress can't mask another's
total failure.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from warn_v2 import cli
from warn_v2.enrich_notices import registry


class _StubEnricher:
    def __init__(self, state: str, stats: dict[str, int]) -> None:
        self.state = state
        self._stats = stats

    def run(self, *, limit, dry_run, pdf_dir, request_delay) -> dict[str, int]:
        return self._stats


def _stats(**overrides: int) -> dict[str, int]:
    stats = dict.fromkeys(("considered", "enriched", "pdf_fetched", "skipped", "errors"), 0)
    stats.update(overrides)
    return stats


def _invoke(monkeypatch: pytest.MonkeyPatch, *enrichers: _StubEnricher):
    monkeypatch.setattr(registry, "all_enrichers", lambda: list(enrichers))
    return CliRunner().invoke(cli.main, ["enrich-notices"])


def test_clean_run_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(monkeypatch, _StubEnricher("GA", _stats(considered=5, enriched=5)))
    assert result.exit_code == 0, result.output


def test_errors_with_banked_progress_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # The TCSG pattern: progress committed, then timeouts until the early abort.
    result = _invoke(
        monkeypatch,
        _StubEnricher("GA", _stats(considered=244, enriched=2, pdf_fetched=8, errors=3)),
    )
    assert result.exit_code == 0, result.output


def test_errors_with_only_skips_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # Drained-backlog steady state: pages fetched fine (skips), a few timeouts.
    result = _invoke(
        monkeypatch,
        _StubEnricher("GA", _stats(considered=240, skipped=238, errors=2)),
    )
    assert result.exit_code == 0, result.output


def test_errors_with_no_progress_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(monkeypatch, _StubEnricher("GA", _stats(considered=10, errors=3)))
    assert result.exit_code == 1
    # Failed via the deliberate sys.exit, not some uncaught exception.
    assert isinstance(result.exception, SystemExit)
    assert "states with errors and no progress: GA" in result.output


def test_empty_run_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(monkeypatch, _StubEnricher("GA", _stats()))
    assert result.exit_code == 0, result.output


def test_failed_state_not_masked_by_healthy_state(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(
        monkeypatch,
        _StubEnricher("GA", _stats(considered=10, pdf_fetched=10)),
        _StubEnricher("XX", _stats(considered=10, errors=10)),
    )
    assert result.exit_code == 1
    assert "states with errors and no progress: XX" in result.output
