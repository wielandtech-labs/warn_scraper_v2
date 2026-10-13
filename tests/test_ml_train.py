"""Weekly train -> gate -> score: promotion gates, drift, champion lifecycle."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import func, insert, select

from tests.ml_synthetic import population
from warn_v2.db.models import MlModelRun, Notice, RepeatRiskScore
from warn_v2.ml import backtest, train
from warn_v2.ml.events import build_events, load_notices
from warn_v2.ml.train import FoldScore, decide, psi, realized, train_and_score

AS_OF = date(2023, 6, 1)
YEARS = [2015, 2018, 2021]
NOW = datetime(2023, 6, 1, 12, tzinfo=UTC)


def _fold(pr=0.6, ece=0.02, rule=0.55, year=2021):
    return FoldScore(year=year, pr_auc=pr, ece=ece, rule_pr_auc=rule)


@pytest.mark.parametrize(
    ("challenger", "champion", "promote", "why"),
    [
        (_fold(ece=0.08), None, False, "ECE"),
        (_fold(pr=0.50), None, False, "prior-events rule"),
        (_fold(), None, True, "no champion"),
        (_fold(), _fold(pr=0.9, year=2020), True, "new test year"),
        (_fold(pr=0.60), _fold(pr=0.65), False, "trails champion"),
        (_fold(pr=0.64), _fold(pr=0.65), True, "vs champion"),
    ],
)
def test_promotion_gates(challenger, champion, promote, why):
    ok, reason = decide(challenger, champion)
    assert ok is promote and why in reason


def test_psi_flags_a_shifted_distribution():
    rng = np.random.default_rng(0)
    ref = rng.beta(2, 8, 5000)
    assert psi(ref, rng.beta(2, 8, 5000)) < 0.02
    assert psi(ref, rng.beta(5, 5, 5000)) > 0.25
    assert np.isnan(psi(ref, np.array([])))


@pytest.fixture
def seeded(db, monkeypatch):
    monkeypatch.setattr(backtest, "MIN_TRAIN_EVENTS", 500)
    df = population(n_companies=2500)
    db.execute(insert(Notice), [
        {"notice_id": r.notice_id, "state": r.state, "employer": r.employer,
         "notice_date": r.notice_date.date(), "layoff_count": None
         if r.layoff_count != r.layoff_count else int(r.layoff_count),
         "closure_category": r.closure_category}
        for r in df.itertuples()
    ])
    db.commit()
    return db


def _run(db, tmp_path: Path, now=NOW):
    run = train_and_score(db, as_of=AS_OF, reports_dir=tmp_path, code_version="test",
                          years=YEARS, now=now)
    db.commit()
    return run, json.loads(run.metrics)


def _scores(db, version):
    return db.scalar(select(func.count()).select_from(RepeatRiskScore)
                     .where(RepeatRiskScore.model_version == version))


def test_champion_lifecycle(seeded, tmp_path, monkeypatch):
    db = seeded
    first, m1 = _run(db, tmp_path)
    assert first.promoted and first.decision == "no champion yet"
    assert (Path(first.artifact_path) / "model.joblib").exists()
    assert (tmp_path / "repeat_risk_backtest.md").exists()
    assert m1["open_events"] > 0 and m1["scores_written"] == m1["open_events"]
    assert _scores(db, first.version) == m1["open_events"]
    assert m1["score_psi"] < 0.25  # same data the reference came from

    # A challenger that fails a gate: the old champion keeps scoring, and
    # the events it already scored aren't written twice.
    monkeypatch.setattr(train, "MAX_ECE", -1.0)
    second, m2 = _run(db, tmp_path, now=NOW + timedelta(days=7))
    assert not second.promoted and "ECE" in second.decision
    assert m2["scorer_version"] == first.version and m2["scores_written"] == 0
    assert _scores(db, second.version) == 0

    # Passing again: the new version takes over and scores everything.
    monkeypatch.setattr(train, "MAX_ECE", 0.05)
    third, m3 = _run(db, tmp_path, now=NOW + timedelta(days=14))
    assert third.promoted and m3["scorer_version"] == third.version
    assert _scores(db, third.version) == m3["open_events"]
    assert db.scalar(select(func.count()).select_from(MlModelRun)) == 3


def test_champion_with_missing_artifact_is_replaced(seeded, tmp_path):
    db = seeded
    first, _ = _run(db, tmp_path)
    (Path(first.artifact_path) / "model.joblib").unlink()
    second, m2 = _run(db, tmp_path, now=NOW + timedelta(days=7))
    assert second.promoted and "artifact unreadable" in second.decision
    assert m2["scorer_version"] == second.version


def test_realized_grades_the_first_score_of_matured_events(seeded):
    db = seeded
    events = build_events(load_notices(db), as_of=AS_OF)
    lab = events[events["labelled"]].head(400)
    # First prediction: perfect. A later (re-)score of the same event is
    # inverted — realized performance must ignore it.
    for i, (k, t, y) in enumerate(zip(lab["company_key"], lab["t0"], lab["label"], strict=True)):
        db.add(RepeatRiskScore(model_version="v1", company_key=k, event_start=t.date(),
                               score=float(y), scored_at=NOW))
        db.add(RepeatRiskScore(model_version="v2", company_key=k, event_start=t.date(),
                               score=1.0 - float(y), scored_at=NOW + timedelta(days=i + 1)))
    db.commit()
    r = realized(db, events, AS_OF)
    assert r["n"] == 400 and r["pr_auc"] == pytest.approx(1.0)
