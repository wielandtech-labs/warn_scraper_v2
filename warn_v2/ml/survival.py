"""Discrete-time survival model for repeat filings, backtested against the classifier.

The classifier (backtest.py) only learns from events whose full 365-day
horizon is observed and covered, so it throws away every event that opened in
the last year before a fold's cutoff, and every event whose state had a
coverage hole somewhere in its window. Here those events count up to the point
they stop being observed:

- **Time axis.** Days since the event's first notice (t0). Nothing can happen
  before day EVENT_GAP_DAYS, since a later notice inside that window belongs
  to the same event. From there the window is cut into the intervals in EDGES.
- **Censoring.** An event is censored at `followup_days` (from build_events:
  the earlier of as_of and the first uncovered month of its state). In a fold
  with cutoff Jan 1 of Y it is also censored at the cutoff.
- **Person-period rows.** One row per (event, interval the event is at risk
  in and observed through). The target is 1 in the interval where the next
  event starts. An interval cut short by censoring is dropped whatever
  happened in it, so the risk set never depends on the outcome.
- **Hazard models.** The classifier's pipelines (backtest.make_model), plus
  the interval as a feature. Cumulative incidence is
  F(t) = 1 - prod(1 - h_k) over the intervals ending by t.
- **Baseline.** A life table per prior-events bucket: the survival analogue of
  the "count of prior events" rule.
- **Comparison.** The classifier is refitted in every fold, on its own
  labelled-by-cutoff training set, and scored on the same test events.

Metrics:
- F(365) on the classifier's own labelled test events: PR-AUC, Brier, ECE.
- On all test-year events: Uno's IPCW C-index at 365 days, and IPCW Brier
  scores at 90/180/365 days plus their integral (IBS), with censoring weights
  from a Kaplan-Meier fit of the censoring distribution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from warn_v2.ml.backtest import MIN_TRAIN_EVENTS, RANDOM_STATE, fit, fold_split, metrics
from warn_v2.ml.events import (
    CATEGORICAL_FEATURES,
    EVENT_GAP_DAYS,
    FEATURES,
    HORIZON_DAYS,
    NUMERIC_FEATURES,
)

# Interval edges in days since t0: (30, 60], (60, 90], ..., (330, 365].
EDGES = np.array([*range(EVENT_GAP_DAYS, 331, 30), HORIZON_DAYS], dtype=float)
N_INTERVALS = len(EDGES) - 1
HORIZONS = (90, 180, 365)
SURVIVAL_MODELS = ["life_table", "hazard_logreg", "hazard_gbm"]
# The shipped classifier, refitted per fold exactly as backtest.py does, so
# both are graded on identical events. It only has a 365-day answer.
CLASSIFIER = "gbm"
COMPARED = [*SURVIVAL_MODELS, CLASSIFIER]
PRIOR_BUCKETS = (0, 1, 2, 3)  # 3 = three or more


def _bucket(prior_events: np.ndarray) -> np.ndarray:
    return np.minimum(prior_events.astype(int), PRIOR_BUCKETS[-1])


def _follow(events: pd.DataFrame, cutoff: pd.Timestamp | None) -> np.ndarray:
    follow = events["followup_days"].to_numpy(float)
    if cutoff is not None:
        follow = np.minimum(follow, (cutoff - events["t0"]).dt.days.to_numpy(float))
    return follow


def durations(events: pd.DataFrame, cutoff: pd.Timestamp | None = None
              ) -> tuple[np.ndarray, np.ndarray]:
    """(time, observed) per event. Time is days to the next event when it is
    seen within follow-up, else the follow-up itself (censored). A cutoff
    censors every event there too, hiding outcomes from after it."""
    follow = _follow(events, cutoff)
    gap = events["next_gap_days"].to_numpy(float)
    observed = ~np.isnan(gap) & (gap <= follow)
    return np.where(observed, gap, follow), observed


def expand(events: pd.DataFrame, cutoff: pd.Timestamp | None = None) -> pd.DataFrame:
    """Person-period rows: FEATURES, `interval` (0-based), `y`, and `event`.

    An interval enters the risk set only when follow-up covers all of it, and
    an event that has not happened before it. Whether a row exists must not
    depend on the outcome. Keeping a partly observed interval only when the
    repeat landed inside it (the naive rule) inflates hazards for the newest
    cohorts, the ones nearest every fold's test year.
    """
    follow = _follow(events, cutoff)[:, None]
    gap = events["next_gap_days"].to_numpy(float)[:, None]
    seen = ~np.isnan(gap)
    lo, hi = EDGES[None, :-1], EDGES[None, 1:]
    before = seen & (gap <= lo)  # already repeated: out of the risk set
    keep = (follow >= hi) & ~before
    hit = seen & (gap > lo) & (gap <= hi)
    rows, ks = np.nonzero(keep)
    out = events.iloc[rows][FEATURES].reset_index(drop=True)
    out["interval"] = ks
    out["y"] = hit[rows, ks].astype(int)
    out["event"] = rows  # position in `events`
    return out


def _make_hazard(name: str) -> Pipeline:
    if name == "hazard_logreg":
        pre = ColumnTransformer([
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50),
             CATEGORICAL_FEATURES),
            # One dummy per interval: a free baseline hazard.
            ("int", OneHotEncoder(handle_unknown="ignore"), ["interval"]),
        ])
        return Pipeline([("pre", pre), ("clf", LogisticRegression(C=1.0, max_iter=2000))])
    if name == "hazard_gbm":
        pre = ColumnTransformer(
            [
                ("num", "passthrough", [*NUMERIC_FEATURES, "interval"]),
                ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                                       encoded_missing_value=-1), CATEGORICAL_FEATURES),
            ],
            verbose_feature_names_out=False,
        )
        # Same fixed settings as the classifier's gbm (see backtest.make_model).
        clf = HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=150, early_stopping=False,
            max_leaf_nodes=31, min_samples_leaf=50,
            l2_regularization=1.0, categorical_features=["state"],
            random_state=RANDOM_STATE,
        )
        return Pipeline([("pre", pre.set_output(transform="pandas")), ("clf", clf)])
    raise ValueError(name)


@dataclass
class HazardModel:
    name: str
    pipeline: Pipeline | None = None
    # life_table: hazard per (prior-events bucket, interval).
    table: np.ndarray | None = None

    def hazards(self, X: pd.DataFrame) -> np.ndarray:
        """(n_events, N_INTERVALS) hazard per interval."""
        if self.name == "life_table":
            assert self.table is not None
            result: np.ndarray = self.table[_bucket(X["prior_events"].to_numpy())]
            return result
        assert self.pipeline is not None
        n = len(X)
        grid = X[FEATURES].iloc[np.repeat(np.arange(n), N_INTERVALS)].reset_index(drop=True)
        grid["interval"] = np.tile(np.arange(N_INTERVALS), n)
        h: np.ndarray = self.pipeline.predict_proba(grid)[:, 1]
        return h.reshape(n, N_INTERVALS)

    def cumulative(self, X: pd.DataFrame) -> np.ndarray:
        """(n_events, N_INTERVALS) F at each interval's end edge (EDGES[1:])."""
        result: np.ndarray = 1.0 - np.cumprod(1.0 - self.hazards(X), axis=1)
        return result


