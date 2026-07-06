"""Rate limiting + usage metering for the data endpoints.

Two timescales, two mechanisms:

- Per-minute burst: in-process sliding window. Deliberately in-memory — with
  api.replicas=1 there is no cross-pod coherence problem, and losing a
  60-second window on deploy is harmless. If replicas ever go >1 each pod
  enforces the limit independently (effective limit x N); revisit before
  scaling out.
- Daily quota (API-keyed requests only): a Postgres counter row per key per
  day (api_usage_daily). Lives in the DB because it is also the billing/abuse
  audit trail and must survive restarts.

Anonymous requests are limited per client IP at browser-friendly rates — the
same-origin SPA must never trip them. Admin users are exempt.

Limits are env-tunable (RATE_* vars) so a bad limit is a values-change hotfix,
not a code deploy.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response
from prometheus_client import Counter
from sqlalchemy.orm import Session

from warn_v2.api.deps import get_current_user, get_db
from warn_v2.db.models import ApiKey, ApiUsageDaily, User

ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") != "0"

# Requests per sliding 60s window. Anonymous covers the same-origin SPA: its
# heaviest page fires <10 calls, so 120/min is ~10x human browsing.
PER_MINUTE = {
    "anon": int(os.getenv("RATE_ANON_PER_MIN", "120")),
    "free": int(os.getenv("RATE_FREE_PER_MIN", "120")),
    "paid": int(os.getenv("RATE_PAID_PER_MIN", "600")),
    "enterprise": int(os.getenv("RATE_ENTERPRISE_PER_MIN", "600")),
}

# Requests per UTC day, enforced only for API-keyed requests (sessions and
# anonymous browsing carry no daily quota — burst limiting is enough there).
PER_DAY = {
    "free": int(os.getenv("RATE_FREE_PER_DAY", "2000")),
    "paid": int(os.getenv("RATE_PAID_PER_DAY", "100000")),
    "enterprise": int(os.getenv("RATE_ENTERPRISE_PER_DAY", "100000")),
}

_WINDOW_SECONDS = 60
_PRUNE_INTERVAL = 300  # drop idle identities every 5 minutes

REQUESTS_TOTAL = Counter(
    "warn_api_requests_total", "Requests through the rate limiter", ["tier"]
)
RATE_LIMITED_TOTAL = Counter(
    "warn_api_rate_limited_total", "Requests rejected with 429", ["tier"]
)


class SlidingWindowLimiter:
    """Per-identity sliding window over the last 60 seconds. Thread-safe."""

    def __init__(self, window: float = _WINDOW_SECONDS, clock=time.time) -> None:
        self._window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_prune = clock()

    def hit(self, ident: str, limit: int) -> tuple[bool, int, float]:
        """Record a request; returns (allowed, remaining, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            if now - self._last_prune >= _PRUNE_INTERVAL:
                self._prune(now)
            window = self._hits.setdefault(ident, deque())
            cutoff = now - self._window
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= limit:
                return False, 0, window[0] + self._window - now
            window.append(now)  # rejected requests don't extend the window
            return True, limit - len(window), 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        for ident in list(self._hits):
            window = self._hits[ident]
            while window and window[0] <= cutoff:
                window.popleft()
            if not window:
                del self._hits[ident]
        self._last_prune = now


_minute_limiter = SlidingWindowLimiter()


def _bump_daily(db: Session, key_id: int) -> int:
    """Increment today's counter for a key and return the new count."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:  # tests run SQLite
        from sqlalchemy.dialects.sqlite import insert
    stmt = (
        insert(ApiUsageDaily)
        .values(key_id=key_id, day=datetime.now(UTC).date(), count=1)
        .on_conflict_do_update(
            index_elements=["key_id", "day"],
            set_={"count": ApiUsageDaily.count + 1},
        )
        .returning(ApiUsageDaily.count)
    )
    count = db.execute(stmt).scalar_one()
    db.commit()
    return count


def _client_ip(request: Request) -> str:
    # Real client IPs require uvicorn's proxy_headers behind Traefik — see
    # the serve command. Fall back to a shared bucket if unset.
    return request.client.host if request.client else "unknown"


def enforce_limits(
    request: Request,
    response: Response,
    user: User | None = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Router-level dependency for the data endpoints (not auth/keys/webhooks)."""
    if not ENABLED:
        return
    role = user.role if user is not None else None
    if role == "admin":
        REQUESTS_TOTAL.labels(tier="admin").inc()
        return

    key: ApiKey | None = getattr(request.state, "api_key", None)
    if key is not None:
        tier, ident = role, f"key:{key.id}"
    elif user is not None:
        tier, ident = role, f"user:{user.id}"
    else:
        tier, ident = "anon", f"ip:{_client_ip(request)}"

    REQUESTS_TOTAL.labels(tier=tier).inc()
    limit = PER_MINUTE.get(tier, PER_MINUTE["anon"])
    allowed, remaining, retry_after = _minute_limiter.hit(ident, limit)
    if not allowed:
        RATE_LIMITED_TOTAL.labels(tier=tier).inc()
        raise HTTPException(
            status_code=429,
            detail=(
                "Rate limit exceeded. Sign up for a free API key at /account "
                "for stable programmatic access."
            ),
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

    if key is not None:
        daily_limit = PER_DAY.get(tier, PER_DAY["free"])
        count = _bump_daily(db, key.id)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Daily-Limit"] = str(daily_limit)
        response.headers["X-RateLimit-Daily-Remaining"] = str(max(0, daily_limit - count))
        if count > daily_limit:
            RATE_LIMITED_TOTAL.labels(tier=tier).inc()
            raise HTTPException(
                status_code=429,
                detail="Daily quota exceeded — see /api/usage for your limits.",
                headers={"Retry-After": "3600"},
            )
