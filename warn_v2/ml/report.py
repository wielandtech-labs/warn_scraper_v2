"""Backtest report: the JSON the pipeline keeps, and a markdown rendering."""
from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from warn_v2.ml.backtest import (
    MODELS,
    RULES,
    BacktestResult,
    bootstrap_ci,
    fit,
    fold_split,
    metrics,
    reliability,
)
from warn_v2.ml.events import EVENT_GAP_DAYS, FEATURES, HORIZON_DAYS, km_repeat_curve

SIZE_BUCKETS = [(0, 100, "<100"), (100, 500, "100-499"), (500, float("inf"), "500+")]


def choose(result: BacktestResult) -> dict[str, Any]:
    """logreg unless gbm's PR-AUC is better with a CI that excludes zero both
    pooled AND without 2020 — the simpler model wins ties. The 2020 wave is
    ~30% of test events, so a pooled-only gate would pick the model that
    handles one atypical year best."""
    oof = result.oof
    diff = bootstrap_ci(oof, "gbm", "logreg")
    diff_ex = bootstrap_ci(oof[oof["fold"] != 2020], "gbm", "logreg")
    name = "gbm" if diff["lo"] > 0 and diff_ex["lo"] > 0 else "logreg"
    return {"model": name, "gbm_minus_logreg_pr_auc": diff,
            "gbm_minus_logreg_pr_auc_ex_2020": diff_ex}


