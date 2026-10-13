"""Survival backtest report: JSON kept by the run, and a markdown rendering."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from warn_v2.ml.backtest import bootstrap_ci, metrics, reliability
from warn_v2.ml.events import EVENT_GAP_DAYS, HORIZON_DAYS
from warn_v2.ml.report import _f
from warn_v2.ml.survival import (
    CLASSIFIER,
    COMPARED,
    EDGES,
    HORIZONS,
    SURVIVAL_MODELS,
    SurvivalResult,
    _f365_metrics,
    curve_matrix,
    time_metrics,
)

# The decision rule from the model card: the hazard GBM replaces the
# classifier only if it is not significantly worse at ranking (the PR-AUC
# gap's 95% CI reaches zero) and is better on the 365-day IPCW Brier score.
CANDIDATE = "hazard_gbm"


def _pool(result: SurvivalResult) -> dict[str, dict[str, float]]:
    oof, cur = result.oof, result.curves
    y = oof["label"].to_numpy(int)
    time = cur["time"].to_numpy(float)
    observed = cur["observed"].to_numpy(bool)
    out: dict[str, dict[str, float]] = {}
    for m in COMPARED:
        if m in SURVIVAL_MODELS:
            extra = time_metrics(time, observed, curve_matrix(cur, m))
        else:
            extra = _f365_metrics(time, observed, cur[m].to_numpy(float))
        out[m] = {**metrics(y, oof[m].to_numpy()), **extra}
    return out


def build_survival_report(
    events: pd.DataFrame, result: SurvivalResult, *, as_of: date
) -> dict[str, Any]:
    oof = result.oof
    pooled = _pool(result)
    gap = bootstrap_ci(oof, CANDIDATE, CLASSIFIER)
    # Not significantly worse: the CI's upper end reaches zero.
    adopt = gap["hi"] >= 0 if not np.isnan(gap["hi"]) else gap["point"] >= 0
    better_brier = (pooled[CANDIDATE][f"brier_{HORIZON_DAYS}"]
                    < pooled[CLASSIFIER][f"brier_{HORIZON_DAYS}"])
    n_train = sum(f["n_train_events"] for f in result.folds)
    n_lab = sum(f["n_train_labelled"] for f in result.folds)
    return {
        "as_of": as_of.isoformat(),
        "definition": {"event_gap_days": EVENT_GAP_DAYS, "horizon_days": HORIZON_DAYS,
                       "interval_edges": EDGES.tolist()},
        "data": {
            "events": len(events),
            "labelled_events": int(events["labelled"].sum()),
            # Summed over folds: what the survival model trains on vs what
            # the classifier can use.
            "train_events_survival": n_train,
            "train_events_classifier": n_lab,
        },
        "folds": result.folds,
        "pooled": pooled,
        "ci": {
            "pr_auc": {m: bootstrap_ci(oof, m) for m in COMPARED},
            f"{CANDIDATE}_minus_{CLASSIFIER}": gap,
        },
        "decision": {
            "candidate": CANDIDATE,
            "ranking_not_worse": bool(adopt),
            "brier_365_better": bool(better_brier),
            "adopt": bool(adopt and better_brier),
        },
        "reliability": {
            CANDIDATE: reliability(oof["label"].to_numpy(int), oof[CANDIDATE].to_numpy()),
        },
    }


def render_survival_markdown(r: dict[str, Any]) -> str:
    d, pooled, dec = r["data"], r["pooled"], r["decision"]
    gap = r["ci"][f"{CANDIDATE}_minus_{CLASSIFIER}"]
    lines = [
        f"# Repeat-layoff survival backtest — as of {r['as_of']}",
        "",
        f"{d['events']:,} events, {d['labelled_events']:,} with a full covered horizon. "
        f"Across folds the survival models train on {d['train_events_survival']:,} "
        f"event-folds; the classifier can use {d['train_events_classifier']:,}.",
        "",
        "## Pooled out-of-fold metrics",
        "",
        "PR-AUC, ROC-AUC, P@10% and ECE use F(365) on the classifier's labelled test "
        "events. Brier@d, IBS and C@365 are IPCW on every test-year event.",
        "",
        "| model | PR-AUC | ROC-AUC | P@10% | ECE | "
        + " | ".join(f"Brier@{h}" for h in HORIZONS) + " | IBS | C@365 |",
        "|---|---|---|---|---|" + "---|" * len(HORIZONS) + "---|---|",
    ]
    for m in COMPARED:
        p = pooled[m]
        lines.append(
            f"| {m} | {_f(p['pr_auc'])} | {_f(p['roc_auc'])} | {_f(p['precision_at_10pct'])} "
            f"| {_f(p['ece'])} | "
            + " | ".join(_f(p.get(f"brier_{h}", float("nan"))) for h in HORIZONS)
            + f" | {_f(p.get('ibs', float('nan')))} | {_f(p['c_index_365'])} |"
        )
    lines += [
        "",
        "PR-AUC 95% CIs (company-clustered bootstrap): "
        + ", ".join(f"{m} {_f(c['lo'])} to {_f(c['hi'])}" for m, c in r["ci"]["pr_auc"].items()),
        "",
        f"- {CANDIDATE} - {CLASSIFIER} PR-AUC: {_f(gap['point'])} "
        f"[{_f(gap['lo'])}, {_f(gap['hi'])}]",
        f"- Ranking not worse: {dec['ranking_not_worse']}; "
        f"Brier@{HORIZON_DAYS} better: {dec['brier_365_better']} "
        f"→ **adopt {CANDIDATE}: {dec['adopt']}**",
        "",
        "## Per-fold",
        "",
        "| year | train (survival) | train (classifier) | test | "
        + " | ".join(f"{m} PR-AUC" for m in COMPARED) + " | "
        + " | ".join(f"{m} C@365" for m in COMPARED) + " |",
        "|---|---|---|---|" + "---|" * (2 * len(COMPARED)),
    ]
    for f in r["folds"]:
        ms = f["models"]
        lines.append(
            f"| {f['year']} | {f['n_train_events']:,} | {f['n_train_labelled']:,} "
            f"| {f['n_test_labelled']:,} | "
            + " | ".join(_f(ms[m]["pr_auc"]) for m in COMPARED) + " | "
            + " | ".join(_f(ms[m]["c_index_365"]) for m in COMPARED) + " |"
        )
    lines += ["", f"## Calibration of F(365) ({CANDIDATE}, pooled deciles)", "",
              "| mean predicted | observed |", "|---|---|"]
    for row in r["reliability"][CANDIDATE]:
        lines.append(f"| {_f(row['mean_pred'])} | {_f(row['frac_pos'])} |")
    return "\n".join(lines) + "\n"
