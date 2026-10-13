"""Routes: /og/states/{code}.png — per-state social-share card images.

At the site root (not /api), like the sitemap and feeds: unfurlers fetch the
URL the page's og:image tag names (see warn_v2.api.seo), and it should read as
an asset of the page, not an API call. Rendering takes ~60 ms, so each card is
kept in-process for a day -- the same window it's cached downstream for.
"""
from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2.api import og_cards
from warn_v2.api.deps import get_db
from warn_v2.api.routes.stats import (
    _aggregate_over_time,
    _apply_closure_filter,
    _not_superseded,
    _today,
)
from warn_v2.db.models import Notice
from warn_v2.states import is_valid_state, state_name

router = APIRouter(tags=["seo"], include_in_schema=False)

TTL_S = 24 * 3600
_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()


def _state_card(db: Session, code: str) -> bytes:
    # Same population as /api/stats/by-state: not superseded, Non-WARN out.
    stmt = select(
        func.count(Notice.notice_id),
        func.coalesce(func.sum(Notice.layoff_count), 0),
        func.count(Notice.layoff_count),  # notices that publish a count at all
    ).where(Notice.state == code)
    stmt = _apply_closure_filter(_not_superseded(stmt), None)
    notices, workers, counted = db.execute(stmt).one()

    rows = _aggregate_over_time(
        db,
        substr_len=4,
        state=code,
        closure_category=None,
        industry=None,
        subsector=None,
        after=None,
        before=None,
    )
    this_year = str(_today().year)
    # Complete years only: the partial current year would draw as a collapse.
    yearly = [(year, int(total)) for year, _n, total in rows if year < this_year]
    return og_cards.render_state_card(
        code,
        state_name(code) or code,
        # None (a dash + "not published") only when notices exist but none
        # carries a count; a state with no notices at all honestly shows 0.
        None if notices and not counted else int(workers),
        int(notices),
        yearly,
    )


@router.get("/og/states/{code}.png")
def state_card(code: str, db: Session = Depends(get_db)) -> Response:
    code = code.upper()
    if not is_valid_state(code):
        raise HTTPException(status_code=404, detail="Unknown state")
    now = time.monotonic()
    with _lock:
        hit = _cache.get(code)
    if hit is None or hit[0] < now:
        hit = (now + TTL_S, _state_card(db, code))
        with _lock:
            _cache[code] = hit
    return Response(
        content=hit[1],
        media_type="image/png",
        headers={"Cache-Control": f"public, max-age={TTL_S}"},
    )
