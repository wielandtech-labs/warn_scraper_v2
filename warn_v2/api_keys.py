"""API-key auth core, the programmatic sibling of warn_v2.auth's sessions.

The caller holds the raw key (shown exactly once at creation) and the DB stores
only its sha256, so a DB leak does not leak usable keys. Keys don't expire;
revocation is a soft timestamp so usage history survives for audit.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from warn_v2.db.models import ApiKey, User

KEY_PREFIX = "warn_"
PREFIX_DISPLAY_LEN = 13  # "warn_" + 8 chars: enough to tell keys apart
MAX_ACTIVE_KEYS = 5
# last_used_at is display metadata, not an audit log — throttle writes so a hot
# key doesn't turn every GET into an UPDATE + commit.
_LAST_USED_RESOLUTION = timedelta(minutes=5)


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_key(db: Session, user: User, name: str | None = None) -> tuple[ApiKey, str]:
    """Mint a key for ``user``; returns (row, raw key). Caller owns the transaction."""
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey(
        user_id=user.id,
        key_sha256=_sha256(raw),
        prefix=raw[:PREFIX_DISPLAY_LEN],
        name=name,
    )
    db.add(key)
    db.flush()
    return key, raw


def resolve_key(db: Session, raw: str) -> tuple[User, ApiKey] | None:
    """Return (user, key) for a raw key, or None if unknown or revoked."""
    key = db.scalar(select(ApiKey).where(ApiKey.key_sha256 == _sha256(raw)))
    if key is None or key.revoked_at is not None:
        return None
    user = db.get(User, key.user_id)
    if user is None:
        return None
    now = datetime.now(UTC)
    last = key.last_used_at
    if last is not None and last.tzinfo is None:  # SQLite round-trips naive datetimes
        last = last.replace(tzinfo=UTC)
    if last is None or now - last >= _LAST_USED_RESOLUTION:
        key.last_used_at = now
        db.commit()  # routes are read-only and never commit; persist the bump here
    return user, key


def revoke_key(db: Session, key: ApiKey) -> None:
    """Soft-revoke: the key stops resolving but the row remains. Caller commits."""
    key.revoked_at = datetime.now(UTC)
