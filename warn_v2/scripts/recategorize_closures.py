"""Re-derive closure_category for uncategorized notices from their stored type.

One-shot repair. ``closure_category`` is first-non-null-wins, so a normalizer
improvement only reaches rows a scraper re-reads. This re-runs
``normalize_closure_category`` over every notice whose category is NULL but
whose raw ``closure_type`` is set. It also maps MD's numeric type codes: rows
ingested before md.py learned them still hold a bare "1" or "2".

Only NULL categories are written, so Non-WARN rows and existing categories are
never touched. ``closure_type`` itself is left as the source wrote it.

Usage::

    warn-v2 recategorize-closures --dry-run
    warn-v2 recategorize-closures
"""
from __future__ import annotations

import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.closure import normalize_closure_category
from warn_v2.db.models import Notice
from warn_v2.scrapers.states.md import _MD_TYPE_CODES

log = logging.getLogger(__name__)

_LEGACY_CODES: dict[str, dict[str, str]] = {"MD": _MD_TYPE_CODES}


def recategorize_closures(session: Session) -> Counter[str]:
    """Fill NULL categories in ``session``; the caller commits.

    Returns the number of notices categorized, per state.
    """
    filled: Counter[str] = Counter()
    notices = session.scalars(
        select(Notice).where(
            Notice.closure_category.is_(None), Notice.closure_type.is_not(None)
        )
    ).all()
    for notice in notices:
        raw = notice.closure_type.strip()
        raw = _LEGACY_CODES.get(notice.state, {}).get(raw, raw)
        category = normalize_closure_category(raw)
        if category is not None:
            notice.closure_category = category
            filled[notice.state] += 1
    session.flush()
    log.info("recategorize-closures: %s", dict(sorted(filled.items())))
    return filled
