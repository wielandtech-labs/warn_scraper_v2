"""API-key management endpoints.

Authenticates exclusively via the session cookie (get_cookie_user), never via
an API key — a leaked key must not be able to mint or revoke keys.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from warn_v2 import api_keys
from warn_v2.api.deps import get_cookie_user, get_db
from warn_v2.db.models import ApiKey, User

router = APIRouter(prefix="/keys", tags=["keys"])


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    prefix: str
    name: str | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(ApiKeyOut):
    key: str  # the raw key — returned exactly once, never retrievable again


class CreateKeyIn(BaseModel):
    name: str | None = Field(None, max_length=64)


def _require_session(user: User | None = Depends(get_cookie_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("", status_code=201)
def create_key(
    body: CreateKeyIn,
    user: User = Depends(_require_session),
    db: Session = Depends(get_db),
) -> ApiKeyCreatedOut:
    if user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="Verify your email before creating keys")
    active = db.scalar(
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
    ) or 0
    if active >= api_keys.MAX_ACTIVE_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Active key limit reached ({api_keys.MAX_ACTIVE_KEYS}); revoke one first",
        )
    key, raw = api_keys.create_key(db, user, body.name)
    db.commit()
    return ApiKeyCreatedOut(
        id=key.id,
        prefix=key.prefix,
        name=key.name,
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        key=raw,
    )


@router.get("")
def list_keys(
    user: User = Depends(_require_session), db: Session = Depends(get_db)
) -> list[ApiKeyOut]:
    rows = db.scalars(
        select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())
    )
    return [ApiKeyOut.model_validate(k) for k in rows]


@router.delete("/{key_id}")
def revoke_key(
    key_id: int,
    user: User = Depends(_require_session),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    key = db.get(ApiKey, key_id)
    # 404 for both "doesn't exist" and "not yours" — no key-id probing.
    if key is None or key.user_id != user.id:
        raise HTTPException(status_code=404, detail="Key not found")
    if key.revoked_at is None:
        api_keys.revoke_key(db, key)
        db.commit()
    return {"status": "revoked"}
