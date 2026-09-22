"""Consolidate duplicate Company rows non-destructively.

Strategy (per the consolidation plan):
  Pass 1 — DUNS merge: rows sharing a non-null ``duns`` are the same legal entity.
  Pass 2 — name fallback: among rows not already merged, group by
           ``name_normalized``; merge a group when it spans <=1 distinct DUNS
           (same name + two DUNS = different companies -> skip, don't over-merge)
           OR when its members share one website domain (same name + same site =
           one company whose enrichment split across several DUNS, e.g. Boeing).
  Then — admin overrides (``CompanyMergeOverride``, set from the admin UI) are
           applied on top and win over both passes; see warn_v2/companies/merge.py.
Each group keeps one canonical survivor (prefer enriched, higher confidence, a
digit-free name, more notices, lower id); the rest get ``canonical_company_id``
pointed at it. We NEVER touch ``Notice.company_id`` or delete rows, so the merge
is fully reversible.

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

from warn_v2.companies.merge import apply_overrides, flatten
from warn_v2.companies.normalize import canonical_name, website_domain
from warn_v2.db.models import Company, CompanyMergeOverride, Notice
from warn_v2.db.session import session_scope

log = logging.getLogger(__name__)

_GUARDRAIL = 0.50  # abort if >50% of companies would be merged away


def _same_website(members: list[Company]) -> bool:
    """True when every member that has a website resolves to one shared domain
    (and at least one member has a website).

    Lets a same-name group that spans multiple DUNS still merge when their sites
    agree — e.g. Boeing's several D&B records (``Boeing`` / ``Boeing Company`` /
    ``The Boeing Company``), all at boeing.com: imperfect enrichment matched one
    company to several DUNS, not genuinely different companies. Members with no
    website are ignored (they ride along on the shared name), so one
    un-enriched sibling doesn't block the merge.
    """
    domains = {website_domain(m.website) for m in members}
    domains.discard("")
    return len(domains) == 1


def _survivor_key(c: Company, notice_counts: dict[int, int]) -> tuple:
    """Higher tuple wins (via max): enriched, then confidence, then a digit-free
    name, then more notices, then lower id.

    The survivor's raw name is the label the group shows everywhere (e.g. Top
    Employers), so a clean ``Kmart Corporation`` must beat a store-numbered
    ``KMART CORPORATION # 7435`` even when the store row has more notices. The
    check is relative within a group: names that always carry digits (3M,
    7-Eleven) tie on it and fall through to notice count."""
    conf = float(c.enrichment_confidence) if c.enrichment_confidence is not None else 0.0
    clean_name = not any(ch.isdigit() for ch in c.name)
    return (c.enriched_at is not None, conf, clean_name, notice_counts.get(c.id, 0), -c.id)


def _parent_group_key(c: Company) -> str:
    # Prefer exact identifiers (provider id of the global ultimate, then DUNS) over the
    # fuzzy name; fall back to self when the company has no parent linkage.
    if c.global_ultimate_id:
        return "ult:" + c.global_ultimate_id
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
    stats: dict = {
        "total": 0, "merged": 0, "duns_groups": 0,
        "name_groups": 0, "website_groups": 0,
    }

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
            multi_duns = len({m.duns for m in members if m.duns}) >= 2
            # A same-name group with >=2 distinct DUNS is normally different
            # entities — unless the members share one website domain, which marks
            # them as one company enrichment split across several DUNS records.
            if multi_duns:
                if not _same_website(members):
                    continue
                stats["website_groups"] += 1
            stats["name_groups"] += 1
            surv = pick(members)
            for m in members:
                if m.id != surv.id:
                    merged_into[m.id] = surv.id

        # The guardrail judges only the heuristic merges: a large deliberate
        # admin merge must not trip it.
        auto_merged = len(merged_into)
        ratio = auto_merged / stats["total"] if stats["total"] else 0.0
        if ratio > _GUARDRAIL and not force:
            log.warning(
                "consolidate: %d/%d (%.0f%%) would be merged — exceeds %d%% "
                "guardrail. Re-run with --force if this is expected.",
                auto_merged, stats["total"], ratio * 100, int(_GUARDRAIL * 100),
            )
            session.rollback()
            stats["merged"] = 0
            stats["aborted"] = True
            return stats

        # Admin overrides (newest first) win over the heuristics, then flatten:
        # a hub that absorbed children in Pass 1 (child -> hub) can itself be
        # merged in Pass 2 or by an override (hub -> survivor), and
        # canonical_company_id is followed only one level by the rollups.
        overrides = session.execute(
            select(CompanyMergeOverride.company_id, CompanyMergeOverride.target_company_id)
            .order_by(CompanyMergeOverride.decided_at.desc())
        ).all()
        stats["overrides"] = len(overrides)
        merged_into = flatten(apply_overrides(merged_into, overrides))

        stats["merged"] = len(merged_into)

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
                "name_groups=%d website_groups=%d) — nothing written",
                stats["merged"], stats["total"], stats["duns_groups"],
                stats["name_groups"], stats["website_groups"],
            )
        else:
            session.commit()
            log.info(
                "consolidate: merged %d of %d (duns_groups=%d name_groups=%d "
                "website_groups=%d)",
                stats["merged"], stats["total"], stats["duns_groups"],
                stats["name_groups"], stats["website_groups"],
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
        f"name_groups={stats['name_groups']} website_groups={stats['website_groups']} "
        f"total={stats['total']}{suffix}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