def incidence_at(F: np.ndarray, days: float) -> np.ndarray:
    """F(days) from the per-interval curve, linear inside an interval."""
    curve = np.hstack([np.zeros((len(F), 1)), F])  # F(EDGES[0]) = 0
    days = float(np.clip(days, EDGES[0], EDGES[-1]))
    k = int(np.clip(np.searchsorted(EDGES, days, side="right") - 1, 0, N_INTERVALS - 1))
    frac = (days - EDGES[k]) / (EDGES[k + 1] - EDGES[k])
    result: np.ndarray = curve[:, k] + frac * (curve[:, k + 1] - curve[:, k])
    return result


def fit_hazard(name: str, train_events: pd.DataFrame, cutoff: pd.Timestamp | None) -> HazardModel:
    pp = expand(train_events, cutoff)
    model = HazardModel(name=name)
    if name == "life_table":
        b = _bucket(pp["prior_events"].to_numpy())
        table = np.zeros((len(PRIOR_BUCKETS), N_INTERVALS))
        for i in range(len(PRIOR_BUCKETS)):
            for k in range(N_INTERVALS):
                sel = (b == i) & (pp["interval"].to_numpy() == k)
                # Fall back to the interval's pooled hazard in an empty cell.
                ref = sel if sel.any() else (pp["interval"].to_numpy() == k)
                table[i, k] = pp.loc[ref, "y"].mean() if ref.any() else 0.0
        model.table = table
        return model
    model.pipeline = _make_hazard(name).fit(pp[[*FEATURES, "interval"]], pp["y"])
    return model


