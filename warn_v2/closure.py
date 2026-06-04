"""Normalize freeform WARN closure-type text into filterable categories.

State sources record the layoff-vs-closure distinction inconsistently: most pass
the raw column value through verbatim ("Closure", "Plant Closure", "Layoff",
codes like "CL"/"WR"/"lo"), a few normalize it, and many leave it null. To make
``closure_type`` filterable we batch every value into one of two canonical
buckets — ``"Closure"`` or ``"Layoff"`` — or ``None`` when the value is blank,
unrecognized, or ambiguously names both.

This is the single source of truth, imported by the storage upsert, the GA
enricher, and the backfill migration.
"""
from __future__ import annotations

import re

CLOSURE = "Closure"
LAYOFF = "Layoff"

# Whole-word codes used by a few sources (e.g. IN "lo"/"cl", WI "CL"/"WR").
_CLOSURE_CODE_RE = re.compile(r"\bcl\b")
_LAYOFF_CODE_RE = re.compile(r"\b(?:lo|wr)\b")


def normalize_closure_category(raw: str | None) -> str | None:
    """Bucket a raw closure-type string into ``"Closure"``, ``"Layoff"``, or None.

    Returns ``None`` for blank/unrecognized input and for values that name both
    a closure and a layoff (e.g. "Layoff and Closure"), which can't be cleanly
    assigned to a single bucket.
    """
    if not raw:
        return None
    s = raw.strip().lower()
    if not s:
        return None

    # "clos" covers closure / closing / permanent closures.
    has_clos = "clos" in s or bool(_CLOSURE_CODE_RE.search(s))
    has_layoff = (
        "layoff" in s
        or "lay off" in s
        or "reduction" in s
        or "rif" in s
        or bool(_LAYOFF_CODE_RE.search(s))
    )

    if has_clos and not has_layoff:
        return CLOSURE
    if has_layoff and not has_clos:
        return LAYOFF
    return None
