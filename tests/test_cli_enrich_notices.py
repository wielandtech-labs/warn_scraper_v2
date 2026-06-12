"""Tests for `warn-v2 enrich-notices` exit-code policy.

Rate-limited sources (TCSG) block before the backlog drains on most runs, so a
run that durably banks progress before erroring must exit 0 — otherwise the
nightly Job is marked Failed forever. Only a run with errors and zero work
accomplished is a real failure.
"""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from warn_v2 import cli
from warn_v2.enrich_notices import registry


class _StubEnricher:
    state = "GA"

    def __init__(self, stats: dict[str, int]) -> None:
        self._stats = stats

    def run(self, *, limit, dry_run, pdf_dir, request_delay) -> dict[str, int]:
        return self._stats


def _invoke(monkeypatch: pytest.MonkeyPatch, stats: dict[str, int]):
    monkeypatch.setattr(registry, "all_enrichers", lambda: [_StubEnricher(stats)])
    return CliRunner().invoke(cli.main, ["enrich-notices"])


def test_clean_run_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(
        monkeypatch,
        {"considered": 5, "enriched": 5, "pdf_fetched": 0, "skipped": 0, "errors": 0},
    )
    assert result.exit_code == 0, result.output


def test_errors_with_banked_progress_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    # The TCSG pattern: progress committed, then timeouts until the early abort.
    result = _invoke(
        monkeypatch,
        {"considered": 244, "enriched": 2, "pdf_fetched": 8, "skipped": 0, "errors": 3},
    )
    assert result.exit_code == 0, result.output


def test_errors_with_no_progress_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _invoke(
        monkeypatch,
        {"considered": 10, "enriched": 0, "pdf_fetched": 0, "skipped": 0, "errors": 3},
    )
    assert result.exit_code == 1