# --- censoring-aware metrics -------------------------------------------------

def km_censoring(time: np.ndarray, observed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Kaplan-Meier of the *censoring* distribution G(t) = P(C > t):
    (sorted distinct times, G just after each). Events count as censored
    for this fit, the usual convention for IPCW weights."""
    t = np.asarray(time, float)
    cens = ~np.asarray(observed, bool)
    uniq, inv, counts = np.unique(t, return_inverse=True, return_counts=True)
    at_risk = len(t) - np.concatenate([[0], np.cumsum(counts)[:-1]])  # t >= u
    d = np.bincount(inv, weights=cens.astype(float), minlength=len(uniq))
    surv = np.cumprod(1.0 - d / np.maximum(at_risk, 1.0))
    return uniq, surv


def _g_at(uniq: np.ndarray, surv: np.ndarray, t: np.ndarray, *, left: bool) -> np.ndarray:
    """G(t), or G(t-) with left=True. Floored so one late censoring can't
    blow a weight up."""
    side = "left" if left else "right"
    idx = np.searchsorted(uniq, t, side=side) - 1
    g = np.where(idx >= 0, surv[np.clip(idx, 0, None)], 1.0)
    return np.maximum(g, 0.05)


def brier_ipcw(time: np.ndarray, observed: np.ndarray, F_tau: np.ndarray, tau: float) -> float:
    """Graf's IPCW Brier score at tau for predicted P(event by tau).

    Event-free at tau means still followed at tau without an event. That
    includes follow-up ending exactly at tau, which is every non-repeater
    watched for the full horizon (durations() caps follow-up there), so
    those use G(tau-): their own censoring at tau is not a loss to follow-up
    before it."""
    uniq, surv = km_censoring(time, observed)
    died = observed & (time <= tau)
    alive = ~died & (time >= tau)
    w_died = 1.0 / _g_at(uniq, surv, time, left=True)
    w_alive = 1.0 / _g_at(uniq, surv, np.full(len(time), tau), left=True)
    loss = np.where(died, (1.0 - F_tau) ** 2 * w_died, 0.0) + np.where(
        alive, F_tau**2 * w_alive, 0.0
    )
    return float(loss.mean())


def integrated_brier(time: np.ndarray, observed: np.ndarray, F: np.ndarray) -> float:
    """Trapezoid integral of the IPCW Brier score over the interval edges
    from the first to the horizon, divided by that span."""
    taus = EDGES[1:]
    scores = [brier_ipcw(time, observed, F[:, k], tau) for k, tau in enumerate(taus)]
    return float(np.trapezoid(scores, taus) / (taus[-1] - taus[0]))


def uno_c(time: np.ndarray, observed: np.ndarray, risk: np.ndarray, tau: float) -> float:
    """Uno's IPCW concordance, truncated at tau. A pair (i, j) is comparable
    when i's event is observed before tau and before j's time; it is
    concordant when i's risk is higher (ties count half). "Before tau" is
    inclusive, matching the label (a repeat on day 365 counts). Each comparable i is
    weighted by 1 / G(T_i-)^2. O(n log n) via a Fenwick tree over risk ranks."""
    time = np.asarray(time, float)
    observed = np.asarray(observed, bool)
    risk = np.asarray(risk, float)
    uniq, surv = km_censoring(time, observed)
    w = 1.0 / _g_at(uniq, surv, time, left=True) ** 2
    ranks = np.searchsorted(np.unique(risk), risk) + 1  # 1-based
    size = int(ranks.max()) if len(ranks) else 0
    tree = np.zeros(size + 1)

    def add(i: int) -> None:
        while i <= size:
            tree[i] += 1
            i += i & -i

    def prefix(i: int) -> float:
        s = 0.0
        while i > 0:
            s += tree[i]
            i -= i & -i
        return s

    order = np.argsort(-time, kind="stable")
    num = den = 0.0
    inserted = 0
    i = 0
    while i < len(order):
        j = i
        while j < len(order) and time[order[j]] == time[order[i]]:
            j += 1
        group = order[i:j]
        # Everything already in the tree has a strictly later time.
        for g in group:
            if observed[g] and time[g] <= tau and inserted:
                lower = prefix(int(ranks[g]) - 1)
                equal = prefix(int(ranks[g])) - lower
                num += w[g] * (lower + 0.5 * equal)
                den += w[g] * inserted
        for g in group:
            add(int(ranks[g]))
        inserted += len(group)
        i = j
    return num / den if den else float("nan")


# --- backtest ----------------------------------------------------------------

@dataclass
class SurvivalResult:
    folds: list[dict[str, Any]] = field(default_factory=list)
    # One row per labelled test event (the classifier's test set):
    # company_key, t0, label, fold, plus F(365) per survival model.
    oof: pd.DataFrame = field(default_factory=pd.DataFrame)
    # One row per test-year event, labelled or not: time, observed, fold, and
    # F at each interval edge per model (`<model>@<k>`).
    curves: pd.DataFrame = field(default_factory=pd.DataFrame)


def fold_events(events: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(train, test) for test year `year`. Train is every event opened
    before Jan 1 of Y, to be censored there; test is every event opening in Y."""
    cutoff = pd.Timestamp(year=year, month=1, day=1)
    train = events[events["t0"] < cutoff]
    test = events[events["t0"].dt.year == year]
    return train, test


def time_metrics(time: np.ndarray, observed: np.ndarray, F: np.ndarray) -> dict[str, float]:
    out = {f"brier_{h}": brier_ipcw(time, observed, incidence_at(F, h), h) for h in HORIZONS}
    out["ibs"] = integrated_brier(time, observed, F)
    out["c_index_365"] = uno_c(time, observed, F[:, -1], HORIZON_DAYS)
    return out


def _f365_metrics(time: np.ndarray, observed: np.ndarray, p: np.ndarray) -> dict[str, float]:
    """The subset of time_metrics a 365-day-only predictor can answer."""
    return {
        f"brier_{HORIZON_DAYS}": brier_ipcw(time, observed, p, HORIZON_DAYS),
        "c_index_365": uno_c(time, observed, p, HORIZON_DAYS),
    }


def run_survival_backtest(events: pd.DataFrame, years: list[int]) -> SurvivalResult:
    result = SurvivalResult()
    oofs, curves = [], []
    for year in years:
        cutoff = pd.Timestamp(year=year, month=1, day=1)
        train, test = fold_events(events, year)
        labelled = test[test["labelled"]]
        clf_train = fold_split(events, year)[0]
        # The classifier's own guard (run_backtest), so both grade the same
        # folds the shipped backtest does.
        if (len(clf_train) < MIN_TRAIN_EVENTS or clf_train["label"].nunique() < 2
                or labelled["label"].nunique() < 2):
            continue
        time, observed = durations(test)
        y = labelled["label"].to_numpy(int)
        fold: dict[str, Any] = {
            "year": year, "n_train_events": len(train),
            "n_train_labelled": len(clf_train),
            "n_test": len(test), "n_test_labelled": len(labelled),
            "models": {},
        }
        oof = labelled[["t0", "company_key", "state", "label"]].copy()
        cur = test[["t0", "company_key"]].copy()
        cur["time"], cur["observed"] = time, observed
        for name in SURVIVAL_MODELS:
            model = fit_hazard(name, train, cutoff)
            F = model.cumulative(test)
            F_lab = F[test["labelled"].to_numpy()]
            oof[name] = F_lab[:, -1]
            for k in range(N_INTERVALS):
                cur[f"{name}@{k}"] = F[:, k]
            fold["models"][name] = {
                **metrics(y, F_lab[:, -1]),
                **time_metrics(time, observed, F),
            }
        clf = fit(CLASSIFIER, clf_train)
        p_all = clf.predict(test)
        oof[CLASSIFIER] = p_all[test["labelled"].to_numpy()]
        cur[CLASSIFIER] = p_all
        fold["models"][CLASSIFIER] = {
            **metrics(y, oof[CLASSIFIER].to_numpy()),
            **_f365_metrics(time, observed, p_all),
        }
        result.folds.append(fold)
        oofs.append(oof.assign(fold=year))
        curves.append(cur.assign(fold=year))
    result.oof = pd.concat(oofs, ignore_index=True) if oofs else pd.DataFrame()
    result.curves = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    return result


def curve_matrix(curves: pd.DataFrame, model: str) -> np.ndarray:
    return curves[[f"{model}@{k}" for k in range(N_INTERVALS)]].to_numpy()
