"""Tests for `warn-v2 sentiment-report`, focused on file output: which files
each scope writes, and the payloads the /layoff-sentiment skill reads."""
from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from click.testing import CliRunner

from warn_v2 import cli
from warn_v2.db.models import Company, Notice


def _seed_state(db, state: str, n: int = 6, naics: str | None = None) -> None:
    """Enough recent notices to clear the MIN_NOTICES threshold."""
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
    """The CLI fetches BLS context — never from tests."""
    from warn_v2.reports import bls as bls_mod

    monkeypatch.setattr(bls_mod, "fetch_bls_context", lambda *a, **k: None)


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
    from warn_v2.reports.generate import generate_national_report

    _seed_state(db, "CA")
    _, status, payload = generate_national_report(db, bls=_bls_fixture())
    assert status == "pending"
    assert payload["sufficient"] is True
    assert payload["bls_context"]["industry"] == "Total nonfarm"
    assert payload["bls_context"]["unemployment_rate"]["value"] == 4.2

    # Without BLS data the payload has no bls_context key.
    _, _, payload = generate_national_report(db, bls=None)
    assert "bls_context" not in payload


def test_industry_payload_carries_sector_bls_context(db):
    from warn_v2.reports.generate import generate_industry_report

    _seed_state(db, "CA", naics="311999")
    _, status, payload, _ = generate_industry_report(db, "31-33", bls=_bls_fixture())
    assert status == "pending"
    assert payload["bls_context"]["industry"] == "Manufacturing"

    # A sector missing from the BLS blocks gets no bls_context key.
    _seed_state(db, "TX", naics="111000")
    _, _, payload, _ = generate_industry_report(db, "11", bls=_bls_fixture())
    assert "bls_context" not in payload


def _seed_monthly_history(db, state: str, *, as_of: date, months: int = 40) -> None:
    """40 complete months of history ending the month before as_of (clears
    the ets-seasonal forecast ladder tier) plus a handful of very recent
    notices (clears the MIN_NOTICES gate)."""
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
    from warn_v2.reports.generate import generate_national_report, generate_state_report

    as_of = date(2026, 7, 1)
    _seed_monthly_history(db, "CA", as_of=as_of)

    state_md, state_status, state_payload = generate_state_report(db, "CA", as_of=as_of)
    assert state_status == "pending"
    assert state_payload["forecast"]["model"] in {"ets-seasonal", "ets-trend", "ets-level"}
    assert len(state_payload["forecast"]["points"]) == 6
    assert "## Outlook — next 6 months (model estimate)" in state_md

    national_md, _, national_payload = generate_national_report(db, as_of=as_of)
    assert "forecast" in national_payload
    assert "## Outlook — next 6 months (model estimate)" in national_md


def test_sparse_history_has_no_forecast_key_or_section(db):
    from warn_v2.reports.generate import generate_state_report

    # _seed_state puts every notice on a single day -- one month of history,
    # far below even the lowest forecast ladder tier.
    _seed_state(db, "CA")
    md, status, payload = generate_state_report(db, "CA")
    assert status == "pending"
    assert "forecast" not in payload
    assert "Outlook" not in md


def test_single_state_writes_pending_report(db, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    content = (tmp_path / "CA.md").read_text(encoding="utf-8")
    assert "Written analysis pending" in content
    assert "CA status=pending" in result.output


def test_dry_run_writes_nothing(db, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path), "--dry-run"],
    )
    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []
    assert "(dry run — nothing written)" in result.output


def test_insufficient_state_written_and_exits_0(db, tmp_path):
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "WY", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "Insufficient recent WARN activity" in (tmp_path / "WY.md").read_text(encoding="utf-8")
    assert "insufficient=1" in result.output


def test_unknown_state_rejected(db, tmp_path):
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "ZZ", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "unknown state" in result.output


def test_state_run_writes_no_national_or_industry_files(db, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--state", "CA", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["CA.md"]


def test_full_run_writes_national_and_industry_files(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(cli.main, ["sentiment-report", "--reports-dir", str(tmp_path)])
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


def test_full_run_writes_payloads_json(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(cli.main, ["sentiment-report", "--reports-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    doc = json.loads((tmp_path / "payloads.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1
    assert doc["as_of"] == date.today().isoformat()
    assert len(doc["jurisdictions"]) == 52  # 51 states + US
    assert len(doc["industries"]) == 20
    ca = doc["jurisdictions"]["CA"]
    assert ca["sufficient"] is True
    assert ca["totals"]["layoffs_current"] == 60
    assert doc["jurisdictions"]["WY"]["sufficient"] is False
    assert doc["industries"]["31-33"]["sector_name"]
    assert "payloads=72" in result.output


def test_industry_run_writes_single_scorecard_no_json(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--industry", "31-33", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["industry_31-33.md"]


def test_national_run_writes_only_us_md(db, tmp_path):
    _seed_state(db, "CA")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--national", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == ["US.md"]


def test_national_and_state_mutually_exclusive(db, tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--national", "--state", "CA", "--reports-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_national_and_industry_mutually_exclusive(db, tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--national", "--industry", "31-33",
         "--reports-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_unknown_industry_rejected(db, tmp_path):
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--industry", "ZZ", "--reports-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "unknown industry" in result.output


def test_state_and_industry_mutually_exclusive(db, tmp_path):
    result = CliRunner().invoke(
        cli.main,
        ["sentiment-report", "--state", "CA", "--industry", "31-33",
         "--reports-dir", str(tmp_path)],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_full_dry_run_writes_nothing(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []


def test_full_run_writes_forecasts_json(db, tmp_path):
    _seed_monthly_history(db, "CA", as_of=date.today())
    result = CliRunner().invoke(cli.main, ["sentiment-report", "--reports-dir", str(tmp_path)])
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
def test_targeted_runs_do_not_write_forecasts_or_payloads(db, tmp_path, extra_args):
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path), *extra_args]
    )
    assert result.exit_code == 0, result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "forecasts.json" not in names
    assert "payloads.json" not in names


def test_forecasts_build_failure_does_not_abort_run(db, tmp_path, monkeypatch):
    from warn_v2.reports import forecast as forecast_mod

    monkeypatch.setattr(
        forecast_mod,
        "build_forecasts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _seed_state(db, "CA", naics="311999")
    result = CliRunner().invoke(cli.main, ["sentiment-report", "--reports-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "forecasts=failed" in result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "forecasts.json" not in names
    assert "US.md" in names and "payloads.json" in names  # the rest still completed
