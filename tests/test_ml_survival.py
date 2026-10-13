"""Survival model: censoring, person-period expansion, IPCW metrics, backtest."""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner

from tests.ml_synthetic import background, notices_frame, population
from warn_v2.ml import backtest, survival
from warn_v2.ml.events import FEATURES, HORIZON_DAYS, build_events
from warn_v2.ml.survival import (
    EDGES,
    N_INTERVALS,
    brier_ipcw,
    durations,
    expand,
    fit_hazard,
    fold_events,
    incidence_at,
    km_censoring,
    run_survival_backtest,
    uno_c,
)

AS_OF = date(2023, 6, 1)
D0 = date(2015, 3, 2)


@pytest.fixture(scope="module")
def events():
    return build_events(population(n_companies=4000), as_of=AS_OF)


def _one(gap: float | None, follow: float, t0: str = "2015-03-02") -> pd.DataFrame:
    row = {f: 0.0 for f in FEATURES}
    row.update(state="AA", company_key="x", t0=pd.Timestamp(t0),
               next_gap_days=np.nan if gap is None else gap, followup_days=follow)
    return pd.DataFrame([row])


# --- followup_days in build_events ------------------------------------------

def test_followup_is_full_horizon_when_covered_and_cut_at_a_hole():
    rows = [{"company_key": "acme", "state": "AA", "notice_date": D0}]
    bg = background("AA", date(2013, 1, 1), date(2019, 12, 31))
    full = build_events(notices_frame(rows + bg), as_of=date(2020, 1, 1))
    acme = full[full["company_key"] == "acme"].iloc[0]
    assert acme["followup_days"] == HORIZON_DAYS and acme["labelled"]

    holed = background("AA", date(2013, 1, 1), date(2019, 12, 31),
                       skip_months={"2015-07", "2015-08", "2015-09"})
    ev = build_events(notices_frame(rows + holed), as_of=date(2020, 1, 1))
    acme = ev[ev["company_key"] == "acme"].iloc[0]
    # Observed up to the first day of the first missing month, not dropped.
    assert acme["followup_days"] == (pd.Timestamp("2015-07-01") - pd.Timestamp(D0)).days
    assert not acme["labelled"]


def test_followup_stops_at_as_of():
    rows = [{"company_key": "acme", "state": "AA", "notice_date": date(2019, 9, 2)}]
    bg = background("AA", date(2013, 1, 1), date(2019, 12, 31))
    ev = build_events(notices_frame(rows + bg), as_of=date(2020, 1, 1))
    f = ev[ev["company_key"] == "acme"].iloc[0]["followup_days"]
    assert 0 < f <= (pd.Timestamp("2020-01-01") - pd.Timestamp("2019-09-02")).days


# --- durations and expansion -------------------------------------------------

def test_durations_hide_outcomes_after_the_cutoff():
    ev = _one(gap=200, follow=365)
    t, o = durations(ev)
    assert (t[0], o[0]) == (200, True)
    # Cutoff 100 days after t0: the day-200 repeat is in the future.
    t, o = durations(ev, cutoff=pd.Timestamp("2015-03-02") + pd.Timedelta(days=100))
    assert (t[0], o[0]) == (100, False)


def test_expansion_rows_stop_at_the_event_or_censoring():
    # Repeat on day 75: intervals (30,60] survived, (60,90] has the event.
    pp = expand(_one(gap=75, follow=365))
    assert list(pp["interval"]) == [0, 1] and list(pp["y"]) == [0, 1]
    # Never repeats, fully observed: every interval, all zero.
    pp = expand(_one(gap=None, follow=365))
    assert list(pp["interval"]) == list(range(N_INTERVALS)) and pp["y"].sum() == 0
    # Censored on day 100: (30,60] and (60,90] survived; (90,120] is cut short
    # and dropped rather than counted as a survival.
    pp = expand(_one(gap=None, follow=100))
    assert list(pp["interval"]) == [0, 1] and pp["y"].sum() == 0
    # A repeat after the follow-up ends is censored, not an event.
    pp = expand(_one(gap=300, follow=100))
    assert pp["y"].sum() == 0
    # A repeat inside an interval the follow-up only partly covers is
    # dropped with that interval: (60,90] is seen only to day 80.
    pp = expand(_one(gap=75, follow=80))
    assert list(pp["interval"]) == [0] and pp["y"].sum() == 0
    # Censored before the first interval ends: no rows at all.
    assert expand(_one(gap=None, follow=40)).empty


