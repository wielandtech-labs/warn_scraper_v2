"""Shared notice query filters.

The same set of notice filters (state, employer, closure category, industry,
date range, geocoded-only) is applied by several endpoints — the notices list
and its count query, the map-pins projection, CSV/JSON export, and the RSS
feeds. Centralising them here keeps the semantics (and the eventual switch from
substring to trigram employer search) in one place.

Each helper takes a SQLAlchemy ``Select`` over ``Notice`` and returns the
modified statement, so it composes with whatever projection/ordering the caller
has already built.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import Select

from warn_v2.companies.naics import naics_filter
from warn_v2.db.models import Company, Location, Notice


def apply_notice_filters(
    stmt: Select,
    *,
    state: str | None = None,
    employer: str | None = None,
    closure_category: str | None = None,
    industry: str | None = None,
    subsector: str | None = None,
    after: date | None = None,
    before: date | None = None,
    geocoded_only: bool = False,
    location_joined: bool = False,
) -> Select:
    """Apply the standard notice filters to a SELECT over ``Notice``.

    ``location_joined`` should be True when the caller has already joined
    ``Location`` (e.g. the map-pins query), so a ``geocoded_only`` filter adds
    the lat/lon predicate without a duplicate join. An ``industry``/``subsector``
    filter inner-joins ``Company`` and so excludes notices with no linked
    company — matching the long-standing behaviour of the notices endpoint.
    """
    if state:
        stmt = stmt.where(Notice.state == state.upper())
    if employer:
        stmt = stmt.where(Notice.employer.ilike(f"%{employer}%"))
    if closure_category:
        stmt = stmt.where(Notice.closure_category == closure_category)
    industry_filter = naics_filter(Company.naics_code, industry, subsector)
    if industry_filter is not None:
        stmt = stmt.join(Company, Notice.company_id == Company.id).where(industry_filter)
    if after:
        stmt = stmt.where(Notice.notice_date >= after)
    if before:
        stmt = stmt.where(Notice.notice_date <= before)
    if geocoded_only:
        if not location_joined:
            stmt = stmt.join(Location, Notice.location_id == Location.id)
        stmt = stmt.where(Location.lat.is_not(None), Location.lon.is_not(None))
    return stmt
