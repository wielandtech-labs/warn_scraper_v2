"""Routes: /og/states/{code}.png and /og/notices/{id}.png — social-share cards.

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
from warn_v2.api.filters import apply_stats_closure_filter as _apply_closure_filter
from warn_v2.api.routes.stats import (
    _aggregate_over_time,
    _not_superseded,
    _today,
)
from warn_v2.closure import closure_label
from warn_v2.db.models import Notice
from warn_v2.notifications.templates import fmt_date
from warn_v2.states import is_valid_state, state_name

router = APIRouter(tags=["seo"], include_in_schema=False)

TTL_S = 24 * 3600
_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()
# Notice cards are keyed by an unbounded id space (crawlers walk every notice),
# so that cache is capped; oldest-inserted entries go first.
NOTICE_CACHE_MAX = 512
_notice_cache: dict[str, tuple[float, bytes]] = {}


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


def notice_card_png(notice: Notice) -> bytes:
    """Render `notice`'s share card. Also used by warn_v2.social to attach the
    card to posts without an HTTP round trip."""
    st_name = state_name(notice.state) or notice.state
    city = notice.location.city if notice.location else None
    place = f"{city}, {notice.state}" if city else st_name
    dates = [f"Filed {fmt_date(notice.notice_date)}"] if notice.notice_date else []
    if notice.effective_date:
        dates.append(f"Effective {fmt_date(notice.effective_date)}")
    return og_cards.render_notice_card(
        employer=notice.employer,
        code=notice.state,
        place=place,
        workers=notice.layoff_count,
        action=closure_label(notice.closure_category),
        dates=" · ".join(dates) or "Date not published",
    )


@router.get("/og/notices/{notice_id}.png")
def notice_card(notice_id: str, db: Session = Depends(get_db)) -> Response:
    now = time.monotonic()
    with _lock:
        hit = _notice_cache.get(notice_id)
    if hit is None or hit[0] < now:
        notice = db.get(Notice, notice_id)
        if notice is None:
            raise HTTPException(status_code=404, detail="Unknown notice")
        hit = (now + TTL_S, notice_card_png(notice))
        with _lock:
            _notice_cache.pop(notice_id, None)
            while len(_notice_cache) >= NOTICE_CACHE_MAX:
                _notice_cache.pop(next(iter(_notice_cache)))
            _notice_cache[notice_id] = hit
    return Response(
        content=hit[1],
        media_type="image/png",
        headers={"Cache-Control": f"public, max-age={TTL_S}"},
    )