def test_risk_set_does_not_depend_on_the_outcome():
    # Half the events repeat on day 45, half never; follow-up ends uniformly
    # between day 31 and day 100. The true hazard in (30,60] is 0.5. Keeping
    # a partly observed interval only when the repeat is in it (the naive
    # rule) reads it as ~0.6; this is what inflated GBM hazards near cutoffs.
    n = 4000
    rng = np.random.default_rng(4)
    frames = [
        _one(gap=45.0 if i % 2 else None, follow=float(rng.integers(31, 101)))
        for i in range(n)
    ]
    pp = expand(pd.concat(frames, ignore_index=True))
    first = pp[pp["interval"] == 0]
    assert first["y"].mean() == pytest.approx(0.5, abs=0.03)


def test_expansion_never_has_an_interval_past_follow_up(events):
    cutoff = pd.Timestamp("2019-01-01")
    ev = events[events["t0"] < cutoff].reset_index(drop=True)
    pp = expand(ev, cutoff)
    time, observed = durations(ev, cutoff)
    follow = np.minimum(ev["followup_days"], (cutoff - ev["t0"]).dt.days).to_numpy(float)
    i = pp["event"].to_numpy()
    t, o, f = time[i], observed[i], follow[i]
    k = pp["interval"].to_numpy()
    lo, hi = EDGES[k], EDGES[k + 1]
    # Every row's interval is observed to its end, before the cutoff.
    assert (f >= hi).all()
    assert (pp["y"] == (o & (t > lo) & (t <= hi))).all()
    # At most one event row per event, and it is the event's last row.
    hits = pp[pp["y"] == 1]
    assert not hits["event"].duplicated().any()
    last = pp.groupby("event")["interval"].max()
    assert (hits.set_index("event")["interval"] == last[hits["event"]]).all()


# --- curves ------------------------------------------------------------------

def test_cumulative_incidence_is_monotone_and_bounded(events):
    train, test = fold_events(events, 2018)
    for name in ("life_table", "hazard_logreg"):
        model = fit_hazard(name, train, pd.Timestamp("2018-01-01"))
        F = model.cumulative(test.head(300))
        assert F.shape == (300, N_INTERVALS)
        assert (F >= 0).all() and (F <= 1).all()
        assert (np.diff(F, axis=1) >= -1e-12).all()


def test_incidence_at_interpolates_between_edges():
    F = np.array([[0.1 * (k + 1) for k in range(N_INTERVALS)]])
    assert incidence_at(F, EDGES[0])[0] == 0.0
    assert incidence_at(F, EDGES[1])[0] == pytest.approx(0.1)
    assert incidence_at(F, (EDGES[1] + EDGES[2]) / 2)[0] == pytest.approx(0.15)
    assert incidence_at(F, HORIZON_DAYS)[0] == pytest.approx(F[0, -1])


# --- IPCW metrics ------------------------------------------------------------

def test_censoring_km_matches_statsmodels():
    from statsmodels.duration.survfunc import SurvfuncRight

    rng = np.random.default_rng(1)
    t = rng.integers(31, 365, 400).astype(float)
    o = rng.random(400) < 0.6
    uniq, surv = km_censoring(t, o)
    ref = SurvfuncRight(t, (~o).astype(int))
    for u, s in zip(uniq, surv, strict=True):
        k = np.searchsorted(ref.surv_times, u, side="right")
        expect = ref.surv_prob[k - 1] if k else 1.0
        assert s == pytest.approx(expect)


def test_brier_without_censoring_is_the_plain_brier_score():
    rng = np.random.default_rng(2)
    t = rng.integers(31, 600, 1000).astype(float)
    o = np.ones(1000, bool)
    p = rng.random(1000)
    y = (t <= 365).astype(float)
    assert brier_ipcw(t, o, p, 365) == pytest.approx(np.mean((y - p) ** 2))


