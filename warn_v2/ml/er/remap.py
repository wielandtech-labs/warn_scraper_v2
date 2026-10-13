"""Company keys from the entity-resolution clustering, for rerunning the
repeat-risk backtests on the model's grouping instead of today's.

Every raw Company row maps to "e<root>", where root is the lowest company id
in its system cluster. The events built from these keys differ from the
standard run (merged employers' notices join one history), so the two
backtests are compared side by side, not event by event.
"""
from __future__ import annotations

import pandas as pd

from warn_v2.ml.er.run import Fitted, clusterings


def er_company_keys(f: Fitted, overrides: pd.DataFrame,
                    rejected: set[frozenset[int]] | None = None) -> dict[int, str]:
    """raw company_id -> "e<lowest company id in its system cluster>".
    rejected: root pairs admins rejected as merges (kept apart)."""
    system = clusterings(f, overrides, rejected)["system"]
    ids = f.profiles["company_id"].astype(int).tolist()
    root: dict[int, int] = {}
    for cid, c in zip(ids, system, strict=True):
        root[int(c)] = min(root.get(int(c), cid), cid)
    return {cid: f"e{root[int(c)]}" for cid, c in zip(ids, system, strict=True)}
