"""Resolve company merge maps: admin overrides on top of the automatic merges.

A merge map is ``{duplicate_id: canonical_id}``. The nightly consolidator builds
one from DUNS/name heuristics; admins then correct it through
``CompanyMergeOverride`` rows (``target_company_id`` set = "merge into this",
NULL = "keep separate"). Both the consolidator and the admin API run the same
``apply_overrides`` + ``flatten`` so a manual decision means the same thing
whether it lands immediately (API) or on the next nightly recompute.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

log = logging.getLogger(__name__)


def flatten(merged_into: dict[int, int]) -> dict[int, int]:
    """Resolve every entry to its ultimate root.

    ``canonical_company_id`` is followed only one level by the rollup queries
    (stats/companies routes), so chains like child -> hub -> survivor must be
    collapsed to child -> survivor before writing. Cycle-safe.
    """
    def _root(cid: int) -> int:
        seen: set[int] = set()
        while cid in merged_into and cid not in seen:
            seen.add(cid)
            cid = merged_into[cid]
        return cid

    return {cid: _root(cid) for cid in merged_into}


def apply_overrides(
    merged_into: dict[int, int],
    overrides: Iterable[tuple[int, int | None]],
) -> dict[int, int]:
    """Apply admin overrides to ``merged_into``; returns a new (unflattened) map.

    ``overrides`` are ``(company_id, target_company_id)`` pairs, **newest first**
    — a newer decision wins any conflict with an older one:

    * target NULL -> the row is kept separate (removed from the map). Rows merged
      into it stay under it.
    * target set  -> the row joins the target's group. If the target currently
      sits *under* the row (e.g. the admin picked the clean-named "Kmart
      Corporation", which the consolidator had merged into a store-numbered
      survivor), the target is detached and becomes the root instead — the
      admin's choice of label beats the heuristic's.
    * A manual decision is never undone by a later-processed (older) one; an
      override that would form a cycle through manual edges is skipped + logged.
    """
    out = dict(merged_into)
    manual: set[int] = set()

    def _reaches(start: int, needle: int) -> bool:
        seen: set[int] = set()
        cur = start
        while cur in out and cur not in seen:
            seen.add(cur)
            cur = out[cur]
            if cur == needle:
                return True
        return False

    for src, tgt in overrides:
        if src in manual or tgt == src:
            continue
        if tgt is None:
            manual.add(src)
            out.pop(src, None)
            continue
        if _reaches(tgt, src):
            # The target currently resolves to src. Its own edge is automatic ->
            # detach it so the target becomes the root. If that edge is a (newer)
            # manual one, honoring this override would build a cycle -> skip.
            if tgt in manual:
                log.warning("merge override %s -> %s skipped: would form a cycle", src, tgt)
                continue
            out.pop(tgt, None)
        manual.add(src)
        out[src] = tgt
    return out
