"""SQLAlchemy models — see plan §Data model for rationale."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# SQLite requires INTEGER for autoincrement to work; Postgres is fine with BIGINT.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    pass


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    city: Mapped[str | None] = mapped_column(Text)
    county: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(2), index=True)
    zip: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lon: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    geocode_source: Mapped[str | None] = mapped_column(String(16))
    # Values: 'census' | 'zip' | 'city' | 'county'. Null for pre-migration rows.

    __table_args__ = (
        UniqueConstraint("state", "city", "zip", name="uq_locations_state_city_zip"),
    )


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    duns: Mapped[str | None] = mapped_column(String(16), index=True)
    sic_code: Mapped[str | None] = mapped_column(String(8))
    sic_desc: Mapped[str | None] = mapped_column(String(256))
    naics_code: Mapped[str | None] = mapped_column(String(8))
    naics_desc: Mapped[str | None] = mapped_column(String(256))
    website: Mapped[str | None] = mapped_column(String(512))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    parent_company_name: Mapped[str | None] = mapped_column(String(512))
    parent_duns: Mapped[str | None] = mapped_column(String(16), index=True)
    global_ultimate_name: Mapped[str | None] = mapped_column(String(512))
    hq_address: Mapped[str | None] = mapped_column(Text)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enrichment_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    enrichment_sources: Mapped[str | None] = mapped_column(Text)  # JSON-encoded list
    enrichment_source: Mapped[str | None] = mapped_column(String(16))
    # Values: 'provider' | 'edgar' | 'claude'. Null for rows enriched before this field existed.

    # --- consolidation (see warn_v2/scripts/consolidate_companies.py) ---
    canonical_company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )  # set => duplicate of the canonical (same legal entity); canonical row = NULL
    name_normalized: Mapped[str | None] = mapped_column(String(512), index=True)
    global_ultimate_duns: Mapped[str | None] = mapped_column(String(16), index=True)
    global_ultimate_id: Mapped[str | None] = mapped_column(String(64), index=True)
    # D&B's stable id for the global ultimate (from its profile href) — exact,
    # free sibling-grouping key shared by all subsidiaries of one parent.
    parent_group_key: Mapped[str | None] = mapped_column(String(512), index=True)


class Notice(Base):
    __tablename__ = "notices"

    notice_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    employer: Mapped[str] = mapped_column(String(512), nullable=False)
    notice_date: Mapped[date | None] = mapped_column(Date, index=True)
    effective_date: Mapped[date | None] = mapped_column(Date)
    layoff_count: Mapped[int | None] = mapped_column(Integer)
    closure_type: Mapped[str | None] = mapped_column(Text)
    # Normalized bucket derived from closure_type: 'Closure' | 'Layoff' | None.
    # See warn_v2.closure.normalize_closure_category.
    closure_category: Mapped[str | None] = mapped_column(String(16), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(1024))
    raw_notice_url: Mapped[str | None] = mapped_column(String(1024))
    pdf_path: Mapped[str | None] = mapped_column(String(1024))
    is_superseded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    company_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("companies.id", ondelete="SET NULL")
    )
    location_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("locations.id", ondelete="SET NULL")
    )

    company: Mapped[Company | None] = relationship("Company")
    location: Mapped[Location | None] = relationship("Location")

    __table_args__ = (
        Index("ix_notices_state_notice_date", "state", "notice_date"),
    )


class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_scraped: Mapped[int | None] = mapped_column(Integer)
    rows_new: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # ok | fetch_failed | parse_failed | validation_failed | storage_failed
    error: Mapped[str | None] = mapped_column(Text)
    snapshot_path: Mapped[str | None] = mapped_column(String(1024))
