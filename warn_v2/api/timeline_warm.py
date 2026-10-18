"""Keep the /timelapse payloads warm, so no visitor pays the cold query.

The timeline caches (warn_v2.api.timeline) would otherwise make the first
visitor after each expiry wait 1.6-3 s. A daemon thread rebuilds every
unfiltered window x bucket the /timelapse page offers at startup, then every
``REFRESH_S`` -- inside the TTL, so those entries are replaced before they can
expire. Filtered views (a linked-view industry tap, a state) are cached on
first request only.

The cache is per process: this helps because the API runs one uvicorn worker
(``warn-v2 serve``) and one replica.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date

from warn_v2.api.routes import map_places, stats
from warn_v2.api.timeline import TTL_S, Bucket
from warn_v2.db.session import get_session_factory

log = logging.getLogger(__name__)

# The window starts /timelapse offers (frontend/src/routes/timelapse.tsx WINDOWS).
WINDOWS = (date(2015, 1, 1), date(2010, 1, 1), date(1999, 1, 1))
BUCKETS: tuple[Bucket, ...] = ("quarter", "year", "month")
REFRESH_S = TTL_S - 5 * 60


def warm_once() -> None:
    """Rebuild every default timeline body, querying each window once."""
    db = get_session_factory()()
    try:
        for after in WINDOWS:
            places = map_places.PlaceFilters(after=after)
            industries = stats.IndustryFilters(after=after)
            map_places.place_months(db, places, refresh=True)
            stats.industry_months(db, industries, refresh=True)
            # Rolled up from the rows just refreshed; no further SQL.
            for bucket in BUCKETS:
                map_places.timeline_body(db, bucket, places, refresh=True)
                stats.industries_timeline_body(db, bucket, industries, refresh=True)
    finally:
        db.close()


def _run(stop: threading.Event) -> None:
    while True:
        started = time.monotonic()
        try:
            warm_once()
            log.info("timeline cache warmed in %.1fs", time.monotonic() - started)
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
