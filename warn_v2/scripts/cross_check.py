"""Cross-check stored notices against the live state WARN pages.

Re-fetches what each state currently publishes and diffs it against what we've
stored, in a single read-only pass per state. Unlike the scrape pipeline this
never writes notices — its product is a drift report:

  * ``missing_from_db`` — notices on the live page whose content-hash
    ``notice_id`` is not in our DB. A real gap: a scrape that dropped rows, a
    parser that drifted, or a failed prior run. No date windowing — a
    fresh-parse id we don't store is missing, full stop.
  * ``extra_in_db`` — notices we hold whose ``notice_id`` is absent from the
    live page, *restricted to the date window the page currently covers*. A
    page only shows a rolling window, so an old historical row we keep is not
    drift; only a gap inside the live window is (withdrawn/amended/re-keyed, or
    a stale duplicate).

A notice whose hashed fields drift on the page (e.g. an employer string going
``Acme Inc`` -> ``Acme, Inc.``) gets a new ``notice_id`` and so shows up as
*both* ``missing_from_db`` (the new id) and ``extra_in_db`` (the old, stored
id). That pairing is the intended re-key signal, not a double-count.

The same content hash (``pipeline.dedup.notice_id``) keys both sides, and the
same impossible-date filter the storage path applies
(``pipeline.validate.filter_bad_dates``) is applied to the live rows, so the
comparison is apples to apples. This is the read-only sibling of
``pipeline.runner.run_state``: it does the scraper's ``fetch()`` → ``parse()``
but stops before storage.

Why state pages and not USA Today / other aggregators: those are peer scrapers
of the same upstream sources, with their own coverage and errors. The only
ground truth for "did we miss a notice" is the state's own page.

Usage::

    warn-v2 cross-check                 # all non-blocked states (network)
    warn-v2 cross-check --state DC      # one state
    warn-v2 cross-check --json          # machine-readable
    warn-v2 cross-check --no-store      # read-only preview, no DB write
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import CrossCheckRun, Notice
from warn_v2.db.session import session_scope
from warn_v2.pipeline.dedup import notice_id
from warn_v2.pipeline.validate import filter_bad_dates
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed, StateScraper
from warn_v2.scrapers.registry import all_states, get_scraper

# Jurisdictions known to be blocked at scraper-build time — no live source to
# verify against. Kept in sync with scripts.audit.BLOCKED.
from warn_v2.scripts.audit import BLOCKED

log = logging.getLogger(__name__)

# How many sample rows of each kind to persist on a CrossCheckRun (the table is
# for triage, not a full mirror — the counts are the signal).
_SAMPLE_LIMIT = 25

# (notice_id, employer, notice_date) for a single drift row.
_Row = tuple[str, str, date | None]


@dataclass
class CrossCheck:
    """Drift report for one jurisdiction."""

    state: str
    status: str = "ok"  # ok | fetch_failed | parse_failed | empty | degraded | blocked
    error: str | None = None
    live_rows: int = 0
    db_active: int = 0
    window_start: date | None = None
    window_end: date | None = None
    missing_from_db: list[_Row] = field(default_factory=list)
    extra_in_db: list[_Row] = field(default_factory=list)

    @property
    def missing_count(self) -> int:
        return len(self.missing_from_db)

    @property
    def extra_count(self) -> int:
        return len(self.extra_in_db)

    def to_dict(self) -> dict:
        def rows(rs: list[_Row]) -> list[dict]:
            return [
                {"notice_id": nid, "employer": emp, "notice_date": d}
                for nid, emp, d in rs
            ]

        return {
            "state": self.state,
            "status": self.status,
            "error": self.error,
            "live_rows": self.live_rows,
            "db_active": self.db_active,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "missing_count": self.missing_count,
            "extra_count": self.extra_count,
            "missing_from_db": rows(self.missing_from_db),
            "extra_in_db": rows(self.extra_in_db),
        }


def cross_check_state(
    scraper: StateScraper, session: Session
) -> CrossCheck:
    """Fetch a state's live page and diff it against stored notices (read-only)."""
    cc = CrossCheck(state=scraper.state.upper())

    # fetch → parse, mirroring runner.run_state's error handling but without
    # snapshotting or persisting. A source we can't retrieve/parse can't be used
    # to verify, so we record the failure and skip the diff.
    try:
        raw = scraper.fetch()
    except ScrapeFailed as e:
        cc.status, cc.error = "fetch_failed", str(e)
        return cc
    except Exception as e:  # defensive: unexpected fetch error
        cc.status, cc.error = "fetch_failed", f"{type(e).__name__}: {e}"
        return cc

    try:
        rows = scraper.parse(raw)
    except ParseFailed as e:
        cc.status, cc.error = "parse_failed", str(e)
        return cc
    except Exception as e:
        cc.status, cc.error = "parse_failed", f"{type(e).__name__}: {e}"
        return cc

    # Drop impossible-date rows exactly as the storage path does, so live and
    # stored sets are comparable (a typo'd date the scraper would never have
    # stored must not count as missing).
    filter_bad_dates(rows)
    if not rows:
        cc.status = "empty"
        return cc

    live: dict[str, NoticeRow] = {notice_id(r): r for r in rows}
    cc.live_rows = len(live)

    # Mirror the pipeline's row-count gate (pipeline.validate): a live fetch
    # outside the scraper's expected range is itself untrustworthy — a degraded
    # or truncated page, or a parser regression. Its diff would mislead (a
    # half-empty page makes us look complete), so record the fetch size and skip
    # the comparison rather than emit a false "no drift".
    low, high = scraper.expected_row_range
    if not (low <= len(rows) <= high):
        cc.status = "degraded"
        return cc

    live_dates = [r.notice_date for r in live.values() if r.notice_date]
    cc.window_start = min(live_dates) if live_dates else None
    cc.window_end = max(live_dates) if live_dates else None

    # DB side: active (non-superseded) notices for this state.
    db_rows = session.execute(
        select(Notice.notice_id, Notice.employer, Notice.notice_date).where(
            Notice.state == cc.state,
            Notice.is_superseded.is_(False),
        )
    ).all()
    db_ids = {nid for nid, _, _ in db_rows}
    cc.db_active = len(db_ids)

    # missing: on the live page, not stored. No windowing — a fresh id we lack
    # is a gap regardless of date.
    for nid, row in live.items():
        if nid not in db_ids:
            cc.missing_from_db.append((nid, row.employer, row.notice_date))

    # extra: stored but absent from the live page, only within the date window
    # the page currently covers (older history isn't expected to be on the page).
    if cc.window_start and cc.window_end:
        for nid, employer, nd in db_rows:
            if nid in live:
                continue
            if nd is not None and cc.window_start <= nd <= cc.window_end:
                cc.extra_in_db.append((nid, employer, nd))

    cc.missing_from_db.sort(key=lambda t: t[2] or date.min, reverse=True)
    cc.extra_in_db.sort(key=lambda t: t[2] or date.min, reverse=True)
    return cc


