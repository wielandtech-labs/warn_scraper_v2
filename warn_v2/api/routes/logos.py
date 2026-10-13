"""Routes: /api/logos/{company_id} — a company's own site icon, proxied + cached.

Mounted OUTSIDE the rate limiter: one companies page renders dozens of logos,
which would eat an anonymous visitor's 120/min budget for the data calls.
Abuse is bounded anyway -- the caller picks a company id, not a URL, and each
domain is fetched at most once per cache TTL (see warn_v2.api.logo_fetch).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from warn_v2.api import logo_fetch
from warn_v2.api.deps import get_db
from warn_v2.db.models import Company

router = APIRouter(prefix="/logos", tags=["companies"])

_HIT_CACHE = f"public, max-age={logo_fetch.HIT_TTL_S}"
_MISS_CACHE = f"public, max-age={logo_fetch.MISS_TTL_S}"


@router.get("/{company_id}", include_in_schema=False)
def company_logo(company_id: int, db: Session = Depends(get_db)) -> Response:
    company = db.get(Company, company_id)
    website = company.website if company is not None else None
    found = logo_fetch.logo_for(website)  # sync route: FastAPI runs it in the threadpool
    if found is None:
        # Cached 404: the UI keeps its monogram, and won't re-ask for a day.
        return Response(status_code=404, headers={"Cache-Control": _MISS_CACHE})
    body, media = found
    return Response(
        content=body,
        media_type=media,
        headers={"Cache-Control": _HIT_CACHE, "X-Content-Type-Options": "nosniff"},
    )
