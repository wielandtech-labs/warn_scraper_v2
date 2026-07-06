"""FastAPI dependency injection helpers."""
from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from warn_v2 import api_keys, auth
from warn_v2.api.schemas import (
    CompanyEnrichedOut,
    CompanyEnterpriseOut,
    CompanyOut,
    NoticeEnrichedOut,
    NoticeEnterpriseOut,
    NoticeOut,
    Page,
)
from warn_v2.db.models import User
from warn_v2.db.session import get_session_factory


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session; close it on exit regardless of exceptions."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def get_cookie_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Resolve ONLY the session cookie — API keys deliberately don't count.

    Key-management (and later billing) routes depend on this so a leaked API
    key can never mint, list, or revoke keys.
    """
    token = request.cookies.get(auth.COOKIE_NAME)
    if not token:
        return None
    return auth.resolve_session(db, token)


def _bearer_key(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Resolve the session cookie or an API key to a User; None for anonymous.

    Keys are accepted as ``X-API-Key: warn_...`` or ``Authorization: Bearer
    warn_...``. The resolved ApiKey row is stashed on request.state.api_key for
    metering/rate limiting.
    """
    user = get_cookie_user(request, db)
    if user is not None:
        return user
    raw = request.headers.get("x-api-key") or _bearer_key(request)
    if raw and raw.startswith(api_keys.KEY_PREFIX):
        resolved = api_keys.resolve_key(db, raw)
        if resolved is not None:
            user, key = resolved
            request.state.api_key = key
            return user
    return None


def require_admin(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


class ViewerSchemas:
    """Company/notice output schemas for the requesting user's role.

    enterprise/admin sessions get the *EnterpriseOut subclasses (D&B fields
    including raw DUNS); paid sessions get *EnrichedOut (D&B fields minus DUNS);
    anonymous and free users get the base schemas — today's exact public shape.
    """

    def __init__(self, user: User | None = Depends(get_current_user)) -> None:
        role = user.role if user is not None else None
        self.enterprise = role in ("enterprise", "admin")
        self.enriched = self.enterprise or role == "paid"
        if self.enterprise:
            self.company: type[CompanyOut] = CompanyEnterpriseOut
            self.notice: type[NoticeOut] = NoticeEnterpriseOut
        elif self.enriched:
            self.company = CompanyEnrichedOut
            self.notice = NoticeEnrichedOut
        else:
            self.company = CompanyOut
            self.notice = NoticeOut

    # Routes using these must set response_model=None: a static response_model
    # (and Pydantic's annotation-based nested serialization) would strip the
    # enriched fields, so Page must be parametrized with the runtime class.
    def company_page(self, items: list, total: int, limit: int, offset: int) -> Page:
        cls = Page[self.company]  # type: ignore[misc, valid-type]
        return cls(
            items=[self.company.model_validate(c) for c in items],
            total=total, limit=limit, offset=offset,
        )

    def notice_page(self, items: list, total: int, limit: int, offset: int) -> Page:
        cls = Page[self.notice]  # type: ignore[misc, valid-type]
        return cls(
            items=[self.notice.model_validate(n) for n in items],
            total=total, limit=limit, offset=offset,
        )


class PaginationParams:
    """Reusable limit/offset query parameters with a safety cap."""

    def __init__(
        self,
        limit: int = Query(50, ge=1, le=500, description="Max items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ) -> None:
        self.limit = limit
        self.offset = offset