def cross_check_states(*, state_filter: str | None = None) -> list[CrossCheck]:
    """Cross-check every registered, non-blocked jurisdiction (or one).

    Performs a live network fetch per state. Each state's DB read runs in its
    own short ``session_scope`` so no single transaction is held open across the
    whole (multi-minute, network-bound) sweep; the caller persists the returned
    results in a separate short transaction.

    Blocked states have no usable source: they're skipped, unless named
    explicitly via ``state_filter`` (then reported with status ``blocked`` so the
    caller sees why nothing came back).
    """
    results: list[CrossCheck] = []
    for code in all_states():
        if state_filter and code != state_filter.upper():
            continue
        if code in BLOCKED:
            if state_filter:
                results.append(CrossCheck(state=code, status="blocked"))
            continue
        try:
            scraper = get_scraper(code)
        except Exception as e:  # missing scraper shouldn't abort the whole run
            results.append(
                CrossCheck(state=code, status="fetch_failed", error=f"no scraper: {e}")
            )
            continue
        log.info("cross-check %s", code)
        with session_scope() as session:
            results.append(cross_check_state(scraper, session))
    return results


def persist(
    session: Session, results: list[CrossCheck], *, checked_at: datetime
) -> None:
    """Record one CrossCheckRun row per result (sampled drift rows in ``sample``)."""

    def sample(rs: list[_Row]) -> list[list]:
        return [
            [nid, emp, d.isoformat() if d else None]
            for nid, emp, d in rs[:_SAMPLE_LIMIT]
        ]

    for cc in results:
        drift = cc.missing_from_db or cc.extra_in_db
        session.add(
            CrossCheckRun(
                state=cc.state,
                checked_at=checked_at,
                status=cc.status,
                live_rows=cc.live_rows,
                db_active=cc.db_active,
                missing_from_db=cc.missing_count,
                extra_in_db=cc.extra_count,
                sample=json.dumps(
                    {"missing": sample(cc.missing_from_db), "extra": sample(cc.extra_in_db)}
                )
                if drift
                else None,
            )
        )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_json(results: list[CrossCheck]) -> str:
    return json.dumps([cc.to_dict() for cc in results], indent=2, default=str)


def render_table(results: list[CrossCheck]) -> str:
    """Compact human-readable table to stdout."""
    header = (
        f"{'ST':<3} {'STATUS':<13} {'LIVE':>6} {'DB':>6} "
        f"{'MISSING':>8} {'EXTRA':>6}  WINDOW"
    )
    lines = [header, "-" * len(header)]
    for cc in results:
        window = (
            f"{cc.window_start}..{cc.window_end}" if cc.window_start else "-"
        )
        lines.append(
            f"{cc.state:<3} {cc.status:<13} {cc.live_rows:>6} {cc.db_active:>6} "
            f"{cc.missing_count:>8} {cc.extra_count:>6}  {window}"
        )
    return "\n".join(lines)
