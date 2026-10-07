"""Tests for `warn-v2 sentiment-report`: the JSON files it writes, and the
payloads the /layoff-sentiment skill reads."""
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
    from warn_v2.reports.generate import build_national_payload

    _seed_state(db, "CA")
    payload = build_national_payload(db, bls=_bls_fixture())
    assert payload["sufficient"] is True
    assert payload["bls_context"]["industry"] == "Total nonfarm"
    assert payload["bls_context"]["unemployment_rate"]["value"] == 4.2

    # Without BLS data the payload has no bls_context key.
    payload = build_national_payload(db, bls=None)
    assert "bls_context" not in payload


def test_industry_payload_carries_sector_bls_context(db):
    from warn_v2.reports.generate import build_industry_payload

    _seed_state(db, "CA", naics="311999")
    payload, _ = build_industry_payload(db, "31-33", bls=_bls_fixture())
    assert payload["bls_context"]["industry"] == "Manufacturing"

    # A sector missing from the BLS blocks gets no bls_context key.
    _seed_state(db, "TX", naics="111000")
    payload, _ = build_industry_payload(db, "11", bls=_bls_fixture())
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
    from warn_v2.reports.generate import build_national_payload, build_state_payload

    as_of = date(2026, 7, 1)
    _seed_monthly_history(db, "CA", as_of=as_of)

    state_payload = build_state_payload(db, "CA", as_of=as_of)
    assert state_payload["forecast"]["model"] in {"ets-seasonal", "ets-trend", "ets-level"}
    assert len(state_payload["forecast"]["points"]) == 6

    assert "forecast" in build_national_payload(db, as_of=as_of)


def test_sparse_history_has_no_forecast_key(db):
    from warn_v2.reports.generate import build_state_payload

    # _seed_state puts every notice on a single day -- one month of history,
    # far below even the lowest forecast ladder tier.
    _seed_state(db, "CA")
    assert "forecast" not in build_state_payload(db, "CA")


def _run(tmp_path, *extra):
    return CliRunner().invoke(
        cli.main, ["sentiment-report", "--reports-dir", str(tmp_path), *extra]
    )


def test_run_writes_only_json(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "forecasts.json", "industries.json", "outlook.json", "payloads.json",
    ]
    # 51 states + national + 20 sectors.
    assert "payloads=72" in result.output


def test_run_writes_payloads_json(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    doc = json.loads((tmp_path / "payloads.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1
    assert doc["as_of"] == date.today().isoformat()
    assert len(doc["jurisdictions"]) == 52  # 51 states + US
    assert len(doc["industries"]) == 20
    ca = doc["jurisdictions"]["CA"]
    assert ca["sufficient"] is True
    assert ca["totals"]["layoffs_current"] == 60
    assert doc["jurisdictions"]["US"]["state_name"] == "United States"
    assert doc["jurisdictions"]["WY"]["sufficient"] is False
    assert doc["industries"]["31-33"]["sector_name"]
    scorecards = json.loads((tmp_path / "industries.json").read_text(encoding="utf-8"))
    assert len(scorecards) == 20


def test_dry_run_writes_nothing(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = _run(tmp_path, "--dry-run")
    assert result.exit_code == 0, result.output
    assert list(tmp_path.iterdir()) == []
    assert "(dry run — nothing written)" in result.output


def test_run_writes_forecasts_json(db, tmp_path):
    _seed_monthly_history(db, "CA", as_of=date.today())
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    payload = json.loads((tmp_path / "forecasts.json").read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert "CA" in payload["jurisdictions"]
    assert "US" in payload["jurisdictions"]
    assert any(line.startswith("forecasts=") for line in result.output.splitlines())


def test_forecasts_build_failure_does_not_abort_run(db, tmp_path, monkeypatch):
    from warn_v2.reports import forecast as forecast_mod

    monkeypatch.setattr(
        forecast_mod,
        "build_forecasts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _seed_state(db, "CA", naics="311999")
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "forecasts=failed" in result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "forecasts.json" not in names
    assert "payloads.json" in names  # the rest still completed


def test_run_writes_outlook_json(db, tmp_path):
    _seed_state(db, "CA", naics="311999")
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    doc = json.loads((tmp_path / "outlook.json").read_text(encoding="utf-8"))
    assert doc["schema"] == 1
    assert doc["as_of"] == date.today().isoformat()
    assert isinstance(doc["claims"], list)
    assert "outlook_claims=" in result.output


def test_outlook_build_failure_does_not_abort_run(db, tmp_path, monkeypatch):
    from warn_v2.outlook import build as outlook_build

    monkeypatch.setattr(
        outlook_build,
        "build_outlook",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _seed_state(db, "CA", naics="311999")
    result = _run(tmp_path)
    assert result.exit_code == 0, result.output
    assert "outlook=failed" in result.output
    names = {p.name for p in tmp_path.iterdir()}
    assert "outlook.json" not in names
    assert "payloads.json" in names
