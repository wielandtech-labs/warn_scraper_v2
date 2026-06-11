"""Password hashing and cookie-session auth core.

Sessions are server-side rows in user_sessions: the browser cookie carries a
random token and the DB stores only its sha256, so a DB leak does not leak
usable session tokens. Expiry is absolute (no sliding) for predictability.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from warn_v2.db.models import User, UserSession

SESSION_TTL = timedelta(days=30)
COOKIE_NAME = "warn_session"

_ph = PasswordHasher()
# Verified against when the email is unknown so both failure modes take the
# same time — no account enumeration via response latency.
_DUMMY_HASH = _ph.hash("warn-v2-timing-equalizer")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def authenticate(db: Session, email: str, password: str) -> tuple[User, str] | None:
    """Check credentials; on success create a session and return (user, raw token).

    Returns None for unknown email and wrong password alike. Does not commit —
    the caller owns the transaction.
    """
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    # Opportunistic cleanup; the table only holds admin-provisioned accounts.
    db.execute(delete(UserSession).where(UserSession.expires_at < datetime.now(UTC)))
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_sha256=_sha256(token),
            user_id=user.id,
            expires_at=datetime.now(UTC) + SESSION_TTL,
        )
    )
    return user, token


def resolve_session(db: Session, token: str) -> User | None:
    """Return the session's user, or None if the token is unknown or expired."""
    sess = db.scalar(select(UserSession).where(UserSession.token_sha256 == _sha256(token)))
    if sess is None:
        return None
    expires_at = sess.expires_at
    if expires_at.tzinfo is None:  # SQLite round-trips naive datetimes
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        return None
    return db.get(User, sess.user_id)


def end_session(db: Session, token: str) -> None:
    """Delete the session row for a raw token (logout). Caller commits."""
    db.execute(delete(UserSession).where(UserSession.token_sha256 == _sha256(token)))
