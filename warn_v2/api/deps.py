"""FastAPI dependency injection helpers."""
from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from warn_v2 import auth
from warn_v2.api.schemas import (
    CompanyEnrichedOut,
    CompanyOut,
    NoticeEnrichedOut,
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


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    """Resolve the session cookie to a User, or None for anonymous/expired."""
    token = request.cookies.get(auth.COOKIE_NAME)
    if not token:
        return None
    return auth.resolve_session(db, token)


def require_admin(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    return user


class ViewerSchemas:
    """Company/notice output schemas for the requesting user's role.

    paid/admin sessions get the *EnrichedOut subclasses (D&B fields included);
    anonymous and free users get the base schemas — today's exact public shape.
    """

    def __init__(self, user: User | None = Depends(get_current_user)) -> None:
        self.enriched = user is not None and user.role in ("paid", "admin")
        self.company: type[CompanyOut] = CompanyEnrichedOut if self.enriched else CompanyOut
        self.notice: type[NoticeOut] = NoticeEnrichedOut if self.enriched else NoticeOut

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
