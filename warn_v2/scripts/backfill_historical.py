"""Ingest historical WARN data for states where the regular scraper only fetches
the current year.

Each supported state has a ``BackfillSpec`` in ``_BACKFILL`` describing one of
two fetch shapes:

* **year loop** (``fetch_year``) — fetch one year at a time from ``year_start``
  to the current year. ``fetch_year(scraper, year)`` returns raw bytes, a list
  of raw chunks (paginated sources), or ``None`` when the year has no data.
* **archive-file list** (``discover_urls``) — discover historical file URLs
  from an archive page and ingest each one (CA). ``parse_for_url`` may return
  an alternate parser for a given URL (e.g. PDF-era files).

Per-state fetch/parse helpers live next to the regular scraper in
``warn_v2/scrapers/states/<st>.py`` (see ``ca._discover_archive_urls``,
``dc._fetch_dc_year``); this module holds only the registry and the loops.

Dry runs log a duplicate preview: rows already in the DB, rows that would
insert, and *near misses* — rows matching an existing notice on
(state, employer, notice_date) but hashing to a different ``notice_id``
(usually city/ZIP drift between a historical format and the live one). Near
misses become duplicates on a real run; review them and plan a
``mark-superseded --state XX`` pass before committing.

Usage::

    warn-v2 backfill-historical --state CA
    warn-v2 backfill-historical --state DC --year-start 2013
    warn-v2 backfill-historical --state VT --dry-run
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import httpx
from sqlalchemy import select

from warn_v2.db.models import Notice, ScraperRun
from warn_v2.db.session import session_scope
from warn_v2.pipeline.dedup import _norm, notice_id
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import NoticeRow, ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import get_scraper
from warn_v2.scrapers.states.ca import _discover_archive_urls, parse_ca_pdf
from warn_v2.scrapers.states.co import _fetch_co_year, _parse_co_year
from warn_v2.scrapers.states.dc import _fetch_dc_year
from warn_v2.scrapers.states.fl import _fetch_fl_year
from warn_v2.scrapers.states.hi import _fetch_hi_year
from warn_v2.scrapers.states.il import _discover_archive_xlsx_urls as _discover_il_xlsx_urls
from warn_v2.scrapers.states.ky import _discover_workbook_urls as _discover_ky_workbook_urls
from warn_v2.scrapers.states.ky import parse_ky_workbook
from warn_v2.scrapers.states.la import _fetch_la_year, parse_la_pdf
from warn_v2.scrapers.states.la import _source_url as _la_source_url
from warn_v2.scrapers.states.md import _fetch_md_year
from warn_v2.scrapers.states.mn import (
    _discover_archive_pdf_urls as _discover_mn_pdf_urls,
)
from warn_v2.scrapers.states.mn import (
    _parse_archive_pdf as _parse_mn_archive_pdf,
)
from warn_v2.scrapers.states.ms import _discover_pdf_urls as _discover_ms_pdf_urls
from warn_v2.scrapers.states.nm import _discover_archive_pdf_urls as _discover_nm_pdf_urls
from warn_v2.scrapers.states.nv import _fetch_nv_year, parse_nv_archive
from warn_v2.scrapers.states.oh import _fetch_oh_year, parse_oh_year
from warn_v2.scrapers.states.pa import _fetch_pa_year, parse_pa_month
from warn_v2.scrapers.states.tx import _fetch_tx_year
from warn_v2.scrapers.states.wi import _fetch_wi_archive_year, parse_wi_archive_html

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillSpec:
    """How to backfill one state. Set either ``fetch_year`` or ``discover_urls``."""

    # Mode 1 — year loop:
    year_start: int | None = None
    fetch_year: Callable[..., bytes | list[bytes] | None] | None = None
    # Optional parser that needs the year for context (e.g. month-only sources).
    parse_year: Callable[[bytes, int], list[NoticeRow]] | None = None

    # Mode 2 — archive-file list:
    discover_urls: Callable[[], list[str]] | None = None
    parse_for_url: Callable[[str], Callable | None] | None = None


def _joblink_fetch(scraper, year: int) -> bytes:
    """JobLink platform: the base class supports fetch(year=Y) directly."""
    return scraper.fetch(year=year)


# Lambdas resolve module globals at call time so tests can patch
# `backfill_historical._fetch_dc_year` / `._discover_archive_urls` /
# `.parse_ca_pdf` exactly as before the registry rewrite.
_BACKFILL: dict[str, BackfillSpec] = {
    "CA": BackfillSpec(
        discover_urls=lambda: _discover_archive_urls(),
        parse_for_url=lambda u: parse_ca_pdf if u.lower().endswith(".pdf") else None,
    ),
    "DC": BackfillSpec(year_start=2013, fetch_year=lambda s, y: _fetch_dc_year(y)),
    # CO: one Google Sheet per year, 2015+; the regular scraper reads only the
    # two newest. _parse_co_year skips the scraper's staleness guard.
    "CO": BackfillSpec(
        year_start=2015,
        fetch_year=lambda s, y: _fetch_co_year(y),
        parse_year=lambda b, y: _parse_co_year(b, y),
    ),
    "AZ": BackfillSpec(year_start=2016, fetch_year=_joblink_fetch),
    "DE": BackfillSpec(year_start=2016, fetch_year=_joblink_fetch),
    # JobLink platforms verified searchable to these years (2026-06-12 probes,
    # see docs/historical-sources.md).
    "KS": BackfillSpec(year_start=1999, fetch_year=_joblink_fetch),
    "ME": BackfillSpec(year_start=2012, fetch_year=_joblink_fetch),
    "VT": BackfillSpec(year_start=2003, fetch_year=_joblink_fetch),
    # Year-URL sources, earliest years verified by 2026-06-12 probes.
    "TX": BackfillSpec(year_start=2020, fetch_year=_fetch_tx_year),
    "FL": BackfillSpec(year_start=2020, fetch_year=_fetch_fl_year),
    "HI": BackfillSpec(year_start=2019, fetch_year=lambda s, y: _fetch_hi_year(y)),
    # KY: one recent .xlsx workbook holds every year back to 2017 as its own
    # sheet (the per-year CSVs only exist for 2025+ — see parse_ky_workbook).
    "KY": BackfillSpec(
        discover_urls=lambda: _discover_ky_workbook_urls(),
        parse_for_url=lambda u: parse_ky_workbook,
    ),
    # LA: per-year PDFs; laworks.net prunes old files, only 2025+ resolve
    # (fetch returns None for pruned years). Pre-2025 → records request.
    "LA": BackfillSpec(
        year_start=2025,
        fetch_year=lambda s, y: _fetch_la_year(y),
        parse_year=lambda b, y: parse_la_pdf(b, _la_source_url(y)),
    ),
    # NV: per-year archive PDFs 2017+ in three layout eras; 2021 is a scanned
    # image (skipped) and 2025 coverage ends June 3 — see nv._ARCHIVE_SOURCES.
    "NV": BackfillSpec(
        year_start=2017,
        fetch_year=lambda s, y: _fetch_nv_year(y),
        parse_year=lambda b, y: parse_nv_archive(b, y),
    ),
    # NM: yearly PDFs back to 2016 with irregular filenames — discover from hub.
    "NM": BackfillSpec(discover_urls=lambda: _discover_nm_pdf_urls()),
    # MD: archived per-year pages warn{year}.shtml verified back to 2010; old
    # pages use 'WIA Code'/'Type Code' headers, which MDScraper.parse aliases.
    "MD": BackfillSpec(year_start=2010, fetch_year=lambda s, y: _fetch_md_year(y)),
    # WI: static per-year pages exist only 2016-2019; the cumulative Google
    # Sheet covers 2020+ via the regular scraper.
    "WI": BackfillSpec(
        year_start=2016,
        fetch_year=lambda s, y: _fetch_wi_archive_year(y),
        parse_year=lambda b, y: parse_wi_archive_html(b, y),
    ),
    # MN: DEED PDFs discovered via Wayback CDX (annual 2018-2021, monthly
    # 2022+). MNScraper.parse expects a JSON envelope — route raw PDF bytes
    # to the archive parser instead.
    "MN": BackfillSpec(
        discover_urls=lambda: _discover_mn_pdf_urls(),
        parse_for_url=lambda u: (lambda raw, _u=u: _parse_mn_archive_pdf(raw, _u)),
    ),
    # MS: the landing page lists every quarterly PDF back to PY2020; the
    # regular scraper ingests only the most recent one.
    "MS": BackfillSpec(discover_urls=lambda: _discover_ms_pdf_urls()),
    # IL: monthly Excel files 2020+ from the archive page (the 1999-2019 PDF
    # era needs a dedicated parser — deferred).
    "IL": BackfillSpec(discover_urls=lambda: _discover_il_xlsx_urls()),
    # OH: four era formats back to 1996, mostly via Wayback replay (see
    # docs/historical-sources.md); 2025 has no known source anywhere.
    "OH": BackfillSpec(
        year_start=1996,
        fetch_year=lambda s, y: _fetch_oh_year(y),
        parse_year=lambda b, y: parse_oh_year(b, y),
    ),
    # PA: archived per-month pages via Wayback CDX (portal.state.pa.us
    # 2001-2015, SharePoint dli.pa.gov 2011-2022; same content template).
    # _fetch_pa_year hard-caps at 2022 — the AEM live era (2023+) stamps
    # notice_date from its publish date, so re-parsing those months would
    # mint duplicates of rows the regular scraper already stores.
    "PA": BackfillSpec(
        year_start=2001,
        fetch_year=lambda s, y: _fetch_pa_year(y),
        parse_year=lambda b, y: parse_pa_month(b, y),
    ),
}

_SUPPORTED = frozenset(_BACKFILL)


def backfill_historical(
    state: str,
    *,
    year_start: int | None = None,
    year_end: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Fetch and ingest all available historical WARN data for ``state``.

    Returns ``{"years_attempted": N, "years_ok": N, "rows_seen": N, "rows_new": N}``.
    """
    state = state.upper()
    spec = _BACKFILL.get(state)
    if spec is None:
        raise ValueError(
            f"backfill-historical does not support {state!r}. "
            f"Supported: {', '.join(sorted(_SUPPORTED))}"
        )

    stats: dict[str, int] = {
        "years_attempted": 0,
        "years_ok": 0,
        "rows_seen": 0,
        "rows_new": 0,
    }

    scraper = get_scraper(state)

    if spec.discover_urls is not None:
        _backfill_url_list(scraper, spec, stats, dry_run=dry_run)
    else:
        start = year_start or spec.year_start or datetime.now().year
        end = year_end or datetime.now().year
        _backfill_year_loop(scraper, state, spec, start, end, stats, dry_run=dry_run)

    log.info(
        "%s backfill done: years_attempted=%d years_ok=%d rows_seen=%d rows_new=%d",
        state,
        stats["years_attempted"],
        stats["years_ok"],
        stats["rows_seen"],
        stats["rows_new"],
    )
    return stats


