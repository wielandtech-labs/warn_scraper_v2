"""Mark duplicate WARN notices as superseded so they are excluded from totals.

Two patterns are detected:

  Case A — ZIP-variance duplicate:
    Same employer + notice_date + city + layoff_count, different notice_id.
    One record has a street address, the other doesn't.  The addressless one
    was scraped before the state source had the full location data; the one
    with an address is the canonical record.  Supersede the addressless one.

  Case B — Amendment:
    Same employer + notice_date + city + zip, different layoff_count.
    The earlier-scraped record is the original; the later one is the amendment.
    Supersede the earlier one.

Both patterns require a location record (location_id IS NOT NULL) on both
notices — notices without location data are skipped (they can't be reliably
matched).

Guardrail: if more than 20 % of a state's notices would be marked, the run
aborts unless --force is supplied.  This catches runaway false-positive matches.

Usage::

    warn-v2 mark-superseded --dry-run            # preview (default)
    warn-v2 mark-superseded                      # commit for all states
    warn-v2 mark-superseded --state IA           # one state only
    warn-v2 mark-superseded --state IA --force   # override guardrail
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict

from sqlalchemy import func, select, text, update

from warn_v2.db.models import Notice
from warn_v2.db.session import session_scope

log = logging.getLogger(__name__)

_GUARDRAIL = 0.20  # abort if >20 % of a state's notices would be superseded


def _find_pairs(session, state_filter: str | None) -> list[tuple[str, str, str, str]]:
    """Return ``(superseded_id, canonical_id, state, description)`` pairs.

    Notices already marked is_superseded are excluded from both sides of the
    match so re-runs are idempotent.
    """
    state_clause = "AND n1.state = :state" if state_filter else ""
    params: dict = {"state": state_filter.upper()} if state_filter else {}

    pairs: list[tuple[str, str, str, str]] = []
    seen: set[str] = set()  # prevent a notice from being superseded twice

    # Case A — ZIP-variance: same count, same city, one has address, other doesn't
    result = session.execute(
        text(f"""
            SELECT n1.notice_id, n2.notice_id, n1.state,
                   n1.employer, n1.notice_date, n1.layoff_count
            FROM notices n1
            JOIN notices n2 ON (
                n1.state = n2.state
                AND lower(trim(n1.employer)) = lower(trim(n2.employer))
                AND n1.notice_date = n2.notice_date
                AND n1.notice_id != n2.notice_id
            )
            JOIN locations l1 ON l1.id = n1.location_id
            JOIN locations l2 ON l2.id = n2.location_id
            WHERE n1.address IS NULL
              AND n2.address IS NOT NULL
              AND lower(trim(l1.city)) = lower(trim(l2.city))
              AND n1.layoff_count IS NOT DISTINCT FROM n2.layoff_count
              AND NOT n1.is_superseded
              AND NOT n2.is_superseded
              {state_clause}
            ORDER BY n1.state, n1.employer, n1.notice_date
        """),
        params,
    )
    for row in result:
        sup_id, can_id, state, emp, nd, cnt = row
        if sup_id in seen or can_id in seen:
            continue
        seen.add(sup_id)
        desc = f"{state} {emp!r} {nd} count={cnt} [zip-variance]"
        pairs.append((sup_id, can_id, state, desc))

    # Case B — Amendment: same city+zip, different count, keep the newer one
    result = session.execute(
        text(f"""
            SELECT n1.notice_id, n2.notice_id, n1.state,
                   n1.employer, n1.notice_date, n1.layoff_count, n2.layoff_count
            FROM notices n1
            JOIN notices n2 ON (
                n1.state = n2.state
                AND lower(trim(n1.employer)) = lower(trim(n2.employer))
                AND n1.notice_date = n2.notice_date
                AND n1.notice_id != n2.notice_id
                AND n1.scraped_at < n2.scraped_at
            )
            JOIN locations l1 ON l1.id = n1.location_id
            JOIN locations l2 ON l2.id = n2.location_id
            WHERE lower(trim(l1.city)) = lower(trim(l2.city))
              AND trim(coalesce(l1.zip, '')) = trim(coalesce(l2.zip, ''))
              AND n1.layoff_count IS DISTINCT FROM n2.layoff_count
              AND NOT n1.is_superseded
              AND NOT n2.is_superseded
              {state_clause}
            ORDER BY n1.state, n1.employer, n1.notice_date
        """),
        params,
    )
    for row in result:
        sup_id, can_id, state, emp, nd, cnt1, cnt2 = row
        if sup_id in seen or can_id in seen:
            continue
        seen.add(sup_id)
        desc = f"{state} {emp!r} {nd} count {cnt1}→{cnt2} [amendment]"
        pairs.append((sup_id, can_id, state, desc))

    # Case C — ZIP-variance where both notices have addresses (not caught by Case A
    # because Iowa always populates `address`).  Matches pairs with identical
    # (employer, notice_date) whose locations share the same city, and either:
    #   • point to the *same* location row (promotion merged them in-place), or
    #   • one location is ZIP-less and the other has a ZIP.
    # Same layoff_count distinguishes this from genuine amendments (Case B).
    result = session.execute(
        text(f"""
            SELECT n1.notice_id, n2.notice_id, n1.state,
                   n1.employer, n1.notice_date, n1.layoff_count
            FROM notices n1
            JOIN notices n2 ON (
                n1.state = n2.state
                AND lower(trim(n1.employer)) = lower(trim(n2.employer))
                AND n1.notice_date = n2.notice_date
                AND n1.notice_id != n2.notice_id
                AND n1.scraped_at < n2.scraped_at
            )
            LEFT JOIN locations l1 ON l1.id = n1.location_id
            LEFT JOIN locations l2 ON l2.id = n2.location_id
            WHERE (
                n1.location_id = n2.location_id
                OR (
                    lower(trim(coalesce(l1.city, ''))) = lower(trim(coalesce(l2.city, '')))
                    AND (l1.zip IS NULL OR l1.zip = '')
                    AND l2.zip IS NOT NULL AND l2.zip != ''
                )
            )
              AND n1.layoff_count IS NOT DISTINCT FROM n2.layoff_count
              AND NOT n1.is_superseded
              AND NOT n2.is_superseded
              {state_clause}
            ORDER BY n1.state, n1.employer, n1.notice_date
        """),
        params,
    )
    for row in result:
        sup_id, can_id, state, emp, nd, cnt = row
        if sup_id in seen or can_id in seen:
            continue
        seen.add(sup_id)
        desc = f"{state} {emp!r} {nd} count={cnt} [zip-variance-addressed]"
        pairs.append((sup_id, can_id, state, desc))

    return pairs


def _state_totals(session, state_filter: str | None) -> dict[str, int]:
    """Return {state: total_non_superseded_count} for the guardrail check."""
    stmt = select(Notice.state, func.count(Notice.notice_id)).where(
        Notice.is_superseded.is_(False)
    )
    if state_filter:
        stmt = stmt.where(Notice.state == state_filter.upper())
    stmt = stmt.group_by(Notice.state)
    return {row[0]: row[1] for row in session.execute(stmt)}


def mark_superseded(
    *,
    dry_run: bool = True,
    state_filter: str | None = None,
    force: bool = False,
) -> dict[str, int]:
    """Find and mark superseded notices.  Returns ``{"marked": N, "skipped": N}``."""
    stats = {"marked": 0, "skipped": 0}

    with session_scope() as session:
        pairs = _find_pairs(session, state_filter)
        if not pairs:
            log.info("No superseded pairs found — nothing to do.")
            return stats

        totals = _state_totals(session, state_filter)

        # Guardrail: check per-state ratios
        by_state: dict[str, list] = defaultdict(list)
        for pair in pairs:
            by_state[pair[2]].append(pair)

        blocked_states: list[str] = []
        for st, st_pairs in by_state.items():
            total = totals.get(st, 0)
            if total == 0:
                continue
            ratio = len(st_pairs) / total
            if ratio > _GUARDRAIL and not force:
                log.warning(
                    "%s: %d/%d (%.0f%%) would be superseded — exceeds %d%% guardrail. "
                    "Re-run with --force to override.",
                    st, len(st_pairs), total, ratio * 100, int(_GUARDRAIL * 100),
                )
                blocked_states.append(st)

        # Process allowed states
        for sup_id, _can_id, state, desc in pairs:
            if state in blocked_states:
                stats["skipped"] += 1
                log.debug("SKIP %s", desc)
                continue
            log.info("SUPERSEDE %s", desc)
            if not dry_run:
                session.execute(
                    update(Notice)
                    .where(Notice.notice_id == sup_id)
                    .values(is_superseded=True)
                )
            stats["marked"] += 1

        if dry_run:
            session.rollback()
            log.info("Dry run — no changes written.")
        else:
            session.commit()

    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Preview what would be marked without committing (default: False)",
    )
    parser.add_argument("--state", default=None, help="Limit to one state (e.g. IA)")
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass the 20%% guardrail — use when you've reviewed the output",
    )
    args = parser.parse_args()

    stats = mark_superseded(
        dry_run=args.dry_run,
        state_filter=args.state,
        force=args.force,
    )
    suffix = " (dry run)" if args.dry_run else ""
    print(f"marked={stats['marked']} skipped={stats['skipped']}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
