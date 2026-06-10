"""Consolidate duplicate Company rows non-destructively.

Strategy (per the consolidation plan):
  Pass 1 — DUNS merge: rows sharing a non-null ``duns`` are the same legal entity.
  Pass 2 — name fallback: among rows not already merged, group by
           ``name_normalized``; merge a group only if it spans <=1 distinct DUNS
           (same name + two DUNS = different companies -> skip, don't over-merge).
Each group keeps one canonical survivor (prefer enriched, higher confidence, more
notices, lower id); the rest get ``canonical_company_id`` pointed at it. We NEVER
touch ``Notice.company_id`` or delete rows, so the merge is fully reversible.

Surviving canonical rows also get a ``parent_group_key`` for sibling-under-parent
rollup, preferring the global-ultimate / parent DUNS over the name.

Guardrail: abort if >50 % of companies would be merged (unless --force).
Dry-run is the default.

Usage::

    warn-v2 consolidate-companies --dry-run   # preview (default)
    warn-v2 consolidate-companies             # commit
    warn-v2 consolidate-companies --force     # bypass the 50% guardrail
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict

from sqlalchemy import func, select

from warn_v2.companies.normalize import canonical_name
from warn_v2.db.models import Company, Notice
from warn_v2.db.session import session_scope

log = logging.getLogger(__name__)

_GUARDRAIL = 0.50  # abort if >50% of companies would be merged away


def _survivor_key(c: Company, notice_counts: dict[int, int]) -> tuple:
    """Higher tuple wins (via max): enriched, then confidence, then more notices,
    then lower id."""
    conf = float(c.enrichment_confidence) if c.enrichment_confidence is not None else 0.0
    return (c.enriched_at is not None, conf, notice_counts.get(c.id, 0), -c.id)


def _parent_group_key(c: Company) -> str:
    if c.global_ultimate_duns:
        return "duns:" + c.global_ultimate_duns
    if c.parent_duns:
        return "duns:" + c.parent_duns
    nm = canonical_name(c.global_ultimate_name or c.parent_company_name or "")
    if nm:
        return "name:" + nm
    return "self:" + (c.name_normalized or canonical_name(c.name))


def consolidate_companies(*, dry_run: bool = True, force: bool = False) -> dict:
    """Merge duplicate companies. Returns summary stats."""
    stats: dict = {"total": 0, "merged": 0, "duns_groups": 0, "name_groups": 0}

    with session_scope() as session:
        companies = list(session.scalars(select(Company)))
        stats["total"] = len(companies)
        if not companies:
            log.info("consolidate: no companies — nothing to do")
            return stats

        notice_counts = {
            cid: n
            for cid, n in session.execute(
                select(Notice.company_id, func.count(Notice.notice_id))
                .where(Notice.company_id.is_not(None))
                .group_by(Notice.company_id)
            )
        }

        for c in companies:
            nn = canonical_name(c.name)
            if c.name_normalized != nn:
                c.name_normalized = nn

        merged_into: dict[int, int] = {}

        def pick(members: list[Company]) -> Company:
            return max(members, key=lambda c: _survivor_key(c, notice_counts))

        # Pass 1 — DUNS.
        by_duns: dict[str, list[Company]] = defaultdict(list)
        for c in companies:
            if c.duns:
                by_duns[c.duns].append(c)
        for members in by_duns.values():
            if len(members) < 2:
                continue
            stats["duns_groups"] += 1
            surv = pick(members)
            for m in members:
                if m.id != surv.id:
                    merged_into[m.id] = surv.id

        # Pass 2 — name fallback (skip rows already merged; skip name groups that
        # span multiple distinct DUNS = same name, different entities).
        by_name: dict[str, list[Company]] = defaultdict(list)
        for c in companies:
            if c.id in merged_into or not c.name_normalized:
                continue
            by_name[c.name_normalized].append(c)
        for members in by_name.values():
            if len(members) < 2:
                continue
            if len({m.duns for m in members if m.duns}) >= 2:
                continue
            stats["name_groups"] += 1
            surv = pick(members)
            for m in members:
                if m.id != surv.id:
                    merged_into[m.id] = surv.id

        stats["merged"] = len(merged_into)

        ratio = len(merged_into) / stats["total"] if stats["total"] else 0.0
        if ratio > _GUARDRAIL and not force:
            log.warning(
                "consolidate: %d/%d (%.0f%%) would be merged — exceeds %d%% "
                "guardrail. Re-run with --force if this is expected.",
                len(merged_into), stats["total"], ratio * 100, int(_GUARDRAIL * 100),
            )
            session.rollback()
            stats["merged"] = 0
            stats["aborted"] = True
            return stats

        # Apply: dupes -> canonical pointer; canonical rows -> NULL + group key.
        for c in companies:
            if c.id in merged_into:
                c.canonical_company_id = merged_into[c.id]
            else:
                c.canonical_company_id = None  # keep canonical rows NULL (idempotent)
                c.parent_group_key = _parent_group_key(c)

        if dry_run:
            session.rollback()
            log.info(
                "consolidate DRY RUN: would merge %d of %d (duns_groups=%d "
                "name_groups=%d) — nothing written",
                stats["merged"], stats["total"], stats["duns_groups"], stats["name_groups"],
            )
        else:
            session.commit()
            log.info(
                "consolidate: merged %d of %d (duns_groups=%d name_groups=%d)",
                stats["merged"], stats["total"], stats["duns_groups"], stats["name_groups"],
            )

    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=False)
    parser.add_argument("--force", action="store_true", help="Bypass the 50%% guardrail")
    args = parser.parse_args()
    stats = consolidate_companies(dry_run=args.dry_run, force=args.force)
    suffix = " (dry run)" if args.dry_run else ""
    print(
        f"merged={stats['merged']} duns_groups={stats['duns_groups']} "
        f"name_groups={stats['name_groups']} total={stats['total']}{suffix}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