# ---------------------------------------------------------------------------
# Mode 2 — archive-file list (CA)
# ---------------------------------------------------------------------------

# Some archives (KY SharePoint) 403 httpx's default User-Agent for file
# downloads even though the discovery API accepts it — send a browser UA.
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
}


def _backfill_url_list(
    scraper, spec: BackfillSpec, stats: dict[str, int], *, dry_run: bool
) -> None:
    log.info("%s: discovering historical file URLs", scraper.state)
    try:
        urls = spec.discover_urls()
    except ScrapeFailed as e:
        log.error("%s: could not discover archive URLs: %s", scraper.state, e)
        return

    if not urls:
        log.warning("%s: no historical file links found", scraper.state)
        return

    log.info("%s: found %d historical file(s)", scraper.state, len(urls))

    for url in urls:
        stats["years_attempted"] += 1
        log.info("%s: fetching %s", scraper.state, url)
        if "web.archive.org" in url:
            # Wayback throttles request bursts; pace replay downloads.
            time.sleep(3)
        try:
            r = httpx.get(url, headers=_FETCH_HEADERS, timeout=120, follow_redirects=True)
            r.raise_for_status()
            raw = r.content
        except httpx.HTTPError as e:
            log.warning("%s: fetch failed for %s: %s", scraper.state, url, e)
            _record_run(
                scraper.state, label=url, status="fetch_failed", error=str(e), dry_run=dry_run
            )
            continue

        parse_fn = spec.parse_for_url(url) if spec.parse_for_url else None
        _ingest_raw(scraper, raw, label=url, stats=stats, dry_run=dry_run, parse_fn=parse_fn)


