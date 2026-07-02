"""Tests for `warn-v2 scrape-all`, focused on the --tolerate exit-code policy.

scrape-all should fail (exit 1) when a non-tolerated state fails, but stay green
when the only failures are tolerated (known-blocked / chronically-flaky) states —
so one flaky source doesn't mark every nightly Job as Failed.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from click.testing import CliRunner

from warn_v2 import cli
from warn_v2.db.models import ScraperRun


def _run(state: str, status: str) -> ScraperRun:
    return ScraperRun(
        state=state,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        rows_scraped=0 if status != "ok" else 5,
        rows_new=0,
        status=status,
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Stub registry + runner so scrape-all touches no network or DB.

    Returns a mutable {state: status} map the test controls.
    """
    statuses: dict[str, str] = {}
    monkeypatch.setattr(cli, "all_states", lambda: list(statuses.keys()))
    monkeypatch.setattr(cli, "get_scraper", lambda state: state)  # opaque token
    monkeypatch.setattr(cli, "run_state", lambda state: _run(state, statuses[state]))
    return statuses


def test_all_ok_exits_zero(patched: dict[str, str]) -> None:
    patched.update({"CA": "ok", "TX": "ok"})
    result = CliRunner().invoke(cli.main, ["scrape-all"])
    assert result.exit_code == 0, result.output


def test_untolerated_failure_exits_nonzero(patched: dict[str, str]) -> None:
    patched.update({"CA": "ok", "TX": "fetch_failed"})
    result = CliRunner().invoke(cli.main, ["scrape-all"])
    assert result.exit_code == 1
    assert "failed: TX" in result.output


def test_tolerated_failure_exits_zero(patched: dict[str, str]) -> None:
    patched.update({"CA": "ok", "GA": "fetch_failed"})
    result = CliRunner().invoke(cli.main, ["scrape-all", "--tolerate", "GA"])
    assert result.exit_code == 0, result.output
    assert "tolerated failures (not failing run): GA" in result.output


def test_tolerated_plus_untolerated_still_fails(patched: dict[str, str]) -> None:
    # GA is tolerated, but TX also failed and is not — the run must still fail.
    patched.update({"GA": "fetch_failed", "TX": "parse_failed", "CA": "ok"})
    result = CliRunner().invoke(cli.main, ["scrape-all", "--tolerate", "GA"])
    assert result.exit_code == 1
    assert "failed: TX" in result.output
    assert "tolerated failures (not failing run): GA" in result.output


def test_tolerate_is_case_insensitive(patched: dict[str, str]) -> None:
    patched.update({"GA": "fetch_failed"})
    result = CliRunner().invoke(cli.main, ["scrape-all", "--tolerate", "ga"])
    assert result.exit_code == 0, result.output


def test_not_modified_counts_as_success(patched: dict[str, str]) -> None:
    patched.update({"CA": "ok", "NV": "not_modified"})
    result = CliRunner().invoke(cli.main, ["scrape-all"])
    assert result.exit_code == 0, result.output
    assert "failed" not in result.output


def test_skip_excludes_states(patched: dict[str, str]) -> None:
    # MS would fail, but --skip keeps it out of the run entirely.
    patched.update({"CA": "ok", "MS": "fetch_failed"})
    result = CliRunner().invoke(cli.main, ["scrape-all", "--skip", "ms"])
    assert result.exit_code == 0, result.output
    assert "MS" not in result.output


def test_skip_composes_with_states(patched: dict[str, str]) -> None:
    patched.update({"CA": "ok", "TX": "ok", "MS": "ok"})
    result = CliRunner().invoke(
        cli.main, ["scrape-all", "--states", "CA,MS", "--skip", "MS"]
    )
    assert result.exit_code == 0, result.output
    assert "CA" in result.output
    assert "MS" not in result.output
    assert "TX" not in result.output
