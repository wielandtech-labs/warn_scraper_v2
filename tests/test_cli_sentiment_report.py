"""Tests for `warn-v2 sentiment-report`, focused on file output and the
exit-code policy (partial narrative failures degrade; total failure exits 1)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from warn_v2 import cli
from warn_v2.db.models import Company, Notice
from warn_v2.reports import ollama as ollama_mod
from warn_v2.reports.generate import _BANNED_RETRY_NOTE, _narrate_checked
from warn_v2.reports.ollama import OllamaUnavailable


class FakeNarrativeClient:
    """Scripted stand-in for OllamaClient."""

    model = "fake-model"

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def narrate(self, *, system: str, prompt: str) -> str:
        self.calls += 1
        if self.fail:
            raise OllamaUnavailable("down")
        return "Layoff activity increased."


def _seed_state(db, state: str, n: int = 6, naics: str | None = None) -> None:
    """Enough recent notices to clear the MIN_NOTICES narrative threshold."""
    recent = date.today() - timedelta(days=10)
    company_id = None
    if naics is not None:
        comp = Company(name=f"CliCo {state} {naics}", naics_code=naics)
        db.add(comp)
        db.flush()
        company_id = comp.id
    for i in range(n):
        db.add(
            Notice(
                notice_id=f"cli_{state}_{naics or 'plain'}_{i}",
                state=state,
                employer=f"Employer {i}",
                notice_date=recent,
                layoff_count=10,
                company_id=company_id,
            )
        )
    db.commit()


@pytest.fixture(autouse=True)
def _no_bls_network(monkeypatch: pytest.MonkeyPatch):
    """CLI runs with a live client fetch BLS context — never from tests."""
    from warn_v2.reports import bls as bls_mod

    monkeypatch.setattr(bls_mod, "fetch_bls_context", lambda *a, **k: None)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeNarrativeClient:
    fake = FakeNarrativeClient()
    monkeypatch.setattr(ollama_mod, "build_ollama_client", lambda: fake)
    return fake


class ScriptedClient:
    """Returns (or raises) queued outputs in order, recording each system prompt."""

    model = "fake-model"

    def __init__(self, outputs: list[str | Exception]):
        self.outputs = list(outputs)
        self.systems: list[str] = []

    def narrate(self, *, system: str, prompt: str) -> str:
        self.systems.append(system)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def test_narrate_checked_clean_output_no_retry():
    client = ScriptedClient(["Job losses rose to 20 from 10."])
    out = _narrate_checked(client, "sys", "{}")
    assert out == "Job losses rose to 20 from 10."
    assert len(client.systems) == 1


def test_narrate_checked_banned_word_retries_once_with_note():
    client = ScriptedClient(
        ["Florida added 5,504 more jobs.", "Job losses in Florida rose by 5,504."]
    )
    out = _narrate_checked(client, "sys", "{}")
    assert out == "Job losses in Florida rose by 5,504."
    assert client.systems == ["sys", "sys" + _BANNED_RETRY_NOTE]


def test_narrate_checked_second_retry_fixes_persistent_banned_word():
    client = ScriptedClient(
        [
            "Manufacturing grew 2.4%.",
            "Publishing added 2,136 job losses.",
            "Job losses in Publishing rose by 2,136.",
        ]
    )
    out = _narrate_checked(client, "sys", "{}")
    assert out == "Job losses in Publishing rose by 2,136."
    assert len(client.systems) == 3
    assert client.systems[2] == "sys" + _BANNED_RETRY_NOTE


def test_narrate_checked_persistent_banned_word_ships_anyway(caplog):
    client = ScriptedClient(
        ["Manufacturing grew 2.4%.", "Losses gained ground.", "It added up."]
    )
    with caplog.at_level("WARNING"):
        out = _narrate_checked(client, "sys", "{}")
    assert out == "It added up."  # shipped after 2 retries, not degraded
    assert len(client.systems) == 3
    assert "persisted after retries" in caplog.text


def test_narrate_checked_unavailable_once_gets_fresh_attempt():
    client = ScriptedClient([OllamaUnavailable("empty narrative content"), "Job losses eased."])
    out = _narrate_checked(client, "sys", "{}")
    assert out == "Job losses eased."
    assert client.systems == ["sys", "sys"]  # plain retry, no corrective note


def test_narrate_checked_unavailable_twice_propagates():
    client = ScriptedClient([OllamaUnavailable("down"), OllamaUnavailable("down")])
    with pytest.raises(OllamaUnavailable):
        _narrate_checked(client, "sys", "{}")


def test_narrate_checked_overlong_draft_retried_with_length_note():
    from warn_v2.reports.generate import _LENGTH_RETRY_NOTE, _RETRY_LENGTH_CHARS

    long_draft = "Job losses rose. " * (_RETRY_LENGTH_CHARS // 17 + 2)
    client = ScriptedClient([long_draft, "Job losses rose, briefly."])
    out = _narrate_checked(client, "sys", "{}")
    assert out == "Job losses rose, briefly."
    assert client.systems[1] == "sys" + _LENGTH_RETRY_NOTE


def test_narrate_checked_failed_corrective_retry_keeps_first_draft():
    client = ScriptedClient(["Manufacturing grew 2.4%.", OllamaUnavailable("down")])
    out = _narrate_checked(client, "sys", "{}")
    assert out == "Manufacturing grew 2.4%."  # flawed draft beats figures-only


class PromptCapturingClient:
    """Succeeds once, keeping the user prompt for payload assertions."""

    model = "fake-model"

    def __init__(self):
        self.prompts: list[str] = []

    def narrate(self, *, system: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return "Job losses eased."


def _bls_fixture() -> dict:
    return {
        "national": {
            "industry": "Total nonfarm",
            "payroll_change_thousands_by_month": {"2026-06": 84.0},
            "unemployment_rate": {"month": "2026-06", "value": 4.2},
        },
        "sectors": {
            "31-33": {
                "industry": "Manufacturing",
                "payroll_change_thousands_by_month": {"2026-06": -2.0},
            }
        },
    }


def test_national_payload_carries_bls_context(db):
    import json

    from warn_v2.reports.generate import generate_national_report

    _seed_state(db, "CA")
    client = PromptCapturingClient()
    _, status = generate_national_report(db, client, bls=_bls_fixture())
    assert status == "ok"
    payload = json.loads(client.prompts[0])
    assert payload["bls_context"]["industry"] == "Total nonfarm"
    assert payload["bls_context"]["unemployment_rate"]["value"] == 4.2

    # Without BLS data the payload is unchanged.
    _, _ = generate_national_report(db, client, bls=None)
    assert "bls_context" not in json.loads(client.prompts[1])


def test_industry_payload_carries_sector_bls_context(db):
    import json

    from warn_v2.reports.generate import generate_industry_report

    _seed_state(db, "CA", naics="311999")
    client = PromptCapturingClient()
    _, status, _ = generate_industry_report(db, client, "31-33", bls=_bls_fixture())
    assert status == "ok"
    payload = json.loads(client.prompts[0])
    assert payload["bls_context"]["industry"] == "Manufacturing"

    # A sector missing from the BLS blocks gets no bls_context key.
    _seed_state(db, "TX", naics="111000")
    _, _, _ = generate_industry_report(db, client, "11", bls=_bls_fixture())
    assert "bls_context" not in json.loads(client.prompts[1])


def _seed_monthly_history(db, state: str, *, as_of: date, months: int = 40) -> None:
    """40 complete months of history ending the month before as_of (clears
    the ets-seasonal forecast ladder tier) plus a handful of very recent
    notices (clears the MIN_NOTICES narrative gate)."""
    from warn_v2.reports.aggregate import _month_start_back

    for i in range(months):
        month_start = _month_start_back(as_of, months - i)
        db.add(
            Notice(
                notice_id=f"hist_{state}_{i}",
                state=state,
                employer=f"HistEmployer {i}",
                notice_date=month_start,
                layoff_count=50 + (i % 4) * 10,
            )
        )
    for j in range(5):
        db.add(
            Notice(
                notice_id=f"recent_{state}_{j}",
                state=state,
                employer=f"RecentEmployer {j}",
                notice_date=as_of - timedelta(days=j),
                layoff_count=20,
            )
        )
    db.commit()


def test_state_and_national_payload_carry_forecast_with_sufficient_history(db):
    import json

    from warn_v2.reports.generate import generate_national_report, generate_state_report

    as_of = date(2026, 7, 1)
    _seed_monthly_history(db, "CA", as_of=as_of)
    client = PromptCapturingClient()

    state_md, state_status = generate_state_report(db, client, "CA", as_of=as_of)
    assert state_status == "ok"
    state_payload = json.loads(client.prompts[0])
    assert "forecast" in state_payload
    assert state_payload["forecast"]["model"] in {"ets-seasonal", "ets-trend", "ets-level"}
    assert len(state_payload["forecast"]["points"]) == 6
    assert "## Outlook — next 6 months (model estimate)" in state_md

    national_md, national_status = generate_national_report(db, client, as_of=as_of)
    assert national_status == "ok"
    national_payload = json.loads(client.prompts[1])
    assert "forecast" in national_payload
    assert "## Outlook — next 6 months (model estimate)" in national_md


def test_sparse_history_has_no_forecast_key_or_section(db):
    import json

    from warn_v2.reports.generate import generate_state_report

    # _seed_state puts every notice on a single day -- one month of history,
    # far below even the lowest forecast ladder tier.
    _seed_state(db, "CA")
    client = PromptCapturingClient()
    md, status = generate_state_report(db, client, "CA")
    assert status == "ok"
    payload = json.loads(client.prompts[0])
    assert "forecast" not in payload
    assert "Outlook" not in md


def test_single_state_with_narrative(db, fake_client, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert fake_client.calls == 2  # health check + the one real narration
    content = (tmp_path / "CA.md").read_text(encoding="utf-8")
    assert "Layoff activity increased." in content
    assert "Narrative generated by fake-model" in content
    assert "narrative_ok=1" in result.output


def test_skip_llm_never_touches_client(db, fake_client, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path), "--skip-llm"],
    )
    assert result.exit_code == 0, result.output
    assert fake_client.calls == 0
    assert "Narrative generation was skipped" in (tmp_path / "CA.md").read_text(encoding="utf-8")


def test_dry_run_writes_nothing(db, fake_client, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []
    assert "(dry run — nothing written)" in result.output


def test_all_narratives_failed_exits_1(db, fake_client, tmp_path):
    fake_client.fail = True
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    # The degraded report is still written before the exit code flips.
    assert "Narrative unavailable this week" in (tmp_path / "CA.md").read_text(encoding="utf-8")
    assert "narrative_failed=1" in result.output


def test_full_outage_health_check_skips_narration_fast(db, fake_client, tmp_path):
    """A systemic outage is caught by one up-front health check, not
    rediscovered independently by every one of the 72 reports (each of
    which would otherwise pay its own retry-with-backoff cost)."""
    fake_client.fail = True
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert fake_client.calls == 1  # only the health check -- not one per report
    assert "ollama health check failed" in result.output
    assert "narrative_ok=0" in result.output
    assert "total=72" in result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "CA.md" in names and "US.md" in names and "forecasts.json" in names
    ca_content = (tmp_path / "CA.md").read_text(encoding="utf-8")
    assert "Narrative unavailable this week" in ca_content


def test_insufficient_state_skips_llm_and_exits_0(db, fake_client, tmp_path):
    # No notices at all: report written, exit 0. The health check still runs
    # once up front (it doesn't know yet that WY has no data to narrate),
    # but generate_state_report itself never calls the client again.
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "WY", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert fake_client.calls == 1
    assert "Insufficient recent WARN activity" in (tmp_path / "WY.md").read_text(encoding="utf-8")


def test_unknown_state_rejected(db, fake_client, tmp_path):
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "ZZ", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "unknown state" in result.output


def test_state_run_writes_no_national_or_industry_files(db, fake_client, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["CA.md"]


def test_full_run_writes_national_and_industry_files(db, fake_client, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path), "--skip-llm"]
    )
    assert result.exit_code == 0, result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "CA.md" in names and "WY.md" in names  # all states
    assert "US.md" in names
    assert "industry_31-33.md" in names and "industry_92.md" in names  # all sectors
    assert "industries.json" in names
    # 51 states + national + 20 sectors.
    assert "total=72" in result.output
    us = (tmp_path / "US.md").read_text(encoding="utf-8")
    assert us.startswith("# United States (US)")
    assert "by state" in us
    scorecard = (tmp_path / "industry_31-33.md").read_text(encoding="utf-8")
    assert "Industry Scorecard" in scorecard
    assert "Score:" in scorecard


def test_industry_run_writes_single_scorecard_no_json(db, fake_client, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--industry", "31-33", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert fake_client.calls == 2  # health check + the one real narration
    assert sorted(p.name for p in tmp_path.iterdir()) == ["industry_31-33.md"]
    content = (tmp_path / "industry_31-33.md").read_text(encoding="utf-8")
    assert "Layoff activity increased." in content


def test_national_run_writes_only_us_md(db, fake_client, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--national", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert fake_client.calls == 2  # health check + the one real narration
    assert sorted(p.name for p in tmp_path.iterdir()) == ["US.md"]
    content = (tmp_path / "US.md").read_text(encoding="utf-8")
    assert "Layoff activity increased." in content
    assert "narrative_ok=1" in result.output


def test_national_narrative_failure_exits_1(db, fake_client, tmp_path):
    fake_client.fail = True
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--national", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    # The degraded report is still written before the exit code flips.
    assert "Narrative unavailable this week" in (tmp_path / "US.md").read_text(encoding="utf-8")
    assert "narrative_failed=1" in result.output


def test_national_and_state_mutually_exclusive(db, fake_client, tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--national", "--state", "CA", "--reports-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_national_and_industry_mutually_exclusive(db, fake_client, tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--national", "--industry", "31-33",
         "--reports-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_unknown_industry_rejected(db, fake_client, tmp_path):
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--industry", "ZZ", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "unknown industry" in result.output


def test_state_and_industry_mutually_exclusive(db, fake_client, tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--state", "CA", "--industry", "31-33",
         "--reports-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_full_dry_run_writes_nothing(db, fake_client, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--reports-dir", str(tmp_path), "--skip-llm", "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []


def test_full_run_writes_forecasts_json(db, fake_client, tmp_path):
    import json

    _seed_monthly_history(db, "CA", as_of=date.today())
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path), "--skip-llm"]
    )
    assert result.exit_code == 0, result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "forecasts.json" in names
    payload = json.loads((tmp_path / "forecasts.json").read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert "CA" in payload["jurisdictions"]
    assert "US" in payload["jurisdictions"]
    assert any(line.startswith("forecasts=") for line in result.output.splitlines())


@pytest.mark.parametrize(
    "extra_args", [["--state", "CA"], ["--national"], ["--industry", "31-33"]]
)
def test_targeted_runs_do_not_write_forecasts_json(db, fake_client, tmp_path, extra_args):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path), *extra_args]
    )
    assert result.exit_code == 0, result.output
    assert "forecasts.json" not in {p.name for p in tmp_path.iterdir()}


def test_forecasts_build_failure_does_not_abort_run(db, fake_client, tmp_path, monkeypatch):
    from warn_v2.reports import forecast as forecast_mod

    monkeypatch.setattr(
        forecast_mod,
        "build_forecasts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path), "--skip-llm"]
    )
    assert result.exit_code == 0, result.output
    assert "forecasts=failed" in result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "forecasts.json" not in names
    assert "US.md" in names  # the rest of the run still completed