# ---------------------------------------------------------------------------
# Mode 1 — year loop
# ---------------------------------------------------------------------------

def _backfill_year_loop(
    scraper,
    state: str,
    spec: BackfillSpec,
    start: int,
    end: int,
    stats: dict[str, int],
    *,
    dry_run: bool,
) -> None:
    log.info("%s: backfilling years %d-%d", state, start, end)

    for year in range(start, end + 1):
        stats["years_attempted"] += 1
        log.info("%s: fetching year %d", state, year)

        try:
            raw = spec.fetch_year(scraper, year)
        except ScrapeFailed as e:
            log.warning("%s %d: fetch failed: %s", state, year, e)
            _record_run(
                state, label=str(year), status="fetch_failed", error=str(e), dry_run=dry_run
            )
            continue

        if raw is None:
            log.info("%s %d: no data (page missing or empty)", state, year)
            continue

        # Paginated sources return one chunk per page; each counts as an attempt.
        chunks = raw if isinstance(raw, list) else [raw]
        parse_fn = None
        if spec.parse_year is not None:
            parse_fn = lambda b, _y=year: spec.parse_year(b, _y)  # noqa: E731
        for i, chunk in enumerate(chunks):
            if i > 0:
                stats["years_attempted"] += 1
            label = str(year) if len(chunks) == 1 else f"{year} p{i + 1}"
            _ingest_raw(
                scraper, chunk, label=label, stats=stats, dry_run=dry_run, parse_fn=parse_fn
            )


