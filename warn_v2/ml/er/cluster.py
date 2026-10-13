"""From pair scores to clusters.

- connected_components: link every pair scoring at least tau and take the
  components. Simple, but one wrong edge chains two large companies together.
- average_linkage: inside each component of the pairs above tau_low, merge
  greedily while two clusters' *average* pair score (unscored pairs count as
  0) stays at or above tau. A single strong edge can't drag in a cluster that
  the rest of the evidence says is different. Cannot-link pairs never end up
  together, and must-link pairs start together (unless that would break a
  cannot-link). Components too large for average linkage fall back to
  single linkage at tau, under the same constraints.
"""
from __future__ import annotations

import heapq
from collections import defaultdict

import numpy as np
import pandas as pd

from warn_v2.ml.er.labels import UnionFind

MAX_COMPONENT = 2000  # larger components fall back to constrained single linkage


def connected_components(n: int, pairs: pd.DataFrame, scores: np.ndarray,
                         tau: float) -> np.ndarray:
    uf = UnionFind(n)
    keep = scores >= tau
    for i, j in zip(pairs["a"].to_numpy()[keep], pairs["b"].to_numpy()[keep], strict=True):
        uf.union(int(i), int(j))
    return uf.labels()


def average_linkage(
    n: int, pairs: pd.DataFrame, scores: np.ndarray, *, tau: float, tau_low: float = 0.2,
    must_link: list[tuple[int, int]] | None = None,
    cannot_link: list[tuple[int, int]] | None = None,
) -> np.ndarray:
    a, b = pairs["a"].to_numpy(int), pairs["b"].to_numpy(int)
    sim: dict[tuple[int, int], float] = {}
    for i, j, s in zip(a, b, scores, strict=True):
        sim[(i, j)] = max(float(s), sim.get((i, j), 0.0))
    for i, j in must_link or []:
        sim[(min(i, j), max(i, j))] = 1.0
    cannot = {(min(i, j), max(i, j)) for i, j in cannot_link or []}

    # Components over the edges worth considering (and the must-links).
    uf = UnionFind(n)
    for (i, j), s in sim.items():
        if s >= tau_low:
            uf.union(i, j)
    comp = uf.labels()
    members: dict[int, list[int]] = defaultdict(list)
    for i, c in enumerate(comp):
        members[int(c)].append(i)

    out = np.arange(n)
    for nodes in members.values():
        if len(nodes) == 1:
            continue
        linkage = _single_link if len(nodes) > MAX_COMPONENT else _agglomerate
        for i, cl in linkage(nodes, sim, cannot, tau, must_link or []).items():
            out[i] = cl
    return out


class _Clusters:
    """Disjoint clusters with per-cluster cannot-link sets and pair-score sums."""

    def __init__(self, nodes: list[int], sim: dict[tuple[int, int], float],
                 cannot: set[tuple[int, int]]) -> None:
        node_set = set(nodes)
        self.owner = {i: i for i in nodes}
        self.members: dict[int, list[int]] = {i: [i] for i in nodes}
        self.total: dict[int, dict[int, float]] = defaultdict(dict)
        for (i, j), sc in sim.items():
            if i in node_set and j in node_set:
                self.total[i][j] = self.total[i].get(j, 0.0) + sc
                self.total[j][i] = self.total[j].get(i, 0.0) + sc
        self.banned: dict[int, set[int]] = defaultdict(set)
        for i, j in cannot:
            if i in node_set and j in node_set:
                self.banned[i].add(j)
                self.banned[j].add(i)

    def allowed(self, x: int, y: int) -> bool:
        return x != y and y not in self.banned[x]

    def merge(self, x: int, y: int) -> int:
        keep, gone = min(x, y), max(x, y)
        self.members[keep] += self.members.pop(gone)
        for i in self.members[keep]:
            self.owner[i] = keep
        for k, sc in self.total.pop(gone, {}).items():
            self.total[k].pop(gone, None)
            if k != keep:
                self.total[keep][k] = self.total[keep].get(k, 0.0) + sc
                self.total[k][keep] = self.total[keep][k]
        self.total[keep].pop(keep, None)
        for k in self.banned.pop(gone, set()):
            self.banned[k].discard(gone)
            if k != keep:
                self.banned[keep].add(k)
                self.banned[k].add(keep)
        return keep

    def must_links(self, must_link: list[tuple[int, int]]) -> None:
        for i, j in must_link:
            if i in self.owner and j in self.owner:
                x, y = self.owner[i], self.owner[j]
                if self.allowed(x, y):
                    self.merge(x, y)

    def labels(self) -> dict[int, int]:
        return {i: min(v) for v in self.members.values() for i in v}


def _single_link(nodes: list[int], sim: dict[tuple[int, int], float],
                 cannot: set[tuple[int, int]], tau: float,
                 must_link: list[tuple[int, int]]) -> dict[int, int]:
    """Fallback for very large components: merge along edges >= tau,
    strongest first, never across a cannot-link (cheaper than average
    linkage, and still constrained)."""
    cl = _Clusters(nodes, sim, cannot)
    cl.must_links(must_link)
    node_set = set(nodes)
    edges = sorted(((sc, i, j) for (i, j), sc in sim.items()
                    if sc >= tau and i in node_set and j in node_set), reverse=True)
    for _, i, j in edges:
        x, y = cl.owner[i], cl.owner[j]
        if cl.allowed(x, y):
            cl.merge(x, y)
    return cl.labels()


def _agglomerate(nodes: list[int], sim: dict[tuple[int, int], float],
                 cannot: set[tuple[int, int]], tau: float,
                 must_link: list[tuple[int, int]]) -> dict[int, int]:
    """Greedy average linkage on one component, driven by a max-heap of
    cluster pairs with lazy invalidation: an entry is stale once either
    cluster has merged since it was pushed. Unscored pairs contribute 0, so
    only clusters joined by some scored edge can reach tau > 0."""
    cl = _Clusters(nodes, sim, cannot)
    cl.must_links(must_link)
    version = dict.fromkeys(cl.members, 0)

    def avg(x: int, y: int) -> float:
        return cl.total[x][y] / (len(cl.members[x]) * len(cl.members[y]))

    heap = [(-avg(x, y), x, y, 0, 0) for x, row in cl.total.items()
            for y in row if x < y and cl.allowed(x, y)]
    heapq.heapify(heap)
    while heap:
        neg, x, y, vx, vy = heapq.heappop(heap)
        if -neg < tau:
            break
        if x not in cl.members or y not in cl.members or (vx, vy) != (version[x], version[y]):
            continue  # stale
        if not cl.allowed(x, y):
            continue
        keep = cl.merge(x, y)
        version[keep] += 1
        for k in cl.total[keep]:
            if cl.allowed(keep, k):
                a, b = min(keep, k), max(keep, k)
                heapq.heappush(heap, (-avg(a, b), a, b, version[a], version[b]))
    return cl.labels()