def _slices(oof: pd.DataFrame, model: str) -> dict[str, list[dict[str, Any]]]:
    workers = np.expm1(oof["day_layoffs_log"])
    size = pd.Series("unknown", index=oof.index)
    for lo, hi, lab in SIZE_BUCKETS:
        size[(oof["day_layoffs_log"] > 0) & (workers >= lo) & (workers < hi)] = lab
    groups = {
        "history": np.where(oof["prior_events"] > 0, "prior filer", "first-time filer"),
        "event_size": size.to_numpy(),
        "type": np.where(oof["day_closure_frac"] >= 0.5, "closure", "layoff"),
        "regime": np.where(oof["t0"].dt.year >= 2020, "2020+", "pre-2020"),
        "state": oof["state"].to_numpy(),
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for dim, labels in groups.items():
        rows = []
        for lab in pd.unique(labels):
            sel = labels == lab
            if sel.sum() < 200:
                continue
            y = oof.loc[sel, "label"].to_numpy(int)
            if y.min() == y.max():
                continue
            rows.append({"slice": str(lab), **metrics(y, oof.loc[sel, model].to_numpy())})
        out[dim] = sorted(rows, key=lambda r: -r["n"])
    out["state"] = out["state"][:12]
    return out


def importance(events: pd.DataFrame, year: int, model: str) -> list[dict[str, Any]]:
    """Permutation importance (drop in PR-AUC) on one fold's test year."""
    train, test = fold_split(events, year)
    fitted = fit(model, train)
    assert fitted.pipeline is not None
    res = permutation_importance(
        fitted.pipeline, test[FEATURES], test["label"].astype(int),
        scoring="average_precision", n_repeats=5, random_state=0,
    )
    rows = [
        {"feature": f, "mean": float(m), "std": float(s)}
        for f, m, s in zip(FEATURES, res.importances_mean, res.importances_std, strict=True)
    ]
    return sorted(rows, key=lambda r: -r["mean"])


def build_report(
    notices: pd.DataFrame, events: pd.DataFrame, result: BacktestResult, *, as_of: date
) -> dict[str, Any]:
    oof = result.oof
    lab = events[events["labelled"]]
    def pool(df: pd.DataFrame) -> dict[str, dict[str, float]]:
        return {
            m: metrics(df["label"].to_numpy(int), df[m].to_numpy(), probabilistic=m not in RULES)
            for m in MODELS
        }

    pooled = pool(oof)
    # The 2020 wave is a third of the test events in some states and a regime
    # of its own; pooled numbers shouldn't be read only through it.
    pooled_ex_2020 = pool(oof[oof["fold"] != 2020])
    chosen = choose(result)
    best = chosen["model"]
    return {
        "as_of": as_of.isoformat(),
        "definition": {"event_gap_days": EVENT_GAP_DAYS, "horizon_days": HORIZON_DAYS,
                       "features": FEATURES},
        "data": {
            "notices": len(notices),
            "companies": int(notices["company_key"].nunique()),
            "events": len(events),
            "labelled_events": len(lab),
            "labelled_prevalence": float(lab["label"].mean()),
            "km_repeat": {str(d): p for d, p in
                          km_repeat_curve(events, [90, 180, 365, 730], as_of=as_of).items()},
        },
        "folds": result.folds,
        "pooled": pooled,
        "pooled_ex_2020": pooled_ex_2020,
        "ci": {
            "pr_auc": {m: bootstrap_ci(oof, m) for m in MODELS if m != "base_rate"},
            # Against the strongest hand rule, not the weakest.
            "logreg_minus_prior_events": bootstrap_ci(oof, "logreg", "prior_events"),
            "gbm_minus_prior_events": bootstrap_ci(oof, "gbm", "prior_events"),
        },
        "chosen": chosen,
        "reliability": {
            best: reliability(oof["label"].to_numpy(int), oof[best].to_numpy()),
            f"{best}_uncalibrated": reliability(
                oof["label"].to_numpy(int), oof[f"{best}_raw"].to_numpy()
            ),
        },
        "slices": _slices(oof, best),
        "importance": importance(events, int(oof["fold"].max()), best),
    }


def _f(x: float, nd: int = 3) -> str:
    return "—" if math.isnan(x) else f"{x:.{nd}f}"


def render_markdown(r: dict[str, Any]) -> str:
    d, pooled, best = r["data"], r["pooled"], r["chosen"]["model"]
    lines = [
        f"# Repeat-layoff backtest — as of {r['as_of']}",
        "",
        f"{d['notices']:,} notices → {d['companies']:,} companies → {d['events']:,} events; "
        f"{d['labelled_events']:,} labelled (horizon observed + covered). "
        f"Labelled prevalence {_f(d['labelled_prevalence'])}.",
        "",
        "Kaplan-Meier P(next filing within d days): "
        + ", ".join(f"{k}d {_f(v)}" for k, v in d["km_repeat"].items()),
        "",
        "## Pooled out-of-fold metrics",
        "",
        "| model | PR-AUC | ROC-AUC | P@10% | Brier | ECE |",
        "|---|---|---|---|---|---|",
    ]
    for label, table in (("", pooled), (" (ex-2020)", r["pooled_ex_2020"])):
        for m in MODELS:
            p = table[m]
            lines.append(
                f"| {m}{label} | {_f(p['pr_auc'])} | {_f(p['roc_auc'])} "
                f"| {_f(p['precision_at_10pct'])} "
                f"| {_f(p.get('brier', float('nan')))} | {_f(p.get('ece', float('nan')))} |"
            )
    ci = r["ci"]
    lines += [
        "",
        "PR-AUC 95% CIs (company-clustered bootstrap): "
        + ", ".join(f"{m} {_f(c['lo'])} to {_f(c['hi'])}" for m, c in ci["pr_auc"].items()),
        "",
        *(
            f"- {m} - prior_events: {_f(c['point'])} [{_f(c['lo'])}, {_f(c['hi'])}]"
            for m, c in (("logreg", ci["logreg_minus_prior_events"]),
                         ("gbm", ci["gbm_minus_prior_events"]))
        ),
        f"- gbm - logreg: {_f(r['chosen']['gbm_minus_logreg_pr_auc']['point'])} "
        f"[{_f(r['chosen']['gbm_minus_logreg_pr_auc']['lo'])}, "
        f"{_f(r['chosen']['gbm_minus_logreg_pr_auc']['hi'])}]; ex-2020 "
        f"{_f(r['chosen']['gbm_minus_logreg_pr_auc_ex_2020']['point'])} "
        f"[{_f(r['chosen']['gbm_minus_logreg_pr_auc_ex_2020']['lo'])}, "
        f"{_f(r['chosen']['gbm_minus_logreg_pr_auc_ex_2020']['hi'])}] → **chosen: {best}**",
        "",
        "## Per-fold PR-AUC",
        "",
        "| year | train | test | prevalence | " + " | ".join(MODELS) + " |",
        "|---|---|---|---|" + "---|" * len(MODELS),
    ]
    for f in r["folds"]:
        lines.append(
            f"| {f['year']} | {f['n_train']:,} | {f['n_test']:,} "
            f"| {_f(f['models']['base_rate']['prevalence'])} | "
            + " | ".join(_f(f["models"][m]["pr_auc"]) for m in MODELS) + " |"
        )
    lines += ["", f"## Calibration ({best}, pooled, equal-frequency deciles)", "",
              "| mean predicted | observed | uncalibrated predicted |", "|---|---|---|"]
    for cal, raw in zip(r["reliability"][best], r["reliability"][f"{best}_uncalibrated"],
                        strict=False):
        lines.append(f"| {_f(cal['mean_pred'])} | {_f(cal['frac_pos'])} | {_f(raw['mean_pred'])} |")
    lines += ["", f"## Slices ({best})", ""]
    for dim, rows in r["slices"].items():
        lines += [f"**{dim}**", "", "| slice | n | prevalence | PR-AUC | lift | ECE |",
                  "|---|---|---|---|---|---|"]
        for s in rows:
            lift = s["pr_auc"] / s["prevalence"] if s["prevalence"] else float("nan")
            lines.append(f"| {s['slice']} | {s['n']:,} | {_f(s['prevalence'])} "
                         f"| {_f(s['pr_auc'])} | {_f(lift, 2)}x | {_f(s['ece'])} |")
        lines.append("")
    lines += ["## Permutation importance (last fold, ΔPR-AUC)", "",
              "| feature | mean | std |", "|---|---|---|"]
    for row in r["importance"]:
        lines.append(f"| {row['feature']} | {_f(row['mean'], 4)} | {_f(row['std'], 4)} |")
    return "\n".join(lines) + "\n"