# ---------------------------------------------------------------------------
# Shared ingest helpers (also used by `warn-v2 ingest-file`)
# ---------------------------------------------------------------------------

def _ingest_raw(
    scraper,
    raw: bytes,
    *,
    label: str,
    stats: dict[str, int],
    dry_run: bool,
    parse_fn=None,
) -> None:
    _parse = parse_fn if parse_fn is not None else scraper.parse
    try:
        rows = _parse(raw)
    except ParseFailed as e:
        log.warning("%s %s: parse failed: %s", scraper.state, label, e)
        _record_run(
            scraper.state, label=label, status="parse_failed", error=str(e), dry_run=dry_run
        )
        return

    if not rows:
        log.info("%s %s: parsed 0 rows — skipping", scraper.state, label)
        return

    if dry_run:
        log.info(
            "%s %s: dry run — would upsert %d rows",
            scraper.state, label, len(rows),
        )
        _report_near_misses(scraper.state, label, rows)
        stats["years_ok"] += 1
        stats["rows_seen"] += len(rows)
        return

    with session_scope() as session:
        seen, new = upsert_notices(session, rows)
        session.commit()

    log.info("%s %s: seen=%d new=%d", scraper.state, label, seen, new)
    stats["years_ok"] += 1
    stats["rows_seen"] += seen
    stats["rows_new"] += new
    _record_run(
        scraper.state, label=label, status="ok",
        rows_scraped=seen, rows_new=new, dry_run=dry_run,
    )


def _report_near_misses(state: str, label: str, rows: list[NoticeRow]) -> None:
    """Dry-run duplicate preview. Best-effort: skipped when no DB is reachable.

    A *near miss* is a parsed row whose ``notice_id`` is new but whose
    (state, normalized employer, notice_date) matches an existing notice —
    i.e. it would insert as a duplicate differing only in city/ZIP.
    """
    try:
        with session_scope() as session:
            ids = {notice_id(r) for r in rows}
            existing_ids = set(
                session.execute(
                    select(Notice.notice_id).where(Notice.notice_id.in_(ids))
                ).scalars()
            )
            dates = {r.notice_date for r in rows if r.notice_date is not None}
            candidates = session.execute(
                select(Notice.notice_id, Notice.employer, Notice.notice_date).where(
                    Notice.state == state.upper(),
                    Notice.notice_date.in_(dates),
                )
            ).all()
    except Exception as e:
        log.warning("%s %s: near-miss check skipped (no DB reachable): %s", state, label, e)
        return

    by_key: dict[tuple[str, object], list[str]] = {}
    for nid, emp, nd in candidates:
        by_key.setdefault((_norm(emp), nd), []).append(nid)

    already = 0
    near: list[NoticeRow] = []
    for r in rows:
        nid = notice_id(r)
        if nid in existing_ids:
            already += 1
            continue
        if any(m != nid for m in by_key.get((_norm(r.employer), r.notice_date), [])):
            near.append(r)

    log.info(
        "%s %s: would_insert=%d (near_miss=%d) already_exists=%d",
        state, label, len(rows) - already, len(near), already,
    )
    for r in near[:10]:
        log.info(
            "%s %s: near miss: %r %s (city=%r zip=%r) collides with an existing "
            "notice keyed differently — would duplicate",
            state, label, r.employer, r.notice_date, r.city, r.zip,
        )
    if len(near) > 10:
        log.info("%s %s: ... and %d more near misses", state, label, len(near) - 10)


def _record_run(
    state: str,
    *,
    label: str,
    status: str,
    error: str | None = None,
    rows_scraped: int | None = None,
    rows_new: int | None = None,
    dry_run: bool,
) -> None:
    """Persist one per-chunk ScraperRun, status-prefixed ``backfill_``.

    The prefix keeps these rows out of everything that reasons about the
    *live* scraper's health from a state's newest run — the audit's
    row-drift/broken flags, /api/runs/status last-success, the staleness
    metric, and cadence inference all treat a whole-source scrape's row
    count as the signal, which a one-month/one-year chunk would fake out.
    """
    if dry_run:
        return
    now = datetime.now().astimezone()
    with session_scope() as session:
        run = ScraperRun(
            state=state,
            started_at=now,
            finished_at=now,
            status=f"backfill_{status}",
            error=error,
            rows_scraped=rows_scraped,
            rows_new=rows_new,
        )
        session.add(run)
        session.commit()
