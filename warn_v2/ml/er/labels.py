"""Training labels, the heuristic baseline, and the group split.

Weak labels come from enrichment, so they exist only where both companies
have a unique id. Positive when the ids agree. When they differ: negative,
unless the two rows have the same normalized name *and* the same website,
which marks one company that enrichment split across several ids (exactly
the consolidator's Boeing exception). A shared website alone is not enough:
subsidiaries list the parent's site, and some rows carry a platform domain.

Admin overrides with a target are gold positives. Overrides with no target
("keep separate") don't say from *which* company, so in system clustering
the company is cannot-linked to every candidate partner except rows an
admin explicitly merged into it.
"""
from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pandas as pd


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[max(rx, ry)] = min(rx, ry)

    def labels(self) -> np.ndarray:
        return np.array([self.find(i) for i in range(len(self.parent))])


def weak_labels(profiles: pd.DataFrame, pairs: pd.DataFrame) -> pd.Series:
    """1 / 0 per pair, NaN where either side lacks a unique id."""
    uid = [None if pd.isna(u) else u for u in profiles["unique_id"]]
    web = [None if pd.isna(w) else w for w in profiles["website_domain"]]
    name = profiles["canonical"].tolist()
    a, b = pairs["a"].to_numpy(int), pairs["b"].to_numpy(int)
    out = np.full(len(pairs), np.nan)
    for k, (i, j) in enumerate(zip(a, b, strict=True)):
        if uid[i] is None or uid[j] is None:
            continue
        if uid[i] == uid[j] or (web[i] is not None and web[i] == web[j]
                                and bool(name[i]) and name[i] == name[j]):
            out[k] = 1.0
        else:
            out[k] = 0.0
    return pd.Series(out, index=pairs.index, name="weak")


def weak_positive_pairs(profiles: pd.DataFrame) -> pd.DataFrame:
    """Every same-unique-id pair, blocked or not (to measure blocking recall)."""
    by_uid: dict[str, list[int]] = defaultdict(list)
    for i, u in enumerate(profiles["unique_id"]):
        if not pd.isna(u):
            by_uid[u].append(i)
    rows = [(m[x], m[y]) for m in by_uid.values() if 1 < len(m) <= 200
            for x in range(len(m)) for y in range(x + 1, len(m))]
    return pd.DataFrame(rows, columns=["a", "b"], dtype=int)


def override_pairs(profiles: pd.DataFrame, overrides: pd.DataFrame
                   ) -> tuple[pd.DataFrame, set[int]]:
    """(gold positive pairs a<b, row positions of keep-separate companies).
    overrides: company_id, target_company_id (nullable)."""
    pos = {cid: i for i, cid in enumerate(profiles["company_id"])}
    rows, separate = [], set()
    for r in overrides.itertuples(index=False):
        i = pos.get(int(r.company_id))
        if i is None:
            continue
        if pd.isna(r.target_company_id):
            separate.add(i)
            continue
        j = pos.get(int(r.target_company_id))
        if j is not None and j != i:
            rows.append((min(i, j), max(i, j)))
    return pd.DataFrame(sorted(set(rows)), columns=["a", "b"], dtype=int), separate


def heuristic_clusters(profiles: pd.DataFrame) -> np.ndarray:
    """The nightly consolidator's two passes, replayed without admin
    overrides (those are gold labels, so the baseline must not see them).
    Same code as production: warn_v2.scripts.consolidate_companies
    .heuristic_merge_map. Returns a cluster label per row."""
    from warn_v2.scripts.consolidate_companies import heuristic_merge_map

    rows = [
        SimpleNamespace(
            id=int(r.company_id), name=r.name, name_normalized=r.canonical,
            unique_id=r.unique_id, website=r.website_domain,
            enriched_at=True if r.enriched else None,
            enrichment_confidence=r.enrichment_confidence,
        )
        for r in profiles.itertuples(index=False)
    ]
    # The consolidator's survivor tie-break counts every notice, superseded
    # ones included; profiles keep that count apart from the live one.
    col = "n_notices_all" if "n_notices_all" in profiles else "n_notices"
    counts = dict(zip(profiles["company_id"], profiles[col], strict=True))
    merged = heuristic_merge_map(rows, counts)
    pos = {cid: i for i, cid in enumerate(profiles["company_id"])}
    uf = UnionFind(len(profiles))
    for dup, surv in merged.items():
        uf.union(pos[dup], pos[surv])
    return uf.labels()


def component_groups(n: int, pairs: pd.DataFrame, positive: np.ndarray) -> np.ndarray:
    """Connected component of every row over the positive pairs. Pairs are
    grouped by their `a` side's component, so transitively linked pairs land
    in one fold of a group split."""
    uf = UnionFind(n)
    for i, j in zip(pairs["a"].to_numpy()[positive], pairs["b"].to_numpy()[positive],
                    strict=True):
        uf.union(int(i), int(j))
    return uf.labels()
