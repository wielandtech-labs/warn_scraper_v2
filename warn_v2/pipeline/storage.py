"""Upsert NoticeRows into Postgres."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from warn_v2.closure import normalize_closure_category
from warn_v2.companies.normalize import canonical_name
from warn_v2.db.models import Company, Location, Notice
from warn_v2.geo.geocoder import geocode as _geocode
from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers._helpers import norm
from warn_v2.scrapers.base import NoticeRow

# First non-null wins: once set, don't overwrite (geocoded location, address, type).
_FILL_IN_FIELDS: tuple[str, ...] = (
    "address",
    "closure_type",
    "closure_category",
    "location_id",
)

# Last non-null wins: amendments may update these fields, so prefer incoming value.
_UPDATE_FIELDS: tuple[str, ...] = ("layoff_count", "effective_date", "raw_notice_url")

# Single-locality jurisdictions: the source publishes no worksite city/ZIP, but
# every notice is in one place by definition (DC = the District of Columbia).
# Default the *location* city so these geocode at city level — same spirit as the
# KY/MT county-centroid fallback. Applied only inside location creation, so it
# never touches notice_id (hashed from the original row before location lookup).
_DEFAULT_CITY: dict[str, str] = {"DC": "Washington"}

# A NAICS code is 2-6 digits (column allows 8).
_NAICS_RE = re.compile(r"\b\d{2,8}\b")


def _derive_location_city(row: NoticeRow) -> str | None:
    """Best-effort worksite city when the source row carries none.

    Used only when a row has no city/zip/county. Derives a city for the Location
    without touching the (already-computed) notice_id, so existing rows fill in
    location_id on the next scrape via the COALESCE path — no re-key, no churn.

    - DC: every notice is in the District -> Washington.
    - MN: the 2025 wide-format report concatenates the City column into the
      employer string ("Upsher-Smith 2025 Maple Grove Manufacturing"); recover it
      (see scrapers/mn_city). Out-of-state HQ cities the source sometimes lists
      (Bentonville, San Francisco) return None and stay un-geocoded — correct.
    """
    state = row.state.upper()
    if state in _DEFAULT_CITY:
        return _DEFAULT_CITY[state]
    if state == "MN":
        from warn_v2.scrapers.mn_city import split_city_from_label
        return split_city_from_label(row.employer)
    return None


def _merge_worksite_rows(rows: Iterable[NoticeRow]) -> list[NoticeRow]:
    """Collapse rows sharing a ``notice_id`` into one, summing distinct worksites.

    Sources like CA EDD publish one row per *worksite*: a single notice can list
    several sites for the same employer/date/city/zip, differing only by street
    address (e.g. Intel's four Santa Clara campuses). ``notice_id`` excludes the
    address, so those rows collapse to one — and the plain upsert would keep only
    the last worksite's ``layoff_count``, discarding the rest and badly
    under-counting affected workers (and manufacturing spurious count==1 rows).

    For each ``notice_id`` group we first drop exact-worksite duplicates (same
    normalized address) so a true duplicate row is never double-counted, then sum
    ``layoff_count`` across the remaining distinct addresses. The first row of the
    group represents the merged notice, carrying the summed count (left ``None``
    only when every row's count was ``None`` — never coerced to 0).

    Idempotent: a re-scrape reads the whole source file, so the group and its sum
    are identical, and the upsert *replaces* the stored count rather than
    accumulating. Groups with a single row are returned unchanged.

    Known limit: rows with no address can't be told apart, so distinct same-city
    worksites in address-less sources still collapse to one.
    """
    groups: dict[str, list[NoticeRow]] = {}
    for row in rows:
        groups.setdefault(notice_id(row), []).append(row)

    merged: list[NoticeRow] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        seen_addresses: set[str] = set()
        total: int | None = None
        for row in group:
            addr = norm(row.address or "")
            if addr and addr in seen_addresses:
                continue  # exact-worksite duplicate — count it once
            seen_addresses.add(addr)
            if row.layoff_count is not None:
                total = (total or 0) + row.layoff_count
        merged.append(replace(group[0], layoff_count=total))
    return merged


def upsert_notices(session: Session, rows: Iterable[NoticeRow]) -> tuple[int, int]:
    """Insert new notices; fill in nullable fields on existing rows.

    Returns ``(rows_seen, rows_new)``.  A notice is "new" iff its content-hash
    ``notice_id`` was absent before this call — re-upserts that only fill in
    previously-NULL fields don't bump the counter.

    On Postgres uses ``ON CONFLICT DO UPDATE`` with COALESCE semantics so that
    a re-scrape can backfill (e.g.) a newly-extracted ``address`` without
    overwriting any field the existing row already had.  On SQLite (used by
    tests) the same contract is implemented via SELECT-then-INSERT / fill-in.
    """
    seen = 0
    new = 0
    dialect = session.bind.dialect.name if session.bind is not None else ""
    now = datetime.now(UTC)

    # Collapse per-worksite rows that share a notice_id into one notice, summing
    # their distinct-address layoff counts (see _merge_worksite_rows).
    rows = _merge_worksite_rows(rows)

    for row in rows:
        seen += 1
        nid = notice_id(row)
        company = _get_or_create_company(session, row.employer, row.naics_code)
        location = _get_or_create_location(session, row)

        payload = {
            "notice_id": nid,
            "state": row.state.upper(),
            "employer": row.employer,
            "notice_date": row.notice_date,
            "effective_date": row.effective_date,
            "layoff_count": row.layoff_count,
            "closure_type": row.closure_type,
            "closure_category": normalize_closure_category(row.closure_type),
            "address": row.address,
            "source_url": row.source_url,
            "raw_notice_url": row.raw_notice_url,
            "scraped_at": now,
            "company_id": company.id,
            "location_id": location.id if location else None,
        }

        # Pre-check to distinguish insert vs. fill-in update.  PG's
        # ON CONFLICT DO UPDATE returns rowcount=1 for both paths, so we
        # can't rely on it for the rows_new counter.
        existing = session.get(Notice, nid)

        # A WARN notice cannot be filed in the future.  Some sources (e.g. MI)
        # publish only the layoff/effective date, which we also store in
        # notice_date; that date is typically months ahead.  On first insert,
        # treat the scrape date as the notice (first-seen) date and preserve the
        # forward-looking date as effective_date.  `nid` was computed from the
        # original row above, so re-scrapes still map to this same row — the
        # stored notice_date diverging from the hashed value does NOT cause
        # duplicate churn.  Runs before the 60-day fallback so MI (which already
        # carries effective_date == layoff date) keeps its real layoff date.
        if (
            existing is None
            and payload["notice_date"] is not None
            and payload["notice_date"] > now.date()
        ):
            if payload["effective_date"] is None:
                payload["effective_date"] = payload["notice_date"]
            payload["notice_date"] = now.date()

        # Apply 60-day WARN Act fallback for effective_date on new inserts only.
        # We deliberately do NOT apply it on re-upserts so that a real
        # source-provided date stored from a previous scrape is never overwritten
        # by our estimate.  Amendments that supply a new non-null date still win
        # via _UPDATE_FIELDS ("last non-null wins").
        if existing is None and payload["effective_date"] is None and row.notice_date is not None:
            payload["effective_date"] = row.notice_date + timedelta(days=60)

        if dialect == "postgresql":
            stmt = pg_insert(Notice).values(**payload)
            set_ = {
                f: func.coalesce(getattr(Notice, f), getattr(stmt.excluded, f))
                for f in _FILL_IN_FIELDS
            }
            set_.update({
                f: func.coalesce(getattr(stmt.excluded, f), getattr(Notice, f))
                for f in _UPDATE_FIELDS
            })
            stmt = stmt.on_conflict_do_update(
                index_elements=["notice_id"],
                set_=set_,
            )
            session.execute(stmt)
            if existing is None:
                new += 1
        else:
            if existing is None:
                session.add(Notice(**payload))
                new += 1
            else:
                for field in _FILL_IN_FIELDS:
                    if getattr(existing, field) is None:
                        new_val = payload.get(field)
                        if new_val is not None:
                            setattr(existing, field, new_val)
                for field in _UPDATE_FIELDS:
                    new_val = payload.get(field)
                    if new_val is not None:
                        setattr(existing, field, new_val)

    session.flush()
    return seen, new


def _clean_naics(naics_code: str | None) -> str | None:
    """First valid NAICS digit-code from a source cell, or None.

    Source cells sometimes hold several whitespace-separated codes
    ("423990             321918") that overflow companies.naics_code
    VARCHAR(8) and abort the whole upsert batch.
    """
    if not naics_code:
        return None
    m = _NAICS_RE.search(naics_code)
    return m.group(0) if m else None


def _get_or_create_company(
    session: Session, name: str, naics_code: str | None = None
) -> Company:
    naics_code = _clean_naics(naics_code)
    # Match on the normalized name so legal-form variants ("Acme Inc" / "Acme,
    # LLC" / "ACME") attach to one row instead of spawning duplicates. If the
    # match was already consolidated into a canonical row, attach to that
    # canonical so new notices accrue to the survivor.
    normalized = canonical_name(name)
    company = session.execute(
        select(Company).where(Company.name_normalized == normalized).limit(1)
    ).scalar_one_or_none()
    if company is None:
        # Backstop for rows predating name_normalized backfill.
        company = session.execute(
            select(Company).where(Company.name == name).limit(1)
        ).scalar_one_or_none()

    if company is None:
        company = Company(name=name, name_normalized=normalized, naics_code=naics_code)
        session.add(company)
        session.flush()
        return company

    if company.canonical_company_id is not None:
        canonical = session.get(Company, company.canonical_company_id)
        if canonical is not None:
            company = canonical
    if not company.name_normalized:
        company.name_normalized = normalized
    if naics_code and not company.naics_code:
        # First non-null wins: fill in a missing NAICS from the WARN filing.
        # An existing enrichment-provided code is preserved.
        company.naics_code = naics_code
    return company


def enrich_notice_location(
    session: Session,
    notice,
    city: str | None,
    zip_: str | None,
    address: str | None,
) -> bool:
    """Create or upgrade the location for a notice using PDF-extracted data.

    Fill-in: if the notice has no location and city/zip are available, create/find one.
    Promote: if the notice has a zip-less location and zip is now known, promote in place.
    Returns True if any location change was made.
    """
    if not city and not zip_:
        return False

    existing_loc = notice.location
    if existing_loc is None:
        partial = NoticeRow(
            state=notice.state,
            employer=notice.employer or "",
            city=city,
            zip=zip_,
            address=address,
        )
        loc = _get_or_create_location(session, partial)
        if loc and loc.id != notice.location_id:
            # Set the relationship (not just the FK) so a later read of
            # notice.location in the same unit of work sees it — e.g. the GA
            # enricher attaches the page County, and may call this again for the
            # page ZIP, right after minting this location from a Word attachment.
            notice.location = loc
            session.flush()
            return True
    elif not existing_loc.zip and zip_:
        # A different location may already hold (state, city, zip); promoting in
        # place would violate uq_locations_state_city_zip (prod: two CT "Conduent
        # (Remote)" notices both resolving to CT/Remote/06109). Rebind to the
        # existing twin rather than colliding.
        twin = session.execute(
            select(Location).where(
                Location.state == existing_loc.state,
                Location.city == existing_loc.city,
                Location.zip == zip_,
            ).limit(1)
        ).scalar_one_or_none()
        if twin is not None and twin.id != existing_loc.id:
            notice.location = twin
            session.flush()
            return True
        existing_loc.zip = zip_
        # Re-geocode with the now-known zip
        from warn_v2.geo.geocoder import geocode as _geocode
        if existing_loc.lat is None:
            result = _geocode(address, existing_loc.city, notice.state, zip_, existing_loc.county)
            if result is not None:
                existing_loc.lat, existing_loc.lon, existing_loc.geocode_source = result
        session.flush()
        return True
    return False


def _zip_is_missing(col):
    """Filter expression matching a Location row with no usable ZIP."""
    return or_(col.is_(None), col == "")


def _get_or_create_location(session: Session, row: NoticeRow) -> Location | None:
    """Find or create the Location for this notice row.

    Backfill rule: when the row carries a non-empty zip but no exact match
    exists, and there's exactly one zip-less candidate for the same
    (state, city), update *that* row's zip in place rather than inserting a
    new one.  This preserves FKs from historical notices that were ingested
    before the scraper knew how to extract a ZIP.

    County-only path: states like KY and MT report only a county name (no
    city, no ZIP).  These notices get a Location keyed on (state, county)
    with county-centroid coordinates as a best-effort lat/lon.

    Derived-city fallback: for sources that publish no worksite locality but where
    a city is implied (DC → Washington) or recoverable (MN's wide-format report
    concatenates the City column into the employer string), derive it via
    ``_derive_location_city`` so the notice geocodes at city level. This rebinds the
    local ``row`` only; ``notice_id`` was already hashed from the original row by the
    caller, so existing rows keep their id (no re-key / churn) and get the location
    filled in on the next scrape via the COALESCE path.
    """
    if not row.city and not row.zip and not row.county:
        derived_city = _derive_location_city(row)
        if derived_city:
            row = replace(row, city=derived_city)

    if not row.city and not row.zip and not row.county:
        return None

    # County-only path: no city, no zip — only county is known.
    if not row.city and not row.zip and row.county:
        state = row.state.upper()
        existing = session.execute(
            select(Location).where(
                Location.state == state,
                Location.city.is_(None),
                Location.county == row.county,
            ).limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.lat is None and existing.lon is None:
                result = _geocode(None, None, state, None, row.county)
                if result is not None:
                    existing.lat, existing.lon, existing.geocode_source = result
            return existing
        lat, lon, geocode_source = (None, None, None)
        result = _geocode(None, None, state, None, row.county)
        if result is not None:
            lat, lon, geocode_source = result
        loc = Location(
            state=state, county=row.county,
            lat=lat, lon=lon, geocode_source=geocode_source,
        )
        session.add(loc)
        session.flush()
        return loc
    state = row.state.upper()
    incoming_zip = row.zip or None  # normalize empty string → None

    # 1. exact match on (state, city, zip).  NULL == NULL is not true in SQL,
    # so branch on whether the row carries a zip.
    if incoming_zip:
        zip_filter = Location.zip == incoming_zip
    else:
        zip_filter = _zip_is_missing(Location.zip)
    exact = session.execute(
        select(Location).where(
            Location.state == state,
            Location.city == row.city,
            zip_filter,
        ).limit(1)
    ).scalar_one_or_none()
    if exact is not None:
        if row.county and not exact.county:
            exact.county = row.county
        # Backfill lat/lon if missing — try address first, ZIP centroid fallback.
        if exact.lat is None and exact.lon is None:
            result = _geocode(row.address, row.city, row.state, exact.zip, row.county)
            if result is not None:
                exact.lat, exact.lon, exact.geocode_source = result
        return exact

    # 2. promote a single zip-less candidate in place
    if incoming_zip:
        zipless = session.execute(
            select(Location).where(
                Location.state == state,
                Location.city == row.city,
                _zip_is_missing(Location.zip),
            )
        ).scalars().all()
        if len(zipless) == 1:
            loc = zipless[0]
            loc.zip = incoming_zip
            if row.county and not loc.county:
                loc.county = row.county
            if loc.lat is None and loc.lon is None:
                result = _geocode(row.address, row.city, row.state, incoming_zip, row.county)
                if result is not None:
                    loc.lat, loc.lon, loc.geocode_source = result
            session.flush()
            return loc

    # 3. fall through to insert
    lat, lon, geocode_source = (None, None, None)
    result = _geocode(row.address, row.city, row.state, incoming_zip, row.county)
    if result is not None:
        lat, lon, geocode_source = result
    loc = Location(
        state=state,
        city=row.city,
        county=row.county,
        zip=incoming_zip,
        lat=lat,
        lon=lon,
        geocode_source=geocode_source,
    )
    session.add(loc)
    session.flush()
    return loc
