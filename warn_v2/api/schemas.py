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


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    duns: str | None
    sic_code: str | None
    sic_desc: str | None
    naics_code: str | None
    naics_desc: str | None
    website: str | None
    enriched_at: datetime | None
    enrichment_confidence: Decimal | None
    enrichment_source: str | None


class NoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notice_id: str
    state: str
    employer: str
    notice_date: date | None
    effective_date: date | None
    layoff_count: int | None
    closure_type: str | None
    address: str | None
    source_url: str | None
    scraped_at: datetime
    company: CompanyOut | None
    location: LocationOut | None


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


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


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
    lat: Decimal
    lon: Decimal
