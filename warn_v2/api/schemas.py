"""Pydantic response schemas for the WARN Scraper read-only API."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LocationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    city: str | None
    county: str | None
    state: str
    zip: str | None
    lat: Decimal | None
    lon: Decimal | None
    geocode_source: str | None


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    # Set when this row was consolidated into another (the canonical/survivor).
    # Null on canonical rows. Just a pointer — not D&B data — so safe to expose.
    canonical_company_id: int | None
    # NOTE: enrichment fields duns, employee_count, parent_company_name,
    # parent_duns, global_ultimate_name, and hq_address are deliberately NOT
    # exposed here. They are stored for internal use only; publishing D&B-sourced
    # data would conflict with its redistribution terms. Surface only low-risk
    # fields (website, industry codes) publicly.
    sic_code: str | None
    sic_desc: str | None
    naics_code: str | None
    naics_desc: str | None
    website: str | None
    enriched_at: datetime | None
    enrichment_confidence: Decimal | None
    enrichment_source: str | None
    # Workers affected across non-superseded notices, rolled up over merged
    # dupes. Computed only by the companies *list* route; None elsewhere
    # ("not computed" — not zero).
    layoff_total: int | None = None


class CompanyEnrichedOut(CompanyOut):
    """CompanyOut + D&B enrichment fields, minus raw DUNS identifiers.

    Served to paid sessions and above. Anonymous and free-tier responses use
    CompanyOut, so these keys are absent (not null) for them — the public shape
    never includes D&B-sourced fields.
    """

    parent_company_name: str | None
    global_ultimate_name: str | None
    hq_address: str | None
    employee_count: int | None


class CompanyEnterpriseOut(CompanyEnrichedOut):
    """CompanyEnrichedOut + raw DUNS identifiers.

    Served only to enterprise/admin sessions — DUNS numbers are the top-tier
    differentiator and never appear below this level.
    """

    duns: str | None
    parent_duns: str | None


class FamilyMemberOut(BaseModel):
    """One company in a corporate family (siblings sharing a parent_group_key).

    Anonymous by design: identifies the family only by its member WARN companies,
    never by the D&B-derived parent name or the internal grouping key, per the
    selective-exposure policy on CompanyOut.
    """

    company_id: int
    name: str
    notice_count: int
    layoff_total: int
    # True for the canonical row the requested company rolls up into.
    is_self: bool


class NoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notice_id: str
    state: str
    employer: str
    notice_date: date | None
    effective_date: date | None
    layoff_count: int | None
    closure_type: str | None
    closure_category: str | None
    address: str | None
    source_url: str | None
    raw_notice_url: str | None
    pdf_path: str | None
    scraped_at: datetime
    company: CompanyOut | None
    location: LocationOut | None


class NoticeEnrichedOut(NoticeOut):
    # Annotation override is required: Pydantic v2 serializes nested models by
    # annotation, so a CompanyEnrichedOut inside plain NoticeOut would be
    # stripped back down to CompanyOut's fields.
    company: CompanyEnrichedOut | None


class NoticeEnterpriseOut(NoticeEnrichedOut):
    company: CompanyEnterpriseOut | None


class ScraperRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    state: str
    started_at: datetime
    finished_at: datetime | None
    rows_scraped: int | None
    rows_new: int | None
    status: str
    error: str | None


class StateStatusOut(BaseModel):
    """Per-state scraper health: the latest run plus the latest *successful* run.

    Powers the public status page. One row per state that has any run history;
    states that have never run are absent (the frontend fills those in).
    """

    state: str
    last_run_at: datetime
    last_status: str
    last_finished_at: datetime | None
    rows_scraped: int | None
    rows_new: int | None
    error: str | None
    last_success_at: datetime | None
    # Notice-date coverage: how far back this state's data reaches. Null when
    # the state has runs but no (non-superseded) notices yet.
    first_notice_date: date | None
    last_notice_date: date | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class SearchCompanyOut(BaseModel):
    """Minimal company hit for the global search / autocomplete box."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class SearchNoticeOut(BaseModel):
    """Minimal notice hit for the global search / autocomplete box."""

    model_config = ConfigDict(from_attributes=True)

    notice_id: str
    employer: str
    state: str
    notice_date: date | None


class SearchResults(BaseModel):
    companies: list[SearchCompanyOut]
    notices: list[SearchNoticeOut]


class MapPinOut(BaseModel):
    """Lightweight notice projection used exclusively by the map endpoint.

    Contains only the 7 fields the map popup actually renders, keeping the
    response ~7x smaller than a full NoticeOut so all geocoded notices can
    be returned in a single fetch without hitting payload size concerns.
    """

    model_config = ConfigDict(from_attributes=True)

    notice_id: str
    employer: str
    state: str
    notice_date: date | None
    layoff_count: int | None
    lat: float
    lon: float
