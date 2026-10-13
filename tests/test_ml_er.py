"""Entity resolution: blocking, leakage-free features, labels, clustering, metrics."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from tests.er_synthetic import profiles as synthetic_profiles
from tests.er_synthetic import true_pairs
from warn_v2.ml.er.blocking import candidate_pairs, pair_completeness
from warn_v2.ml.er.cluster import average_linkage, connected_components
from warn_v2.ml.er.evaluate import b_cubed, gold_clusters, pairwise
from warn_v2.ml.er.features import FEATURES, INPUT_COLUMNS, pair_features
from warn_v2.ml.er.labels import (
    component_groups,
    heuristic_clusters,
    override_pairs,
    weak_labels,
)
from warn_v2.ml.er.records import ENRICHMENT_COLUMNS
from warn_v2.ml.er.run import evaluate, fit_all


@pytest.fixture(scope="module")
def synth():
    return synthetic_profiles(n_entities=300)


# --- blocking ----------------------------------------------------------------

def test_blocking_keeps_nearly_every_true_pair_and_prunes_the_rest(synth):
    prof, truth = synth
    cand = candidate_pairs(prof)
    assert pair_completeness(cand, true_pairs(truth)) >= 0.95
    n = len(prof)
    assert len(cand) < 0.1 * n * (n - 1) / 2
    assert (cand["a"] < cand["b"]).all() and not cand.duplicated().any()


# --- features ----------------------------------------------------------------

def _same(x: pd.DataFrame, y: pd.DataFrame) -> bool:
    return bool(((x == y) | (x.isna() & y.isna())).all().all())


def test_features_are_symmetric(synth):
    prof, _ = synth
    pairs = candidate_pairs(prof).head(500)
    fwd = pair_features(prof, pairs)
    rev = pair_features(prof, pairs.rename(columns={"a": "b", "b": "a"})[["a", "b"]])
    assert list(fwd.columns) == FEATURES
    assert np.allclose(fwd.fillna(-1).to_numpy(), rev.fillna(-1).to_numpy())


def test_features_never_read_enrichment(synth):
    prof, _ = synth
    assert set(INPUT_COLUMNS).isdisjoint(ENRICHMENT_COLUMNS)
    pairs = candidate_pairs(prof).head(500)
    scrambled = prof.copy()
    rng = np.random.default_rng(0)
    for col in ENRICHMENT_COLUMNS:
        if col in scrambled:
            scrambled[col] = rng.permutation(scrambled[col].to_numpy())
    assert _same(pair_features(prof, pairs), pair_features(scrambled, pairs))


# --- labels ------------------------------------------------------------------

def test_weak_labels_follow_unique_ids_and_the_website_exception():
    prof = pd.DataFrame({
        "unique_id": ["1", "1", "2", None, "3", "4"],
        "website_domain": [None, None, "x.com", None, "x.com", "x.com"],
        "canonical": ["acme", "acme", "boeing", "zed", "boeing", "boeing defense"],
    })
    pairs = pd.DataFrame({"a": [0, 0, 0, 2, 2], "b": [1, 2, 3, 4, 5]})
    w = weak_labels(prof, pairs).to_numpy()
    assert w[0] == 1 and w[1] == 0 and math.isnan(w[2])
    # Different ids, same name and website: one company split by enrichment.
    assert w[3] == 1
    # Same website but a different name (a subsidiary on the parent's site):
    # still different companies.
    assert w[4] == 0


def test_overrides_become_gold_pairs_and_keep_separate_constraints():
    prof = pd.DataFrame({"company_id": [10, 20, 30]})
    over = pd.DataFrame({"company_id": [30, 20], "target_company_id": [10, None]})
    pos, sep = override_pairs(prof, over)
    assert list(map(tuple, pos[["a", "b"]].to_numpy())) == [(0, 2)] and sep == {1}


def test_group_split_keeps_transitive_pairs_together():
    pairs = pd.DataFrame({"a": [0, 1, 3], "b": [1, 2, 4]})
    groups = component_groups(5, pairs, np.array([True, True, False]))
    assert groups[0] == groups[1] == groups[2] and groups[3] != groups[0]
    assert groups[3] != groups[4]  # a negative pair links nothing


def test_heuristic_baseline_is_the_consolidators_own_code(db):
    """Same rows, same grouping as the nightly consolidator."""
    from warn_v2.db.models import Company
    from warn_v2.ml.er.records import load_profiles
    from warn_v2.scripts.consolidate_companies import consolidate_companies

    for name, uid, site in [
        ("Acme Industries Inc", "111", None), ("Acme Industries LLC", "111", None),
        ("Beta Co", None, None), ("Beta, LLC", None, None),
        ("Summit Inc", "222", None), ("Summit LLC", "333", None),
        ("Boeing", "444", "boeing.com"), ("The Boeing Company", "555", "www.boeing.com"),
        ("Gamma", None, None),
    ]:
        db.add(Company(name=name, unique_id=uid, website=site))
    db.commit()
    prof = load_profiles(db)
    ours = heuristic_clusters(prof)
    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    theirs = {c.id: c.canonical_company_id or c.id for c in db.query(Company)}
    ids = prof["company_id"].tolist()
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            assert (ours[i] == ours[j]) == (theirs[ids[i]] == theirs[ids[j]]), (ids[i], ids[j])


# --- clustering --------------------------------------------------------------

def _pairs(edges):
    return (pd.DataFrame([(a, b) for a, b, _ in edges], columns=["a", "b"]),
            np.array([s for *_, s in edges]))


def test_average_linkage_resists_chaining_that_connected_components_falls_for():
    # Two tight triangles joined by one strong but lone edge.
    pairs, s = _pairs([(0, 1, .95), (0, 2, .95), (1, 2, .95),
                       (3, 4, .95), (3, 5, .95), (4, 5, .95), (2, 3, .9)])
    cc = connected_components(6, pairs, s, 0.5)
    assert len(set(cc)) == 1
    al = average_linkage(6, pairs, s, tau=0.5)
    assert al[0] == al[1] == al[2] and al[3] == al[4] == al[5] and al[0] != al[3]


def test_cannot_link_wins_and_must_link_joins():
    pairs, s = _pairs([(0, 1, .99), (1, 2, .1)])
    al = average_linkage(3, pairs, s, tau=0.5, cannot_link=[(0, 1)])
    assert al[0] != al[1]
    # Must-link joins 1 and 2; 0 then joins on the average (0.99 + 0) / 2.
    al = average_linkage(3, pairs, s, tau=0.4, must_link=[(1, 2)])
    assert al[0] == al[1] == al[2]
    strict = average_linkage(3, pairs, s, tau=0.5, must_link=[(1, 2)])
    assert strict[1] == strict[2] and strict[0] != strict[1]
    # A must-link that would break a cannot-link is ignored.
    al = average_linkage(3, pairs, s, tau=0.4, must_link=[(1, 2)], cannot_link=[(0, 2)])
    assert al[0] != al[2]


def test_large_component_fallback_keeps_cannot_links(monkeypatch):
    from warn_v2.ml.er import cluster

    monkeypatch.setattr(cluster, "MAX_COMPONENT", 3)
    pairs, s = _pairs([(0, 1, .9), (1, 2, .9), (2, 3, .9)])
    al = average_linkage(4, pairs, s, tau=0.5, cannot_link=[(0, 3)])
    assert al[0] != al[3]
    assert len(set(average_linkage(4, pairs, s, tau=0.5))) == 1  # unconstrained: one chain


def test_keep_separate_override_blocks_merges_in_system_mode():
    from warn_v2.ml.er.run import Fitted, clusterings

    prof = pd.DataFrame({"company_id": [10, 20, 30], "unique_id": [None] * 3,
                         "website_domain": [None] * 3, "canonical": ["a", "a", "b"],
                         "name": ["A", "A", "B"], "n_notices": [1, 1, 1],
                         "enriched": [False] * 3, "enrichment_confidence": [None] * 3})
    pairs = pd.DataFrame({"a": [0, 0], "b": [1, 2]})
    f = Fitted(prof, pairs, pd.DataFrame(), np.array([np.nan, np.nan]),
               np.array([0.95, 0.9]), None, np.array([False, False]))  # type: ignore[arg-type]
    over = pd.DataFrame({"company_id": [20, 30], "target_company_id": [None, 10]})
    lab = clusterings(f, over)["system"]
    assert lab[1] != lab[0]  # kept separate despite a 0.95 score
    assert lab[2] == lab[0]  # the admin's merge holds


def test_pair_agreement_counts_without_listing_pairs():
    from warn_v2.ml.er.run import _pair_agreement

    x = np.array([0, 0, 0, 1, 1])  # pairs: 01 02 12 34
    y = np.array([0, 0, 2, 2, 3])  # pairs: 01 23
    assert _pair_agreement(x, y) == {"both": 1, "only_heuristic": 3, "only_this": 1}


# --- metrics -----------------------------------------------------------------

def test_b_cubed_by_hand():
    gold = {1: 0, 2: 0, 3: 1}
    assert b_cubed({1: 0, 2: 0, 3: 1}, gold)["f1"] == 1.0
    # Everything in one predicted cluster: precision (2/3 + 2/3 + 1/3) / 3.
    m = b_cubed({1: 0, 2: 0, 3: 0}, gold)
    assert m["precision"] == pytest.approx(5 / 9) and m["recall"] == 1.0
    # All split: recall (1/2 + 1/2 + 1) / 3.
    m = b_cubed({1: 1, 2: 2, 3: 3}, gold)
    assert m["precision"] == 1.0 and m["recall"] == pytest.approx(2 / 3)


def test_gold_clusters_are_components_of_positive_pairs():
    gold = pd.DataFrame({"a": [1, 2, 4], "b": [2, 3, 5], "same": [1, 1, 0]})
    g = gold_clusters(gold)
    assert g[1] == g[2] == g[3] and g[4] != g[5]


def test_pairwise_threshold_metrics():
    m = pairwise(np.array([1, 1, 0, 0]), np.array([0.9, 0.4, 0.6, 0.1]), 0.5)
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["pr_auc"] > 0.5


# --- end to end --------------------------------------------------------------

def test_model_beats_the_heuristic_on_unenriched_duplicates(synth):
    prof, truth = synth
    fitted = fit_all(prof)
    pairs = true_pairs(truth)
    # Gold: every true pair, plus as many random non-matching candidate pairs.
    cand = fitted.pairs
    neg = cand[truth[cand["a"]] != truth[cand["b"]]].sample(len(pairs), random_state=0)
    gold = pd.concat([pairs.assign(same=1), neg.assign(same=0)], ignore_index=True)
    report = evaluate(fitted, pd.DataFrame(columns=["company_id", "target_company_id"]), gold)

    assert report["blocking_recall"]["weak_positives"] >= 0.95
    assert report["weak_oof"]["model"]["pr_auc"] > 0.9
    g = report["gold"]
    unenr = g["pairwise"]
    assert unenr["system"]["unenriched"]["f1"] > unenr["heuristic"]["unenriched"]["f1"] + 0.1
    assert g["b_cubed"]["system"]["f1"] > g["b_cubed"]["heuristic"]["f1"]
    # Calibrated: out-of-fold scores near the weak-label rate on average.
    lab = fitted.oof_mask
    assert abs(fitted.scores[lab].mean() - fitted.weak[lab].mean()) < 0.05


# --- CLI (database in, aggregates out) ----------------------------------------

def _seed_db(db, n_entities: int = 200):
    from decimal import Decimal

    from tests.er_synthetic import make
    from warn_v2.db.models import Company, Location, Notice

    companies, notices, truth = make(n_entities=n_entities, seed=3)
    for c in companies.itertuples(index=False):
        db.add(Company(id=int(c.id), name=c.name,
                       unique_id=c.unique_id if isinstance(c.unique_id, str) else None,
                       website=c.website if isinstance(c.website, str) else None))
    locs: dict[tuple, Location] = {}
    for k, n in enumerate(notices.itertuples(index=False)):
        key = (n.state, n.city, n.zip)
        if key not in locs:
            locs[key] = Location(state=n.state, city=n.city, zip=n.zip,
                                 lat=Decimal(f"{n.lat:.6f}"), lon=Decimal(f"{n.lon:.6f}"))
            db.add(locs[key])
            db.flush()
        db.add(Notice(notice_id=f"n{k}", state=n.state, employer="x", notice_date=n.notice_date,
                      layoff_count=int(n.layoff_count), address=n.address,
                      company_id=int(n.company_id), location_id=locs[key].id))
    db.commit()
    return companies, truth


def test_cli_samples_then_evaluates_with_gold_and_writes_no_names(db, tmp_path):
    import csv

    from click.testing import CliRunner

    from warn_v2.cli import main

    companies, truth = _seed_db(db)
    res = CliRunner().invoke(main, ["ml-er-sample", "--reports-dir", str(tmp_path), "--n", "60"])
    assert res.exit_code == 0, res.output
    sample_path = tmp_path / "er" / "gold_candidates.csv"
    rows = list(csv.DictReader(sample_path.open(encoding="utf-8")))
    assert rows and {"a_id", "b_id", "a_name", "b_name", "same", "reason"} <= set(rows[0])
    # Some of the sample is pairs blocking dropped, so blocking recall is testable.
    assert any(r["band"] == "unblocked" for r in rows)

    # Label the sample from the synthetic truth, as the audited labels would.
    entity = dict(zip(companies["id"], truth, strict=True))
    with (tmp_path / "er" / "gold.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            r["same"] = str(int(entity[int(r["a_id"])] == entity[int(r["b_id"])]))
            w.writerow(r)

    res = CliRunner().invoke(main, ["ml-er-eval", "--reports-dir", str(tmp_path)])
    assert res.exit_code == 0, res.output
    md = (tmp_path / "er" / "er_eval.md").read_text(encoding="utf-8")
    js = (tmp_path / "er" / "er_eval.json").read_text(encoding="utf-8")
    assert "## Gold set" in md and "B-cubed" in md
    # Aggregates only: no employer name leaves the cluster in the report.
    for name in companies["name"]:
        assert name not in md and name not in js
