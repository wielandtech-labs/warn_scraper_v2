"""Routes: /api/logos/{company_id} — a company's own site icon, proxied + cached.

Mounted OUTSIDE the rate limiter: one companies page renders dozens of logos,
which would eat an anonymous visitor's 120/min budget for the data calls.
Abuse is bounded anyway -- the caller picks a company id, not a URL, and each
domain is fetched at most once per cache TTL (see warn_v2.api.logo_fetch).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from warn_v2.api import logo_fetch
from warn_v2.api.deps import get_db
from warn_v2.db.models import Company

router = APIRouter(prefix="/logos", tags=["companies"])

_HIT_CACHE = f"public, max-age={logo_fetch.HIT_TTL_S}"
_MISS_CACHE = f"public, max-age={logo_fetch.MISS_TTL_S}"

# Outbound fetches get their OWN small pool. Sync routes share Starlette's
# 40-thread pool; a cold companies page (25+ uncached logos, each up to
# DEADLINE_S) would otherwise starve every data endpoint behind it.
_FETCH_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="logo-fetch")


@router.get("/{company_id}", include_in_schema=False)
async def company_logo(company_id: int, db: Session = Depends(get_db)) -> Response:
    company = await run_in_threadpool(db.get, Company, company_id)
    website = company.website if company is not None else None
    logo_url = company.logo_url if company is not None else None
    if company is not None and logo_url is None and company.canonical_company_id:
        # Logo search only covers canonical rows; merged dupes (often what a
        # notice links to) borrow the canonical's override.
        canonical = await run_in_threadpool(db.get, Company, company.canonical_company_id)
        logo_url = canonical.logo_url if canonical is not None else None
    loop = asyncio.get_running_loop()
    found = await loop.run_in_executor(_FETCH_POOL, logo_fetch.logo_for, website, logo_url)
    if found is None:
        # Cached 404: the UI keeps its monogram, and won't re-ask for a day.
        return Response(status_code=404, headers={"Cache-Control": _MISS_CACHE})
    body, media = found
    return Response(
        content=body,
        media_type=media,
        headers={"Cache-Control": _HIT_CACHE, "X-Content-Type-Options": "nosniff"},
    )