def test_uno_c_by_hand():
    # No censoring, so every weight is 1. Times 1..4, all observed.
    t = np.array([1.0, 2.0, 3.0, 4.0])
    o = np.ones(4, bool)
    assert uno_c(t, o, np.array([4.0, 3.0, 2.0, 1.0]), tau=10) == 1.0
    assert uno_c(t, o, np.array([1.0, 2.0, 3.0, 4.0]), tau=10) == 0.0
    # Pairs: (1,2) (1,3) (1,4) (2,3) (2,4) (3,4); risks tie for 1 and 2.
    risk = np.array([2.0, 2.0, 1.0, 0.0])
    assert uno_c(t, o, risk, tau=10) == pytest.approx((0.5 + 1 + 1 + 1 + 1 + 1) / 6)
    # tau=2.5 keeps only i in {1, 2}: pairs (1,2) (1,3) (1,4) (2,3) (2,4).
    assert uno_c(t, o, risk, tau=2.5) == pytest.approx((0.5 + 1 + 1 + 1 + 1) / 5)


def test_uno_c_matches_brute_force_with_censoring():
    rng = np.random.default_rng(3)
    n = 300
    t = rng.integers(31, 400, n).astype(float)
    o = rng.random(n) < 0.7
    r = rng.random(n)
    uniq, surv = km_censoring(t, o)
    w = 1 / survival._g_at(uniq, surv, t, left=True) ** 2
    num = den = 0.0
    for i in range(n):
        if not o[i] or t[i] >= 365:
            continue
        later = t > t[i]
        num += w[i] * ((r[later] < r[i]).sum() + 0.5 * (r[later] == r[i]).sum())
        den += w[i] * later.sum()
    assert uno_c(t, o, r, 365) == pytest.approx(num / den)


# --- backtest ----------------------------------------------------------------

def test_survival_trains_on_more_events_than_the_classifier(events, monkeypatch):
    monkeypatch.setattr(survival, "MIN_TRAIN_EVENTS", 500)
    monkeypatch.setattr(backtest, "MIN_TRAIN_EVENTS", 500)
    result = run_survival_backtest(events, [2015, 2019])
    assert [f["year"] for f in result.folds] == [2015, 2019]
    for f in result.folds:
        assert f["n_train_events"] > f["n_train_labelled"]
        ms = f["models"]
        floor = ms["gbm"]["prevalence"]
        for m in ("hazard_logreg", "hazard_gbm", "gbm"):
            assert ms[m]["pr_auc"] > floor + 0.1
            assert ms[m]["c_index_365"] > 0.6
        assert ms["hazard_gbm"]["ece"] < 0.1
        assert ms["hazard_gbm"]["brier_90"] <= ms["hazard_gbm"]["brier_365"] + 0.05
    # Same labelled test events for every model, so CIs can pair them.
    assert result.oof[["hazard_gbm", "gbm"]].notna().all().all()


def test_cli_writes_report(tmp_path, monkeypatch):
    monkeypatch.setattr(survival, "MIN_TRAIN_EVENTS", 500)
    monkeypatch.setattr(backtest, "MIN_TRAIN_EVENTS", 500)
    df = population(n_companies=2500)
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
        "ml-survival-backtest", "--from-jsonl", str(snap), "--out", str(tmp_path),
        "--as-of", AS_OF.isoformat(), "--first-year", "2019",
    ])
    assert res.exit_code == 0, res.output
    report = json.loads((tmp_path / "repeat_risk_survival.json").read_text())
    assert [f["year"] for f in report["folds"]] == [2019, 2020, 2021]
    assert set(report["pooled"]) == {"life_table", "hazard_logreg", "hazard_gbm", "gbm"}
    assert isinstance(report["decision"]["adopt"], bool)
    md = (tmp_path / "repeat_risk_survival.md").read_text(encoding="utf-8")
    assert "## Pooled out-of-fold metrics" in md and "C@365" in md


def test_notice_one_day_after_gap_lands_in_first_interval():
    rows = [
        {"company_key": "acme", "state": "AA", "notice_date": D0},
        {"company_key": "acme", "state": "AA", "notice_date": D0 + timedelta(days=31)},
    ]
    bg = background("AA", date(2013, 1, 1), date(2019, 12, 31))
    ev = build_events(notices_frame(rows + bg), as_of=date(2020, 1, 1))
    first = ev[ev["company_key"] == "acme"].iloc[[0]]
    pp = expand(first)
    assert list(pp["interval"]) == [0] and list(pp["y"]) == [1]
