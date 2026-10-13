"""Merge suggestions: where the model's clustering disagrees with today's grouping.

Run by hand (`warn-v2 ml-er-suggest`) once the gold evaluation has backed the
model; never on a schedule yet. The output goes only into
``company_merge_suggestions``. An admin accepts a suggestion, which goes through
the normal merge-override path, or rejects it, which only records the
decision. Either way the decision becomes a gold label for the next
``ml-er-eval`` (``load_feedback``), and a rejection also becomes a cannot-link
for every later clustering.

A proposal merges one *current* group into another: each group is keyed by
its root company (``canonical_company_id`` or itself). For every system
cluster that spans two or more current roots, each smaller group is proposed
for merging into the group with the most notices, but only when the model put
the *whole* smaller group in that cluster. Accepting moves the whole group, so
a group the model split must not be proposed on the strength of part of it.
The proposal's score is the average pair score between the two groups
(unscored pairs count as 0), the same linkage rule the clustering used, and it
must reach ``min_score``.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from warn_v2.db.models import CompanyMergeSuggestion
from warn_v2.ml.er.run import Fitted, clusterings, current_roots

MIN_SCORE = 0.8
LIMIT = 200
COLUMNS = ["company_id", "target_company_id", "score"]
# Most cross-group pairs one admin decision contributes to the feedback gold,
# so one big group can't outweigh every other decision.
FEEDBACK_PAIRS_PER_DECISION = 25


def suggestions(
    f: Fitted, overrides: pd.DataFrame, decided: set[frozenset[int]] | None = None,
    rejected: set[frozenset[int]] | None = None,
    *, min_score: float = MIN_SCORE, limit: int = LIMIT,
) -> pd.DataFrame:
    """Proposed merges, strongest first: company_id (a current root) into
    target_company_id (another root), with their linkage score.
    decided: root pairs already ruled on (skipped); rejected: the rejected
    subset of them (cannot-linked in the clustering)."""
    decided = decided or set()
    p = f.profiles
    system = clusterings(f, overrides, rejected)["system"]
    roots = current_roots(p)
    notices = p["n_notices"].to_numpy()
    group_size: dict[int, int] = defaultdict(int)
    for r in roots:
        group_size[int(r)] += 1

    sim: dict[tuple[int, int], float] = {}
    for i, j, s in zip(f.pairs["a"].to_numpy(int), f.pairs["b"].to_numpy(int), f.scores,
                       strict=True):
        sim[(int(i), int(j))] = float(s)

    rows = []
    by_cluster: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(system):
        by_cluster[int(c)].append(i)
    for members in by_cluster.values():
        groups: dict[int, list[int]] = defaultdict(list)
        for i in members:
            groups[int(roots[i])].append(i)
        if len(groups) < 2:
            continue
        keep = max(groups, key=lambda r: (int(notices[groups[r]].sum()), -r))
        for root, rows_in in groups.items():
            if root == keep or frozenset((root, keep)) in decided:
                continue
            if len(rows_in) < group_size[root]:
                continue  # the model split this group; accepting would move all of it
            total = sum(sim.get((min(a, b), max(a, b)), 0.0)
                        for a in rows_in for b in groups[keep])
            score = total / (len(rows_in) * len(groups[keep]))
            if score >= min_score:
                rows.append((root, keep, round(score, 4)))
    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.sort_values(["score", "company_id"], ascending=[False, True]).head(limit) \
        .reset_index(drop=True)


def decided_pairs(session: Session) -> tuple[set[frozenset[int]], set[frozenset[int]]]:
    """(every root pair an admin already ruled on, the rejected ones), in
    either direction."""
    decided, rejected = set(), set()
    for a, b, status in session.execute(
        select(CompanyMergeSuggestion.company_id, CompanyMergeSuggestion.target_company_id,
               CompanyMergeSuggestion.status)
        .where(CompanyMergeSuggestion.status != "open")
    ).all():
        pair = frozenset((int(a), int(b)))
        decided.add(pair)
        if status == "rejected":
            rejected.add(pair)
    return decided, rejected


def write_suggestions(session: Session, proposals: pd.DataFrame,
                      model_version: str) -> dict[str, int]:
    """Replace the open queue with this run's proposals. Every write is
    conditioned on the row still being open in the database, so a decision
    an admin makes while this runs is never overwritten or deleted, and a
    rejected pair is never proposed again."""
    existing = {(s.company_id, s.target_company_id): (s.id, s.status)
                for s in session.scalars(select(CompanyMergeSuggestion))}
    wanted = set()
    stats = {"inserted": 0, "updated": 0, "removed": 0, "skipped_decided": 0}
    now = datetime.now(UTC)
    for r in proposals.itertuples(index=False):
        key = (int(r.company_id), int(r.target_company_id))
        wanted.add(key)
        found = existing.get(key)
        if found is None:
            session.add(CompanyMergeSuggestion(
                company_id=key[0], target_company_id=key[1], score=float(r.score),
                model_version=model_version, status="open"))
            stats["inserted"] += 1
        elif found[1] == "open":
            res = session.execute(
                update(CompanyMergeSuggestion)
                .where(CompanyMergeSuggestion.id == found[0],
                       CompanyMergeSuggestion.status == "open")
                .values(score=float(r.score), model_version=model_version, created_at=now)
            )
            stats["updated" if res.rowcount else "skipped_decided"] += 1  # type: ignore[attr-defined]
        else:
            stats["skipped_decided"] += 1
    stale = [sid for key, (sid, status) in existing.items()
             if status == "open" and key not in wanted]
    if stale:
        res = session.execute(
            delete(CompanyMergeSuggestion)  # the model no longer proposes these
            .where(CompanyMergeSuggestion.id.in_(stale), CompanyMergeSuggestion.status == "open")
        )
        stats["removed"] = int(res.rowcount)  # type: ignore[attr-defined]
    session.flush()
    return stats


def load_feedback(session: Session, profiles: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Decided suggestions as gold pairs: a, b (row positions, a < b), same.

    A decision is about two whole groups, so it labels row pairs, up to
    FEEDBACK_PAIRS_PER_DECISION per decision:
    - rejected: every pair across the two current groups is "different";
    - accepted: the groups are one now, and by the admin's decision one
      company, so pairs of the accepted row with the rest of the joined
      group are "same".
    Biased toward high scores by construction (only proposals get decided),
    so it is reported apart from the audited gold set."""
    rng = random.Random(seed)
    ids = profiles["company_id"].astype(int).tolist()
    roots = current_roots(profiles)
    by_root: dict[int, list[int]] = defaultdict(list)
    for i, r in enumerate(roots):
        by_root[int(r)].append(i)
    pos = {cid: i for i, cid in enumerate(ids)}
    rows = []
    for a, b, status in session.execute(
        select(CompanyMergeSuggestion.company_id, CompanyMergeSuggestion.target_company_id,
               CompanyMergeSuggestion.status)
        .where(CompanyMergeSuggestion.status.in_(("accepted", "rejected")))
    ).all():
        a, b = int(a), int(b)
        if a not in pos or b not in pos:
            continue
        if status == "accepted":
            side_a = [pos[a]]
            side_b = [i for i in by_root.get(int(roots[pos[a]]), []) if i != pos[a]]
        else:
            side_a = by_root.get(int(roots[pos[a]]), [pos[a]])
            side_b = by_root.get(int(roots[pos[b]]), [pos[b]])
        cross = [(min(i, j), max(i, j)) for i in side_a for j in side_b if i != j]
        if len(cross) > FEEDBACK_PAIRS_PER_DECISION:
            cross = rng.sample(cross, FEEDBACK_PAIRS_PER_DECISION)
        rows += [(i, j, int(status == "accepted")) for i, j in cross]
    return pd.DataFrame(rows, columns=["a", "b", "same"]).drop_duplicates(["a", "b"])
