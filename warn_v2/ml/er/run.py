"""End to end: build pairs, train on weak labels, cluster, evaluate, sample.

Reports carry aggregates only. Employer names leave the cluster only in
the gold-candidate CSV, which stays on the reports PVC.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from warn_v2.ml.er.blocking import candidate_pairs, pair_completeness, trigram_pairs
from warn_v2.ml.er.cluster import average_linkage, connected_components
from warn_v2.ml.er.evaluate import (
    b_cubed,
    by_enrichment,
    gold_clusters,
    pairwise,
    pairwise_from_clusters,
    split_pairwise,
)
from warn_v2.ml.er.features import FEATURES, pair_features
from warn_v2.ml.er.labels import (
    component_groups,
    heuristic_clusters,
    override_pairs,
    weak_labels,
    weak_positive_pairs,
)
from warn_v2.ml.er.model import Matcher, cross_fit

TAU = 0.5
# A tenth of the gold sample comes from pairs blocking dropped, found by a
# looser trigram search, so gold blocking recall measures something.
NEAR_MISS_SHARE = 0.1
NEAR_MISS_K = 30
NEAR_MISS_COS = 0.3
JW_BASELINE = 0.92
SCORE_BANDS = [(0.0, 0.1), (0.1, 0.3), (0.3, 0.7), (0.7, 0.9), (0.9, 1.01)]


@dataclass
class Fitted:
    profiles: pd.DataFrame
    pairs: pd.DataFrame  # candidates: a, b
    X: pd.DataFrame
    weak: np.ndarray  # 1/0/NaN per candidate
    scores: np.ndarray  # calibrated; out-of-fold where the pair was trained on
    matcher: Matcher
    oof_mask: np.ndarray  # True where `scores` is out-of-fold


def fit_all(profiles: pd.DataFrame) -> Fitted:
    pairs = candidate_pairs(profiles)
    X = pair_features(profiles, pairs)
    weak = weak_labels(profiles, pairs).to_numpy()
    lab = ~np.isnan(weak)
    if lab.sum() < 50 or len(np.unique(weak[lab])) < 2:
        raise ValueError(f"too few weak labels to train ({int(lab.sum())})")
    y = weak[lab].astype(int)
    comp = component_groups(len(profiles), pairs[lab].reset_index(drop=True), y == 1)
    groups = comp[pairs.loc[lab, "a"].to_numpy(int)]
    oof, matcher = cross_fit(X[lab].reset_index(drop=True), y, groups)
    scores = matcher.predict(X)
    scores[lab] = oof
    return Fitted(profiles, pairs, X, weak, scores, matcher, lab)


def _constraints(f: Fitted, overrides: pd.DataFrame
                 ) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """System mode: unique-id agreement must-links, disagreement cannot-links
    (the weak labels, used as constraints rather than evidence), plus the
    admins' decisions. A merge override must-links the pair. A keep-separate
    override cannot-links the company to every candidate partner, except
    rows an admin merged into it."""
    a, b = f.pairs["a"].to_numpy(int), f.pairs["b"].to_numpy(int)
    must = [(int(i), int(j)) for i, j, w in zip(a, b, f.weak, strict=True) if w == 1]
    cannot = [(int(i), int(j)) for i, j, w in zip(a, b, f.weak, strict=True) if w == 0]
    over_pos, separate = override_pairs(f.profiles, overrides)
    merged_in = set(zip(over_pos["a"], over_pos["b"], strict=True))
    must += [(int(i), int(j)) for i, j in merged_in]
    cannot += [(int(i), int(j)) for i, j in zip(a, b, strict=True)
               if (i in separate or j in separate) and (i, j) not in merged_in]
    return must, cannot


def clusterings(f: Fitted, overrides: pd.DataFrame | None = None) -> dict[str, np.ndarray]:
    """Note: the system clustering applies admin overrides as constraints, so
    on override pairs it is graded on its own inputs; override recall is
    reported for the model-only clusterings and the heuristic for that reason."""
    n = len(f.profiles)
    if overrides is None:
        overrides = pd.DataFrame(columns=["company_id", "target_company_id"])
    must, cannot = _constraints(f, overrides)
    return {
        "heuristic": heuristic_clusters(f.profiles),
        "model_cc": connected_components(n, f.pairs, f.scores, TAU),
        "model_avg": average_linkage(n, f.pairs, f.scores, tau=TAU),
        "system": average_linkage(n, f.pairs, f.scores, tau=TAU,
                                  must_link=must, cannot_link=cannot),
    }


def load_gold(path: Path, profiles: pd.DataFrame) -> pd.DataFrame:
    """Gold CSV (a_id, b_id, same) -> a, b row positions (a < b), same 1/0.
    Rows marked anything but 1/0 (e.g. '?') are skipped."""
    pos = {cid: i for i, cid in enumerate(profiles["company_id"])}
    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            same = (r.get("same") or "").strip()
            i, j = pos.get(int(r["a_id"])), pos.get(int(r["b_id"]))
            if same in {"0", "1"} and i is not None and j is not None and i != j:
                rows.append((min(i, j), max(i, j), int(same)))
    return pd.DataFrame(rows, columns=["a", "b", "same"]).drop_duplicates(["a", "b"])


def _score_pairs(f: Fitted, pairs: pd.DataFrame, feats: pd.DataFrame
                 ) -> tuple[np.ndarray, np.ndarray]:
    """(model score, blocked?) for arbitrary pairs, given their features.
    Candidates reuse their stored (out-of-fold where trained) score; others
    are scored fresh."""
    index = {(int(a), int(b)): k for k, (a, b) in
             enumerate(zip(f.pairs["a"], f.pairs["b"], strict=True))}
    keys = list(zip(pairs["a"].astype(int), pairs["b"].astype(int), strict=True))
    blocked = np.array([k in index for k in keys])
    scores = np.zeros(len(pairs))
    if blocked.any():
        scores[blocked] = f.scores[[index[k] for k, hit in zip(keys, blocked, strict=True)
                                    if hit]]
    if (~blocked).any():
        scores[~blocked] = f.matcher.predict(feats[~blocked].reset_index(drop=True))
    return scores, blocked


def evaluate(f: Fitted, overrides: pd.DataFrame, gold: pd.DataFrame | None) -> dict[str, Any]:
    n = len(f.profiles)
    lab = f.oof_mask
    y = f.weak[lab].astype(int)
    clusters = clusterings(f, overrides)
    weak_pos = weak_positive_pairs(f.profiles)
    over_pos, _ = override_pairs(f.profiles, overrides)
    jw = f.X["name_jw"].to_numpy()

    report: dict[str, Any] = {
        "data": {
            "companies": n,
            "enriched_companies": int(f.profiles["unique_id"].notna().sum()),
            "candidate_pairs": len(f.pairs),
            "reduction_ratio": 1 - len(f.pairs) / max(1, n * (n - 1) / 2),
            "weak_labelled_pairs": int(lab.sum()),
            "weak_positive_pairs": int(y.sum()),
            "override_positive_pairs": len(over_pos),
        },
        "blocking_recall": {
            "weak_positives": pair_completeness(f.pairs, weak_pos),
            "override_positives": pair_completeness(f.pairs, over_pos),
        },
        "weak_oof": {
            "model": pairwise(y, f.scores[lab], TAU),
            "jaro_winkler": pairwise(y, (jw[lab] >= JW_BASELINE).astype(float), 0.5),
        },
        "merges": {
            name: int(n - len(np.unique(lab_))) for name, lab_ in clusters.items()
        },
        "agreement_with_heuristic": {
            name: _pair_agreement(clusters["heuristic"], lab_)
            for name, lab_ in clusters.items() if name != "heuristic"
        },
    }
    if len(over_pos):
        report["override_recall"] = {
            name: float(pairwise_from_clusters(lab_, over_pos).mean())
            for name, lab_ in clusters.items() if name != "system"
        }
    if gold is not None and len(gold):
        gold = gold.reset_index(drop=True)
        g_feats = pair_features(f.profiles, gold[["a", "b"]])
        g_scores, g_blocked = _score_pairs(f, gold[["a", "b"]], g_feats)
        end_to_end = np.where(g_blocked, g_scores, 0.0)
        gy = gold["same"].to_numpy(int)
        gc = gold_clusters(gold)
        enr = by_enrichment(f.profiles, gold)
        report["gold"] = {
            "pairs": len(gold), "positives": int(gy.sum()),
            "enriched_pairs": int(enr.sum()),
            "blocking_recall": float(g_blocked[gy == 1].mean()) if gy.sum() else math.nan,
            "pairwise": {
                "model": split_pairwise(f.profiles, gold, gy, end_to_end, TAU),
                "jaro_winkler": split_pairwise(
                    f.profiles, gold, gy,
                    (g_feats["name_jw"].to_numpy() >= JW_BASELINE).astype(float), 0.5),
                **{
                    name: split_pairwise(f.profiles, gold, gy,
                                         pairwise_from_clusters(lab_, gold), 0.5)
                    for name, lab_ in clusters.items()
                },
            },
            "b_cubed": {
                name: b_cubed({m: int(lab_[m]) for m in gc}, gc)
                for name, lab_ in clusters.items()
            },
        }
    return report


def _pair_agreement(x: np.ndarray, y: np.ndarray) -> dict[str, int]:
    """How two clusterings differ, counted in co-clustered pairs, from the
    contingency table (pairs together in both = sum of C(n_ij, 2)), so a
    huge cluster costs memory linear in rows, not quadratic."""
    def pairs_in(counts: np.ndarray) -> int:
        return int((counts * (counts - 1) // 2).sum())

    _, both = np.unique(np.stack([x, y], axis=1), axis=0, return_counts=True)
    _, nx = np.unique(x, return_counts=True)
    _, ny = np.unique(y, return_counts=True)
    shared = pairs_in(both)
    return {"both": shared, "only_heuristic": pairs_in(nx) - shared,
            "only_this": pairs_in(ny) - shared}


def _near_misses(f: Fitted, limit: int, rng: np.random.Generator) -> pd.DataFrame:
    """Pairs a looser trigram search finds but blocking dropped. Labelling
    some of them is the only way gold blocking recall can come out below 1:
    a gold set drawn from candidates alone is blocked by construction."""
    loose = trigram_pairs(f.profiles["canonical"], k=NEAR_MISS_K, min_cosine=NEAR_MISS_COS)
    blocked = set(zip(f.pairs["a"].astype(int), f.pairs["b"].astype(int), strict=True))
    miss = sorted(loose - blocked)
    if not miss:
        return pd.DataFrame(columns=["a", "b"], dtype=int)
    pick = rng.choice(len(miss), min(limit, len(miss)), replace=False)
    return pd.DataFrame([miss[i] for i in sorted(pick)], columns=["a", "b"])


def sample_gold_candidates(f: Fitted, n: int = 400, seed: int = 0) -> pd.DataFrame:
    """~n pairs for labelling: candidates stratified by score band x
    enrichment, plus a NEAR_MISS_SHARE of pairs blocking dropped."""
    rng = np.random.default_rng(seed)
    enr = by_enrichment(f.profiles, f.pairs)
    strata = [(lo, hi, e) for lo, hi in SCORE_BANDS for e in (True, False)]
    n_miss = round(n * NEAR_MISS_SHARE)
    per = max(1, (n - n_miss) // len(strata))
    picked: list[tuple[int, int, float, str, bool]] = []
    for lo, hi, e in strata:
        idx = np.flatnonzero((f.scores >= lo) & (f.scores < hi) & (enr == e))
        for k in (rng.choice(idx, min(per, len(idx)), replace=False) if len(idx) else []):
            picked.append((int(f.pairs.at[k, "a"]), int(f.pairs.at[k, "b"]),
                           float(f.scores[k]), f"{lo:.1f}-{min(hi, 1):.1f}", bool(e)))
    misses = _near_misses(f, n_miss, rng)
    if len(misses):
        m_scores = f.matcher.predict(pair_features(f.profiles, misses))
        m_enr = by_enrichment(f.profiles, misses)
        picked += [(int(a), int(b), float(sc), "unblocked", bool(e)) for a, b, sc, e in
                   zip(misses["a"], misses["b"], m_scores, m_enr, strict=True)]
    p = f.profiles
    rows = []
    for i, j, score, band, e in picked:
        rows.append({
            "a_id": int(p.at[i, "company_id"]), "b_id": int(p.at[j, "company_id"]),
            "a_name": p.at[i, "name"], "b_name": p.at[j, "name"],
            "a_states": " ".join(sorted(p.at[i, "states"])),
            "b_states": " ".join(sorted(p.at[j, "states"])),
            "a_cities": "; ".join(sorted(c.split("|", 1)[1] for c in p.at[i, "cities"])[:5]),
            "b_cities": "; ".join(sorted(c.split("|", 1)[1] for c in p.at[j, "cities"])[:5]),
            "a_dates": _date_span(p.at[i, "dates"]), "b_dates": _date_span(p.at[j, "dates"]),
            "a_notices": int(p.at[i, "n_notices"]), "b_notices": int(p.at[j, "n_notices"]),
            "a_addresses": " | ".join(p.at[i, "addresses"]),
            "b_addresses": " | ".join(p.at[j, "addresses"]),
            "score": round(score, 3), "band": band,
            "enriched_pair": e, "same": "", "reason": "",
        })
    out = pd.DataFrame(rows)
    return out.sample(frac=1.0, random_state=seed).reset_index(drop=True) if len(out) else out


def _date_span(d: np.ndarray) -> str:
    return f"{d[0]}..{d[-1]}" if len(d) else ""


def _f(x: float, nd: int = 3) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def render_markdown(r: dict[str, Any], as_of: date) -> str:
    d = r["data"]
    lines = [
        f"# Entity resolution evaluation — as of {as_of.isoformat()}",
        "",
        f"{d['companies']:,} company rows ({d['enriched_companies']:,} enriched) → "
        f"{d['candidate_pairs']:,} candidate pairs (reduction ratio "
        f"{_f(d['reduction_ratio'], 5)}). Weak labels: {d['weak_labelled_pairs']:,} pairs, "
        f"{d['weak_positive_pairs']:,} positive. Admin merge overrides: "
        f"{d['override_positive_pairs']:,} pairs.",
        "",
        "## Blocking recall",
        "",
        *(f"- {k}: {_f(v)}" for k, v in r["blocking_recall"].items()),
        "",
        "## Matcher on weak labels (out-of-fold, grouped by company)",
        "",
        "Every pair here is enriched by construction; see the gold section for the rest.",
        "",
        "| model | n | PR-AUC | precision | recall | F1 |",
        "|---|---|---|---|---|---|",
    ]
    for name, m in r["weak_oof"].items():
        lines.append(f"| {name} | {m['n']:,} | {_f(m['pr_auc'])} | {_f(m['precision'])} "
                     f"| {_f(m['recall'])} | {_f(m['f1'])} |")
    lines += ["", "## Clusterings", "",
              "| clustering | rows merged away | pairs shared with heuristic | "
              "only heuristic | only this |", "|---|---|---|---|---|"]
    for name, merged in r["merges"].items():
        ag = r["agreement_with_heuristic"].get(name)
        cells = (f"{ag['both']:,} | {ag['only_heuristic']:,} | {ag['only_this']:,}"
                 if ag else "— | — | —")
        lines.append(f"| {name} | {merged:,} | {cells} |")
    if "override_recall" in r:
        lines += ["", "Recall on admin merge overrides (pairs kept together): "
                  + ", ".join(f"{k} {_f(v)}" for k, v in r["override_recall"].items())]
    g = r.get("gold")
    if g:
        lines += [
            "", "## Gold set",
            "",
            f"{g['pairs']:,} labelled pairs ({g['positives']:,} same, "
            f"{g['enriched_pairs']:,} enriched). Blocking recall on gold positives: "
            f"{_f(g['blocking_recall'])} (the sample includes pairs blocking dropped; "
            "pairs outside the looser search are not covered, so this is an upper bound).",
            "",
            "| system | slice | n | PR-AUC | precision | recall | F1 |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, sl in g["pairwise"].items():
            for part in ("all", "enriched", "unenriched"):
                m = sl[part]
                lines.append(f"| {name} | {part} | {m['n']:,} | {_f(m['pr_auc'])} "
                             f"| {_f(m['precision'])} | {_f(m['recall'])} | {_f(m['f1'])} |")
        lines += ["", "**B-cubed over gold mentions**", "",
                  "| clustering | precision | recall | F1 |", "|---|---|---|---|"]
        for name, m in g["b_cubed"].items():
            lines.append(f"| {name} | {_f(m['precision'])} | {_f(m['recall'])} | {_f(m['f1'])} |")
    return "\n".join(lines) + "\n"


__all__ = ["FEATURES", "Fitted", "evaluate", "fit_all", "load_gold", "render_markdown",
           "sample_gold_candidates"]
