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
    # When the external provider (D&B) last attempted this company — set on hit
    # AND miss, so provider-only runs work through the queue without retrying
    # misses forever. Cleared by reset-enrichment to grant another attempt.
    provider_attempted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
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
    # When the GA enricher last fetched this notice's TCSG entry page + attachment.
    # Set once a fetch succeeds (PDF stored, non-PDF extracted, or no attachment),
    # so already-processed notices drop out of the enricher's candidate set instead
    # of being re-fetched every nightly run (see warn_v2.scripts.enrich_ga).
    attachment_fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    # Stored lowercase; login lookups normalize the same way.
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)  # argon2 PHC string
    role: Mapped[str] = mapped_column(
        String(16), nullable=False, default="free", server_default="free"
    )
    # Values: 'admin' | 'enterprise' | 'paid' | 'free'. Plain String (no PG
    # ENUM) so SQLite tests work and adding roles needs no migration.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserSession(Base):
    """Server-side login session; the cookie holds the raw token, we store only its hash."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    user: Mapped[User] = relationship("User")


class ApiKey(Base):
    """Programmatic-access credential; the caller holds the raw key, we store only its hash.

    Keys don't expire; revocation is a soft timestamp (revoked_at) so the row —
    and any usage history hanging off it — survives for audit. The key's tier is
    always the owning user's current role, never a snapshot.
    """

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # First characters of the raw key ("warn_a1b2c3d4") — the only part ever
    # shown again after creation, so users can tell their keys apart.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship("User")


class Subscription(Base):
    """Email alert subscription (double opt-in).

    A row is created unconfirmed; the confirm link sets ``confirmed_at`` and the
    ``last_notified_at`` watermark to "now" so the subscriber only receives
    notices discovered after they confirm. The digest job advances the watermark
    each run. Filters are optional — null means "any".
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    # Optional filters (mirror the notices query params). Null => no constraint.
    state: Mapped[str | None] = mapped_column(String(2))
    industry: Mapped[str | None] = mapped_column(String(8))  # NAICS sector id, e.g. "31-33"
    employer_query: Mapped[str | None] = mapped_column(String(256))  # case-insensitive substring
    frequency: Mapped[str] = mapped_column(
        String(16), nullable=False, default="daily", server_default="daily"
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirm_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    unsubscribe_token: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    # Watermark: only notices with scraped_at after this are sent in the next digest.
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ScraperRun statuses that mean the run reached the source successfully
# (every consumer that gates on "ok" must accept both).
SCRAPER_SUCCESS_STATUSES = ("ok", "not_modified")


class ScraperRun(Base):
    __tablename__ = "scraper_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rows_scraped: Mapped[int | None] = mapped_column(Integer)
    rows_new: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # ok | not_modified | fetch_failed | parse_failed | validation_failed | storage_failed
    # not_modified is a success: the source was reachable but unchanged since the
    # last run (conditional GET), so parse/store were skipped (rows_scraped NULL).
    error: Mapped[str | None] = mapped_column(Text)
    snapshot_path: Mapped[str | None] = mapped_column(String(1024))


class SourceCache(Base):
    """HTTP validators per source-file URL, for conditional GETs.

    Written by ``warn_v2.scrapers.http_cache.conditional_get``. ``fetched_at``
    is the last time a full body was downloaded (NOT bumped on 304s — the
    staleness guard forces a periodic full download to distrust long 304
    streaks from broken servers). ``state`` lets the runner invalidate a
    state's rows when a run fails after fetch (content fetched ≠ ingested).
    """

    __tablename__ = "source_cache"

    url: Mapped[str] = mapped_column(String(1024), primary_key=True)
    state: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    etag: Mapped[str | None] = mapped_column(String(256))
    last_modified: Mapped[str | None] = mapped_column(String(128))  # raw header, echoed verbatim
    content_hash: Mapped[str | None] = mapped_column(String(64))  # sha256 hex of the body
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CrossCheckRun(Base):
    """One source-cross-check pass for a state: live page vs. stored notices.

    Written by ``warn-v2 cross-check`` (see scripts/cross_check.py). The counts
    are the alertable signal — sustained ``missing_from_db`` on a state means we
    stopped capturing rows the source still publishes. ``sample`` holds a small
    JSON slice of the drift rows for triage, not a full mirror.
    """

    __tablename__ = "cross_check_runs"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    state: Mapped[str] = mapped_column(String(2), nullable=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # ok | fetch_failed | parse_failed | empty | blocked
    live_rows: Mapped[int | None] = mapped_column(Integer)
    db_active: Mapped[int | None] = mapped_column(Integer)
    missing_from_db: Mapped[int | None] = mapped_column(Integer)
    extra_in_db: Mapped[int | None] = mapped_column(Integer)
    sample: Mapped[str | None] = mapped_column(Text)
