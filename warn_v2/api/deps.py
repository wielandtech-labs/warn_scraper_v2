"""FastAPI dependency injection helpers."""
from __future__ import annotations

from collections.abc import Generator

from fastapi import Query
from sqlalchemy.orm import Session

from warn_v2.db.session import get_session_factory


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session; close it on exit regardless of exceptions."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


class PaginationParams:
    """Reusable limit/offset query parameters with a safety cap."""

    def __init__(
        self,
        limit: int = Query(50, ge=1, le=500, description="Max items to return"),
        offset: int = Query(0, ge=0, description="Number of items to skip"),
    ) -> None:
        self.limit = limit
        self.offset = offset
