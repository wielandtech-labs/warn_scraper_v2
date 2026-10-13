"""Pairwise matcher: gradient boosting plus Platt calibration, cross-fitted by group.

The folds split by connected component of the positive weak-label graph.
Pairs inside one real-world company never straddle train and test, so the
model can't score a test pair by recognising its siblings. A random pair
split would leak exactly that.

Platt scaling is fitted on the out-of-fold scores, for the same reason the
repeat-risk model uses Platt (warn_v2/ml/backtest.py): it is monotone, so
calibrating can't reorder pairs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

from warn_v2.ml.er.features import FEATURES

RANDOM_STATE = 0
N_FOLDS = 5


def make_model() -> HistGradientBoostingClassifier:
    # Fixed settings, no early stopping: its random holdout would share
    # companies with the training rows (same reasoning as backtest.make_model).
    return HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=200, early_stopping=False,
        max_leaf_nodes=31, min_samples_leaf=40, l2_regularization=1.0,
        random_state=RANDOM_STATE,
    )


def _logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(q / (1 - q)).reshape(-1, 1)


@dataclass
class Matcher:
    """The fold models from cross-fitting, averaged, then Platt-calibrated.
    Scoring unlabelled pairs with the same models whose out-of-fold scores
    fitted the calibrator keeps the calibration honest; a separate model
    refitted on everything would be more confident than the calibrator
    assumes."""

    models: list[HistGradientBoostingClassifier]
    calibrator: LogisticRegression | None
    feature_names: list[str] = field(default_factory=lambda: list(FEATURES))

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        Xf = X[self.feature_names]
        raw = np.mean([m.predict_proba(Xf)[:, 1] for m in self.models], axis=0)
        if self.calibrator is None:
            return np.asarray(raw)
        cal: np.ndarray = self.calibrator.predict_proba(_logit(raw))[:, 1]
        return cal


def cross_fit(X: pd.DataFrame, y: np.ndarray, groups: np.ndarray,
              n_folds: int = N_FOLDS) -> tuple[np.ndarray, Matcher]:
    """(calibrated out-of-fold scores, matcher built from the fold models)."""
    y = np.asarray(y, int)
    k = min(n_folds, len(np.unique(groups)))
    if k < 2:
        raise ValueError("weak labels form a single company group: nothing to cross-fit")
    raw = np.zeros(len(y))
    models = []
    for tr, te in GroupKFold(n_splits=k).split(X, y, groups):
        if len(np.unique(y[tr])) < 2:
            raise ValueError("a cross-fitting fold has only one class of weak label")
        m = make_model().fit(X.iloc[tr][FEATURES], y[tr])
        raw[te] = m.predict_proba(X.iloc[te][FEATURES])[:, 1]
        models.append(m)
    calibrator = (LogisticRegression().fit(_logit(raw), y)
                  if len(np.unique(y)) == 2 else None)
    oof = calibrator.predict_proba(_logit(raw))[:, 1] if calibrator is not None else raw
    return oof, Matcher(models=models, calibrator=calibrator)
