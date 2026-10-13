"""Repeat-layoff risk model: dataset, backtest, training (see docs/ml/)."""

# The model's name on ml_model_runs rows. Kept here, not in train.py, so the
# API's read side doesn't import sklearn just to look up a score.
MODEL = "repeat_risk"
