"""Rolling-origin backtest for the repeat-layoff model.

For each test year Y: train on events whose label was already *known* on
Jan 1 of Y (t0 + horizon < Y), test on events that open in Y. That is what a
model retrained every January would have seen — no fold peeks at an outcome
from its own future, and the test sets of different years never overlap.

Candidates, weakest first:
- base_rate: the training prevalence (PR-AUC = prevalence; the floor)
- history:   "filed in the last 3 years" — the rule a domain expert would
             write down first
- prior_events: rank by number of earlier events (ties: more recent
             filings first) — the strongest hand rule we found; anything
             we ship has to beat it
- logreg:    L2 logistic regression, one-hot state
- gbm:       HistGradientBoosting, native categorical state

Models are fitted with fixed, untuned hyperparameters. Calibration is Platt
scaling (a 1-D logistic fit on the raw score's logit), fitted on the most
recent training year using a model trained on the years before it; then the
model is refitted on all training years. Platt rather than isotonic because
it is strictly monotone: isotonic's step function ties scores and, fitted on
one year, cost ~0.05 PR-AUC in ranking on the real data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, OrdinalEncoder, StandardScaler

from warn_v2.ml.events import CATEGORICAL_FEATURES, FEATURES, HORIZON_DAYS, NUMERIC_FEATURES

MODELS = ["base_rate", "history", "prior_events", "logreg", "gbm"]
# Rank-only baselines: scores, not probabilities, so no Brier/ECE.
RULES = {"history", "prior_events"}
RANDOM_STATE = 0
MIN_TRAIN_EVENTS = 2_000
MIN_CAL_EVENTS = 300


def make_model(name: str) -> Pipeline:
    if name == "logreg":
        pre = ColumnTransformer([
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=50),
             CATEGORICAL_FEATURES),
        ])
        return Pipeline([("pre", pre), ("clf", LogisticRegression(C=1.0, max_iter=2000))])
    if name == "gbm":
        pre = ColumnTransformer(
            [
                ("num", "passthrough", NUMERIC_FEATURES),
                ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1,
                                       encoded_missing_value=-1), CATEGORICAL_FEATURES),
            ],
            verbose_feature_names_out=False,
        )
        clf = HistGradientBoostingClassifier(
            learning_rate=0.05, max_iter=300, max_leaf_nodes=31, min_samples_leaf=50,
            l2_regularization=1.0, categorical_features=["state"],
            random_state=RANDOM_STATE,
        )
        return Pipeline([("pre", pre.set_output(transform="pandas")), ("clf", clf)])
    raise ValueError(name)


@dataclass
class FittedModel:
    """A trained candidate plus its Platt calibrator (None for baselines)."""

    name: str
    pipeline: Pipeline | None = None
    calibrator: LogisticRegression | None = None
    prevalence: float = 0.0

    def predict_raw(self, X: pd.DataFrame) -> np.ndarray:
        if self.name == "base_rate":
            return np.full(len(X), self.prevalence)
        if self.name == "history":
            # Rank score, not a probability: any filing in the last 3 years,
            # tie-broken by how many, so it isn't a pure step function.
            return (X["prior_notices_3y"] > 0).to_numpy(float) + 1e-3 * X[
                "prior_notices_3y"
            ].to_numpy(float)
        if self.name == "prior_events":
            return (
                X["prior_events"].to_numpy(float)
                + 1e-3 * X["prior_notices_3y"].to_numpy(float)
                - 1e-6 * X["days_since_prev_log"].to_numpy(float)
            )
        assert self.pipeline is not None
        proba: np.ndarray = self.pipeline.predict_proba(X[FEATURES])[:, 1]
        return proba

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.predict_raw(X)
        if self.calibrator is None:
            return raw
        cal: np.ndarray = self.calibrator.predict_proba(_logit(raw))[:, 1]
        return cal


def _logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q)).reshape(-1, 1)


def fit(name: str, train: pd.DataFrame) -> FittedModel:
    y = train["label"].to_numpy(int)
    model = FittedModel(name=name, prevalence=float(y.mean()))
    if name == "base_rate" or name in RULES:
        return model
    # Calibration set = the last 365 days of training events, scored by a
    # model that never saw them. A window, not "the latest calendar year": in
    # leap years a fold's training data ends with a one-day sliver of the next
    # year (2016-01-01 in the 2017 fold), and Platt fitted on that sliver
    # flattened every score (PR-AUC 0.72 -> 0.13).
    start = train["t0"].max() - pd.Timedelta(days=HORIZON_DAYS)
    early = train[train["t0"] <= start]
    late = train[train["t0"] > start]
    if (len(early) >= MIN_TRAIN_EVENTS and len(late) >= MIN_CAL_EVENTS
            and late["label"].nunique() == 2):
        probe = make_model(name).fit(early[FEATURES], early["label"].astype(int))
        raw = probe.predict_proba(late[FEATURES])[:, 1]
        model.calibrator = LogisticRegression().fit(_logit(raw), late["label"].astype(int))
    model.pipeline = make_model(name).fit(train[FEATURES], y)
    return model


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over equal-frequency bins."""
    if len(y) == 0:
        return float("nan")
    order = np.argsort(p, kind="stable")
    total = 0.0
    for idx in np.array_split(order, bins):
        if len(idx):
            total += len(idx) * abs(p[idx].mean() - y[idx].mean())
    return total / len(y)


def reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict[str, float]]:
    order = np.argsort(p, kind="stable")
    return [
        {"mean_pred": float(p[idx].mean()), "frac_pos": float(y[idx].mean()), "n": len(idx)}
        for idx in np.array_split(order, bins)
        if len(idx)
    ]


def precision_at(y: np.ndarray, p: np.ndarray, frac: float) -> float:
    k = max(1, round(frac * len(y)))
    top = np.argsort(-p, kind="stable")[:k]
    return float(y[top].mean())


def metrics(y: np.ndarray, p: np.ndarray, *, probabilistic: bool = True) -> dict[str, float]:
    out = {
        "n": len(y),
        "prevalence": float(y.mean()) if len(y) else float("nan"),
        "pr_auc": float(average_precision_score(y, p)) if y.min() != y.max() else float("nan"),
        "roc_auc": float(roc_auc_score(y, p)) if y.min() != y.max() else float("nan"),
        "precision_at_10pct": precision_at(y, p, 0.10),
    }
    if probabilistic:
        out["brier"] = float(brier_score_loss(y, p))
        out["ece"] = ece(y, p)
    return out


@dataclass
class BacktestResult:
    folds: list[dict[str, Any]] = field(default_factory=list)
    # Out-of-fold predictions for every test event: t0, company_key, state,
    # label, and one column per model.
    oof: pd.DataFrame = field(default_factory=pd.DataFrame)


def fold_split(events: pd.DataFrame, year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(train, test) for test year `year`. Train labels must be realized
    before the year opens; test = labelled events opening in the year."""
    lab = events[events["labelled"]]
    cutoff = pd.Timestamp(year=year, month=1, day=1)
    known = lab["t0"] + pd.Timedelta(days=HORIZON_DAYS) < cutoff
    train = lab[known]
    test = lab[lab["t0"].dt.year == year]
    return train, test


def run_backtest(events: pd.DataFrame, years: list[int]) -> BacktestResult:
    result = BacktestResult()
    frames = []
    for year in years:
        train, test = fold_split(events, year)
        if len(train) < MIN_TRAIN_EVENTS or test["label"].nunique() < 2:
            continue
        y = test["label"].to_numpy(int)
        fold: dict[str, Any] = {
            "year": year, "n_train": len(train), "n_test": len(test),
            "train_prevalence": float(train["label"].mean()), "models": {},
        }
        out = test[["t0", "company_key", "state", "label", *NUMERIC_FEATURES]].copy()
        for name in MODELS:
            model = fit(name, train)
            p = model.predict(test)
            out[name] = p
            fold["models"][name] = metrics(y, p, probabilistic=name not in RULES)
            if model.calibrator is not None:
                raw = model.predict_raw(test)
                out[f"{name}_raw"] = raw
                fold["models"][name]["ece_uncalibrated"] = ece(y, raw)
        result.folds.append(fold)
        frames.append(out.assign(fold=year))
    result.oof = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return result


def bootstrap_ci(
    oof: pd.DataFrame, a: str, b: str | None = None, *, n_boot: int = 300, seed: int = 0
) -> dict[str, float]:
    """95% CI for pooled PR-AUC of model `a` (or of a - b when `b` is given),
    resampling *companies* — events from one employer are correlated, so an
    event-level bootstrap would overstate certainty."""
    rng = np.random.default_rng(seed)
    _, inv = np.unique(oof["company_key"].to_numpy(), return_inverse=True)
    n_keys = int(inv.max()) + 1
    y = oof["label"].to_numpy(int)
    pa = oof[a].to_numpy()
    pb = oof[b].to_numpy() if b else None

    def stat(w: np.ndarray | None) -> float:
        v = average_precision_score(y, pa, sample_weight=w)
        if pb is not None:
            v -= average_precision_score(y, pb, sample_weight=w)
        return float(v)

    # Resampling companies with replacement == weighting each row by how many
    # times its company was drawn.
    draws = []
    for _ in range(n_boot):
        w = np.bincount(rng.integers(0, n_keys, n_keys), minlength=n_keys)[inv]
        if w[y == 1].sum() == 0 or w[y == 0].sum() == 0:
            continue
        draws.append(stat(w))
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return {"point": stat(None), "lo": float(lo), "hi": float(hi)}
