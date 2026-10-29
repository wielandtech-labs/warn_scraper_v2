"""Keep the /timelapse payloads warm, so no visitor pays the cold query.

The timeline caches (warn_v2.api.timeline) would otherwise make the first
visitor after each expiry wait 1.6-3 s. A daemon thread rebuilds every
unfiltered window /map's timeline offers at startup, then every
``REFRESH_S`` -- inside the TTL, so those entries are replaced before they can
expire. Filtered views (a linked-view industry tap, a state) are cached on
first request only.

Each cycle queries only the widest window and rolls the narrower ones up from
its rows, so one set of rows is cached rather than one per window. It then
hands freed heap back to the OS: the API's RSS crept to its 512 Mi limit and
was OOM-killed (118 times in the week after the cache shipped), and the cycle's
large short-lived allocations are what glibc otherwise holds on to.

The cache is per process: this helps because the API runs one uvicorn worker
(``warn-v2 serve``) and one replica.
"""
from __future__ import annotations

import ctypes
import logging
import mmap
import os
import threading
import time
from datetime import date

from warn_v2.api.routes import map_places, stats
from warn_v2.api.timeline import TTL_S, Bucket
from warn_v2.db.session import get_session_factory

log = logging.getLogger(__name__)

# The window starts /map's timeline offers (frontend/src/lib/timelapse.ts
# WINDOWS). All are Jan 1, so each is a whole-month floor on the widest.
WINDOWS = (date(2015, 1, 1), date(2010, 1, 1), date(1999, 1, 1))
# /map loads months and rolls them up in the browser, so only monthly
# bodies are requested; other buckets are built on demand.
BUCKETS: tuple[Bucket, ...] = ("month",)
REFRESH_S = TTL_S - 5 * 60


def warm_once() -> None:
    """Rebuild every default timeline body from one query per endpoint."""
    widest = min(WINDOWS)
    db = get_session_factory()()
    try:
        places = map_places.place_months(db, map_places.PlaceFilters(after=widest), refresh=True)
        industries = stats.industry_months(db, stats.IndustryFilters(after=widest), refresh=True)
        for after in WINDOWS:
            for bucket in BUCKETS:
                map_places.timeline_body(
                    db, bucket, map_places.PlaceFilters(after=after), refresh=True, rows=places
                )
                stats.industries_timeline_body(
                    db, bucket, stats.IndustryFilters(after=after), refresh=True, rows=industries
                )
    finally:
        db.close()


def _release_freed_memory() -> None:
    """Return free heap pages to the OS (glibc's malloc_trim; a no-op on other
    platforms). Python frees the cycle's garbage, but glibc keeps the pages
    mapped in fragmented arenas, so RSS ratchets up cycle after cycle."""
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass


def _rss_mb() -> float | None:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * mmap.PAGESIZE / 1e6
    except (OSError, ValueError):
        return None


def _run(stop: threading.Event) -> None:
    while True:
        started = time.monotonic()
        try:
            warm_once()
            _release_freed_memory()
            log.info(
                "timeline cache warmed in %.1fs; rss %s MB",
                time.monotonic() - started,
                f"{rss:.0f}" if (rss := _rss_mb()) is not None else "?",
            )
        except Exception:
            log.warning("timeline cache warm-up failed", exc_info=True)
        if stop.wait(REFRESH_S):
            return


def start() -> threading.Event | None:
    """Start the warmer thread; set the returned event to stop it.
    ``TIMELINE_WARMUP=0`` disables it (the test suite does)."""
    if os.getenv("TIMELINE_WARMUP", "1") == "0":
        return None
    stop = threading.Event()
    threading.Thread(target=_run, args=(stop,), name="timeline-warm", daemon=True).start()
    return stop
