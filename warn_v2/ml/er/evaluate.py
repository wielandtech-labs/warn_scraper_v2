"""ER metrics: pairwise and cluster-level (B-cubed), split by enrichment.

Pairwise PR-AUC and precision/recall at a threshold judge the matcher. The
clustering is judged with B-cubed against gold clusters: for each gold
mention, precision is the share of its predicted cluster that is in its gold
cluster, and recall the share of its gold cluster that the prediction kept
together. Gold clusters are the connected components of the gold positive
pairs over the mentions that appear in any gold pair.

Every number is also reported for "enriched" pairs (both sides have a unique
id) and the rest. The weak labels cover only the first kind, and the second
is where the heuristics fail, so the gap between them is the headline caveat.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

from warn_v2.ml.er.labels import UnionFind


def pairwise(y: np.ndarray, p: np.ndarray, tau: float) -> dict[str, float]:
    y = np.asarray(y, int)
    pred = np.asarray(p) >= tau
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    prec = tp / (tp + fp) if tp + fp else float("nan")
    rec = tp / (tp + fn) if tp + fn else float("nan")
    return {
        "n": len(y), "positives": int(y.sum()),
        "pr_auc": float(average_precision_score(y, p)) if 0 < y.sum() < len(y) else float("nan"),
        "precision": prec, "recall": rec,
        "f1": 2 * prec * rec / (prec + rec) if prec + rec > 0 else float("nan"),
    }


def pairwise_from_clusters(labels: np.ndarray, pairs: pd.DataFrame) -> np.ndarray:
    """1.0 where a clustering puts the pair together (to grade a clustering,
    like the heuristic baseline, with the same pairwise metrics)."""
    return (labels[pairs["a"].to_numpy(int)] == labels[pairs["b"].to_numpy(int)]).astype(float)


def gold_clusters(gold: pd.DataFrame) -> dict[int, int]:
    """Mention -> gold cluster id, from gold pairs (a, b, same)."""
    mentions = sorted(set(gold["a"]) | set(gold["b"]))
    index = {m: k for k, m in enumerate(mentions)}
    uf = UnionFind(len(mentions))
    for r in gold[gold["same"] == 1].itertuples(index=False):
        uf.union(index[int(r.a)], index[int(r.b)])
    lab = uf.labels()
    return {m: int(lab[index[m]]) for m in mentions}


def b_cubed(pred: dict[int, int], gold: dict[int, int]) -> dict[str, float]:
    """B-cubed precision, recall and F1 over the gold mentions."""
    mentions = list(gold)
    by_pred: dict[int, set[int]] = defaultdict(set)
    by_gold: dict[int, set[int]] = defaultdict(set)
    for m in mentions:
        by_pred[pred[m]].add(m)
        by_gold[gold[m]].add(m)
    p_sum = r_sum = 0.0
    for m in mentions:
        both = len(by_pred[pred[m]] & by_gold[gold[m]])
        p_sum += both / len(by_pred[pred[m]])
        r_sum += both / len(by_gold[gold[m]])
    n = len(mentions)
    p, r = (p_sum / n, r_sum / n) if n else (float("nan"), float("nan"))
    return {"n": n, "precision": p, "recall": r,
            "f1": 2 * p * r / (p + r) if p + r > 0 else float("nan")}


def by_enrichment(profiles: pd.DataFrame, pairs: pd.DataFrame) -> np.ndarray:
    """True for pairs where both sides carry a unique id."""
    has = profiles["unique_id"].notna().to_numpy()
    return has[pairs["a"].to_numpy(int)] & has[pairs["b"].to_numpy(int)]


def split_pairwise(profiles: pd.DataFrame, pairs: pd.DataFrame, y: np.ndarray,
                   p: np.ndarray, tau: float) -> dict[str, Any]:
    enr = by_enrichment(profiles, pairs)
    return {
        "all": pairwise(y, p, tau),
        "enriched": pairwise(y[enr], p[enr], tau),
        "unenriched": pairwise(y[~enr], p[~enr], tau),
    }
