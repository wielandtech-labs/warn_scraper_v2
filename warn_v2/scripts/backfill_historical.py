"""Ingest historical WARN data for states where the regular scraper only fetches
the current year.

Supported states
----------------
CA  — EDD publishes per-fiscal-year XLSX files on an archive page; this script
      discovers all available links and ingests each file.
DC  — Year-parameterised URL; looped from a configurable start year.
AZ  — JobLink platform; ``_build_url(host, year=Y)`` already exists.
DE  — Same JobLink platform as AZ.

CO is excluded: its Google Sheets export is append-only since 2019, so the
regular scraper already captures all historical CO data in one download.

Usage::

    warn-v2 backfill-historical --state CA
    warn-v2 backfill-historical --state DC --year-start 2013
    warn-v2 backfill-historical --state AZ --dry-run
"""
from __future__ import annotations

import logging
from datetime import datetime

import httpx

from warn_v2.db.models import ScraperRun
from warn_v2.scrapers.states.ca import _discover_archive_urls, parse_ca_pdf
from warn_v2.scrapers.states.dc import _fetch_dc_year
from warn_v2.db.session import session_scope
from warn_v2.pipeline.storage import upsert_notices
from warn_v2.scrapers.base import ParseFailed, ScrapeFailed
from warn_v2.scrapers.registry import get_scraper

log = logging.getLogger(__name__)

_SUPPORTED = frozenset({"CA", "DC", "AZ", "DE"})

# Earliest years with data on each platform.
_DEFAULT_YEAR_START = {
    "DC": 2013,
    "AZ": 2016,
    "DE": 2016,
}


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
    if state not in _SUPPORTED:
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

    if state == "CA":
        _backfill_ca(scraper, stats, dry_run=dry_run)
    elif state == "DC":
        start = year_start or _DEFAULT_YEAR_START["DC"]
        end = year_end or datetime.now().year
        _backfill_year_loop(scraper, state, start, end, stats, dry_run=dry_run)
    elif state in ("AZ", "DE"):
        start = year_start or _DEFAULT_YEAR_START[state]
        end = year_end or datetime.now().year
        _backfill_year_loop(scraper, state, start, end, stats, dry_run=dry_run)

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
# CA — archive page discovery
# ---------------------------------------------------------------------------

def _backfill_ca(scraper, stats: dict[str, int], *, dry_run: bool) -> None:
    log.info("CA: discovering historical file URLs from EDD archive page")
    try:
        urls = _discover_archive_urls()
    except ScrapeFailed as e:
        log.error("CA: could not load archive page: %s", e)
        return

    if not urls:
        log.warning("CA: no historical XLSX links found on archive page")
        return

    log.info("CA: found %d historical file(s)", len(urls))

    for url in urls:
        stats["years_attempted"] += 1
        log.info("CA: fetching %s", url)
        try:
            r = httpx.get(url, timeout=120, follow_redirects=True)
            r.raise_for_status()
            raw = r.content
        except httpx.HTTPError as e:
            log.warning("CA: fetch failed for %s: %s", url, e)
            _record_run(scraper.state, label=url, status="fetch_failed", error=str(e), dry_run=dry_run)
            continue

        parse_fn = parse_ca_pdf if url.lower().endswith(".pdf") else None
        _ingest_raw(scraper, raw, label=url, stats=stats, dry_run=dry_run, parse_fn=parse_fn)


# ---------------------------------------------------------------------------
# DC / AZ / DE — year loop
# ---------------------------------------------------------------------------

def _backfill_year_loop(
    scraper,
    state: str,
    start: int,
    end: int,
    stats: dict[str, int],
    *,
    dry_run: bool,
) -> None:
    log.info("%s: backfilling years %d–%d", state, start, end)

    for year in range(start, end + 1):
        stats["years_attempted"] += 1
        log.info("%s: fetching year %d", state, year)

        try:
            if state == "DC":
                raw = _fetch_dc_year(year)
                if raw is None:
                    log.info("%s %d: no data (page missing or empty)", state, year)
                    continue
            else:
                # AZ / DE — JobLinkScraper.fetch(year=Y)
                raw = scraper.fetch(year=year)
        except ScrapeFailed as e:
            log.warning("%s %d: fetch failed: %s", state, year, e)
            _record_run(state, label=str(year), status="fetch_failed", error=str(e), dry_run=dry_run)
            continue

        _ingest_raw(scraper, raw, label=str(year), stats=stats, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Shared ingest helper
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
        _record_run(scraper.state, label=label, status="parse_failed", error=str(e), dry_run=dry_run)
        return

    if not rows:
        log.info("%s %s: parsed 0 rows — skipping", scraper.state, label)
        return

    if dry_run:
        log.info(
            "%s %s: dry run — would upsert %d rows",
            scraper.state, label, len(rows),
        )
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
    if dry_run:
        return
    now = datetime.now().astimezone()
    with session_scope() as session:
        run = ScraperRun(
            state=state,
            started_at=now,
            finished_at=now,
            status=status,
            error=error,
            rows_scraped=rows_scraped,
            rows_new=rows_new,
        )
        session.add(run)
        session.commit()
