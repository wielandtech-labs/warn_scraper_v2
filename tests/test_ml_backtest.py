"""Repeat-layoff backtest: fold hygiene, metrics, and an end-to-end run."""
from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from tests.ml_synthetic import population
from warn_v2.ml import backtest
from warn_v2.ml.backtest import bootstrap_ci, ece, fold_split, run_backtest
from warn_v2.ml.events import HORIZON_DAYS, build_events

AS_OF = date(2023, 6, 1)


@pytest.fixture(scope="module")
def events():
    return build_events(population(n_companies=4000), as_of=AS_OF)


def test_folds_train_only_on_realized_labels_and_never_overlap(events):
    seen: set[tuple[str, pd.Timestamp]] = set()
    for year in range(2010, 2021):
        train, test = fold_split(events, year)
        jan1 = pd.Timestamp(year=year, month=1, day=1)
        assert (train["t0"] + pd.Timedelta(days=HORIZON_DAYS) < jan1).all()
        assert (test["t0"].dt.year == year).all() and test["labelled"].all()
        keys = set(zip(test["company_key"], test["t0"], strict=True))
        assert seen.isdisjoint(keys)
        seen |= keys


def test_learned_models_beat_the_floor(events, monkeypatch):
    monkeypatch.setattr(backtest, "MIN_TRAIN_EVENTS", 500)
    result = run_backtest(events, [2014, 2017, 2020])
    assert [f["year"] for f in result.folds] == [2014, 2017, 2020]
    for f in result.folds:
        m = f["models"]
        assert m["base_rate"]["pr_auc"] == pytest.approx(m["base_rate"]["prevalence"], abs=0.05)
        assert m["logreg"]["pr_auc"] > m["base_rate"]["pr_auc"] + 0.1
        assert m["gbm"]["pr_auc"] > m["base_rate"]["pr_auc"] + 0.1
        assert m["logreg"]["ece"] < 0.1
        assert "ece" not in m["prior_events"]  # rank-only rule
    ci = bootstrap_ci(result.oof, "logreg", "base_rate", n_boot=50)
    assert ci["lo"] <= ci["point"] <= ci["hi"] and ci["lo"] > 0


def test_ece_is_zero_when_calibrated_and_large_when_not():
    rng = np.random.default_rng(0)
    p = rng.random(200_000)
    y = (rng.random(len(p)) < p).astype(int)
    assert ece(y, p) < 0.01
    assert ece(y, np.clip(p + 0.3, 0, 1)) > 0.2


def test_cli_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(backtest, "MIN_TRAIN_EVENTS", 500)
    df = population(n_companies=3000)
    snap = tmp_path / "notices.jsonl"
    with snap.open("w", encoding="utf-8") as fh:
        for r in df.itertuples():
            co = {"id": int(r.company_key[1:]), "canonical_company_id": None} \
                if r.company_key.startswith("c") else None
            fh.write(json.dumps({
                "notice_id": r.notice_id, "state": r.state, "employer": r.employer,
                "notice_date": r.notice_date.date().isoformat(), "effective_date": None,
                "layoff_count": None if pd.isna(r.layoff_count) else int(r.layoff_count),
                "closure_category": r.closure_category, "company": co,
            }) + "\n")

    from warn_v2.cli import main

    res = CliRunner().invoke(main, [
        "ml-backtest", "--from-jsonl", str(snap), "--out", str(tmp_path),
        "--as-of", AS_OF.isoformat(), "--first-year", "2016",
    ])
    assert res.exit_code == 0, res.output
    report = json.loads((tmp_path / "repeat_risk_backtest.json").read_text())
    assert [f["year"] for f in report["folds"]] == list(range(2016, 2022))
    assert report["chosen"]["model"] in {"logreg", "gbm"}
    md = (tmp_path / "repeat_risk_backtest.md").read_text(encoding="utf-8")
    assert "## Pooled out-of-fold metrics" in md and "Permutation importance" in md


def test_calibration_ignores_a_one_day_year_sliver(events):
    # In leap years a fold's training data ends with a sliver of the next
    # calendar year (2016-01-01 in the 2017 fold). Calibrating on "the latest
    # year" fitted Platt to those few rows and flattened every score.
    train, _ = fold_split(events, 2015)  # t0 through 2013
    # Flip the sliver's labels: calibrated on it alone, the slope goes negative.
    sliver = train.tail(40)
    sliver = sliver.assign(t0=pd.Timestamp("2014-01-01"), label=1.0 - sliver["label"])
    model = backtest.fit("logreg", pd.concat([train, sliver], ignore_index=True))
    assert model.calibrator is not None and model.calibrator.coef_[0, 0] > 0.2
