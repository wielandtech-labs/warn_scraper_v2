"""Repeat-layoff risk read side: /api/companies/{id}/repeat-risk + summary."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from warn_v2.api.routes import reports as reports_mod
from warn_v2.db.models import Company, MlModelRun, Notice, RepeatRiskScore
from warn_v2.ml.serve import tier_for

TODAY = date.today()
RECENT = TODAY - timedelta(days=40)


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    from warn_v2.api import app
    from warn_v2.api.deps import get_db

    monkeypatch.setenv("REPEAT_RISK_PUBLIC", "1")
    monkeypatch.setattr(reports_mod, "_REPORTS_DIR", tmp_path)

    def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    yield TestClient(app, raise_server_exceptions=True)
    app.dependency_overrides.clear()


def _run(db, version="v1", prevalence=0.2):
    db.add(MlModelRun(
        model="repeat_risk", version=f"run-{version}", created_at=datetime.now(UTC),
        data_as_of=TODAY, algorithm="gbm", promoted=True, decision="x", artifact_path="/x",
        metrics=json.dumps({"scorer_version": version, "pooled": {"prevalence": prevalence}}),
    ))


def _company(db, name, canonical=None):
    c = Company(name=name, canonical_company_id=canonical)
    db.add(c)
    db.flush()
    return c


def _notice(db, nid, company, when, **kw):
    db.add(Notice(notice_id=nid, state="CA", employer=company.name, notice_date=when,
                  company_id=company.id, **kw))


def _score(db, company, start, p, version="v1"):
    db.add(RepeatRiskScore(model_version=version, company_key=f"c{company.id}",
                           event_start=start, company_id=company.id, score=p))


@pytest.fixture
def seeded(db):
    acme = _company(db, "Acme")
    plant = _company(db, "Acme Plant 2", canonical=acme.id)
    _notice(db, "old", plant, RECENT - timedelta(days=400))  # history via a merged row
    _notice(db, "new", acme, RECENT)
    _score(db, acme, RECENT, 0.4231)
    _score(db, acme, RECENT, 0.05, version="v0")  # superseded version: ignored

    fresh = _company(db, "Fresh Co")
    _notice(db, "f1", fresh, RECENT)
    _notice(db, "f0", fresh, RECENT - timedelta(days=90), closure_category="Non-WARN")
    _score(db, fresh, RECENT, 0.6)

    stale = _company(db, "Stale Co")
    _notice(db, "s0", stale, TODAY - timedelta(days=900))
    _notice(db, "s1", stale, TODAY - timedelta(days=500))
    _score(db, stale, TODAY - timedelta(days=500), 0.7)
    _run(db)
    db.commit()
    return {"acme": acme, "plant": plant, "fresh": fresh, "stale": stale}


def test_scored_prior_filer_rolls_up_merged_rows(client, seeded):
    for cid in (seeded["acme"].id, seeded["plant"].id):
        body = client.get(f"/api/companies/{cid}/repeat-risk").json()
        assert body["status"] == "scored"
        assert body["tier"] == "high" and body["probability"] == 0.42
        assert body["base_rate"] == 0.2 and body["model_version"] == "v1"
        assert body["horizon_end"] == (RECENT + timedelta(days=365)).isoformat()


def test_first_time_filer_gets_no_number(client, seeded):
    # The Non-WARN row before the event doesn't count as history.
    body = client.get(f"/api/companies/{seeded['fresh'].id}/repeat-risk").json()
    assert body["status"] == "insufficient_history"
    assert body["probability"] is None and body["tier"] is None


def test_closed_horizon_is_not_shown(client, seeded):
    body = client.get(f"/api/companies/{seeded['stale'].id}/repeat-risk").json()
    assert body["status"] == "no_open_event"


def test_no_model_run_yet(client, db):
    c = _company(db, "Solo")
    db.commit()
    assert client.get(f"/api/companies/{c.id}/repeat-risk").json()["status"] == "unavailable"


def test_dark_by_default(client, seeded, monkeypatch, tmp_path):
    monkeypatch.delenv("REPEAT_RISK_PUBLIC")
    assert client.get(f"/api/companies/{seeded['acme'].id}/repeat-risk").status_code == 404
    (tmp_path / "repeat_risk_backtest.json").write_text("{}")
    assert client.get("/api/reports/repeat-risk").status_code == 404


def test_unknown_company_404(client):
    assert client.get("/api/companies/999999/repeat-risk").status_code == 404


@pytest.mark.parametrize(("p", "tier"), [(0.0, "low"), (0.149, "low"), (0.15, "moderate"),
                                         (0.349, "moderate"), (0.35, "high"), (0.9, "high")])
def test_tiers(p, tier):
    assert tier_for(p) == tier


def test_summary_endpoint(client, tmp_path):
    first = {"slice": "first-time filer", "n": 10, "pr_auc": 0.11, "prevalence": 0.08}
    (tmp_path / "repeat_risk_backtest.json").write_text(json.dumps({
        "as_of": "2026-10-18", "chosen": {"model": "gbm"},
        "data": {"labelled_events": 54932, "labelled_prevalence": 0.2},
        "pooled": {"gbm": {"pr_auc": 0.594}, "prior_events": {"pr_auc": 0.568}},
        "pooled_ex_2020": {"gbm": {"pr_auc": 0.644}},
        "slices": {"history": [first]},
    }))
    body = client.get("/api/reports/repeat-risk").json()
    assert body["model"] == "gbm" and body["pooled"]["pr_auc"] == 0.594
    assert body["strongest_rule"]["pr_auc"] == 0.568
    assert body["first_time_filers"]["pr_auc"] == 0.11

    (tmp_path / "repeat_risk_backtest.json").write_text('{"truncated": ')
    assert client.get("/api/reports/repeat-risk").status_code == 404
