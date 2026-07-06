"""Route: /api/usage — the caller's tier, limits, and today's metered usage."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.api import ratelimit
from warn_v2.api.deps import get_current_user, get_db
from warn_v2.db.models import ApiKey, ApiUsageDaily, User

router = APIRouter(tags=["usage"])


class KeyUsageOut(BaseModel):
    prefix: str
    name: str | None
    today: int


class UsageOut(BaseModel):
    tier: str
    per_minute_limit: int | None  # None = unlimited (admin)
    daily_limit: int | None  # None = no daily quota for this tier
    today: int  # summed across the user's keys
    keys: list[KeyUsageOut]


@router.get("/usage")
def usage(
    user: User | None = Depends(get_current_user), db: Session = Depends(get_db)
) -> UsageOut:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    today = datetime.now(UTC).date()
    rows = db.execute(
        select(ApiKey.prefix, ApiKey.name, ApiUsageDaily.count)
        .join(
            ApiUsageDaily,
            # Day predicate must live in the ON clause: in the WHERE it would
            # drop keys whose only usage rows are from earlier days. The outer
            # join keeps unused keys visible with today=0.
            (ApiUsageDaily.key_id == ApiKey.id) & (ApiUsageDaily.day == today),
            isouter=True,
        )
        .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
    ).all()

    keys = [KeyUsageOut(prefix=p, name=n, today=c or 0) for p, n, c in rows]
    return UsageOut(
        tier=user.role,
        per_minute_limit=ratelimit.PER_MINUTE.get(user.role) if user.role != "admin" else None,
        daily_limit=ratelimit.PER_DAY.get(user.role),
        today=sum(k.today for k in keys),
        keys=keys,
    )
