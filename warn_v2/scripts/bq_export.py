"""Publish the WARN dataset to BigQuery (Analytics Hub listing).

Daily full refresh: at ~5k enriched notices a WRITE_TRUNCATE load costs
seconds and is trivially idempotent, so there is no CDC/merge logic. Two
tables:

- ``notices``            — current state, one denormalized row per notice
                           (notice + worksite location + canonical company),
                           month-partitioned on notice_date.
- ``notices_snapshots``  — the same rows appended daily under snapshot_date
                           (partition-decorator load, so re-runs replace the
                           day, never duplicate it). Point-in-time correctness
                           for alt-data consumers: amendments rewrite
                           ``notices``, but never history.

Only notices whose CANONICAL company is enriched are exported — the fully
attributed slice is the product; coverage grows as enrichment does.

Raw DUNS identifiers are never exported: the column list below is the single
source of truth and tests assert nothing duns-shaped appears in it.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from warn_v2.db.models import Company, Location, Notice

DEFAULT_DATASET = "warn_notices"
# Refuse a truncate-load that would shrink the public table by more than this
# (protects the listing from a partial Postgres read clobbering it).
SHRINK_GUARD = 0.9

# (name, bq_type, description) — converted to SchemaFields in the loader so the
# module stays importable (and unit-testable) without heavy client imports.
SCHEMA_SPEC: list[tuple[str, str, str]] = [
    ("notice_id", "STRING",
     "Stable content-hash id (state|employer|notice_date|city|zip). Survives refreshes; "
     "join key across snapshots."),
    ("state", "STRING", "Two-letter filing jurisdiction."),
    ("employer", "STRING", "Employer name as published by the state."),
    ("notice_date", "DATE", "Date the notice was filed/published."),
    ("effective_date", "DATE",
     "Layoff/closure effective date (60-day WARN default when the source omits it)."),
    ("layoff_count", "INTEGER", "Workers affected; summed across worksites of one filing."),
    ("closure_type", "STRING", "Raw source wording (e.g. 'Layoff Permanent')."),
    ("closure_category", "STRING", "Normalized bucket: 'Closure' | 'Layoff' | NULL."),
    ("address", "STRING", "Worksite street address as filed."),
    ("city", "STRING", "Worksite city."),
    ("county", "STRING", "Worksite county."),
    ("zip", "STRING", "Worksite ZIP code."),
    ("lat", "FLOAT", "Worksite latitude (see geocode_source for precision)."),
    ("lon", "FLOAT", "Worksite longitude."),
    ("geocode_source", "STRING",
     "Geocoding precision tier: census (street) > zip > city > county."),
    ("company_name", "STRING", "Canonical (deduplicated) company name."),
    ("naics_code", "STRING", "NAICS industry code of the canonical company."),
    ("naics_desc", "STRING", "NAICS industry description."),
    ("sic_code", "STRING", "SIC industry code."),
    ("sic_desc", "STRING", "SIC industry description."),
    ("company_website", "STRING", "Company website."),
    ("employee_count", "INTEGER", "Company total employee count (enrichment)."),
    ("parent_company_name", "STRING", "Direct parent company name, when known."),
    ("global_ultimate_name", "STRING", "Top of the corporate tree, when known."),
    ("enrichment_source", "STRING",
     "Primary source of the company attributes: provider | edgar | claude."),
    ("enrichment_confidence", "FLOAT", "Company match confidence, 0-1."),
    ("source_url", "STRING", "State listing page the notice was scraped from."),
    ("raw_notice_url", "STRING", "Detail page or PDF for this notice (may rot)."),
    ("is_superseded", "BOOLEAN",
     "True when a later amendment/duplicate replaces this row; kept for auditability. "
     "Use the notices_active view for the clean cut."),
    ("scraped_at", "TIMESTAMP", "When this notice was first seen by the scraper (UTC)."),
    ("exported_at", "TIMESTAMP", "When this export run started (UTC)."),
]

SNAPSHOT_EXTRA = ("snapshot_date", "DATE", "UTC date of the daily export run.")


def _coerce(v: object) -> object:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def fetch_export_rows(db: Session, exported_at: datetime | None = None) -> list[dict]:
    """Shape the export: denormalized notice rows, enriched canonical companies only."""
    exported_at = exported_at or datetime.now(UTC)
    canon = aliased(Company)
    stmt = (
        select(Notice, Location, canon)
        .join(Company, Company.id == Notice.company_id)
        # One consolidation hop: a merged duplicate exports its canonical
        # row's attributes, mirroring the website's dedup semantics.
        .join(canon, canon.id == func.coalesce(Company.canonical_company_id, Company.id))
        .outerjoin(Location, Location.id == Notice.location_id)
        .where(canon.enriched_at.is_not(None))
        .order_by(Notice.notice_date, Notice.notice_id)
    )
    rows = []
    for n, loc, c in db.execute(stmt):
        rows.append({
            "notice_id": n.notice_id,
            "state": n.state,
            "employer": n.employer,
            "notice_date": _coerce(n.notice_date),
            "effective_date": _coerce(n.effective_date),
            "layoff_count": n.layoff_count,
            "closure_type": n.closure_type,
            "closure_category": n.closure_category,
            "address": n.address,
            "city": loc.city if loc else None,
            "county": loc.county if loc else None,
            "zip": loc.zip if loc else None,
            "lat": _coerce(loc.lat) if loc else None,
            "lon": _coerce(loc.lon) if loc else None,
            "geocode_source": loc.geocode_source if loc else None,
            "company_name": c.name,
            "naics_code": c.naics_code,
            "naics_desc": c.naics_desc,
            "sic_code": c.sic_code,
            "sic_desc": c.sic_desc,
            "company_website": c.website,
            "employee_count": c.employee_count,
            "parent_company_name": c.parent_company_name,
            "global_ultimate_name": c.global_ultimate_name,
            "enrichment_source": c.enrichment_source,
            "enrichment_confidence": _coerce(c.enrichment_confidence),
            "source_url": n.source_url,
            "raw_notice_url": n.raw_notice_url,
            "is_superseded": n.is_superseded,
            "scraped_at": _coerce(n.scraped_at),
            "exported_at": _coerce(exported_at),
        })
    return rows


def _schema_fields(spec: list[tuple[str, str, str]]):
    from google.cloud import bigquery

    return [bigquery.SchemaField(name, type_, description=desc) for name, type_, desc in spec]


def _current_row_count(client, table_id: str) -> int:
    from google.api_core.exceptions import NotFound

    try:
        return int(client.get_table(table_id).num_rows)
    except NotFound:
        return 0


def load_to_bigquery(
    rows: list[dict],
    project: str,
    dataset: str = DEFAULT_DATASET,
    *,
    snapshot: bool = True,
    client=None,
) -> None:
    """Truncate-load ``notices`` (+ today's snapshot partition) and ensure the view."""
    from google.cloud import bigquery

    if client is None:
        client = bigquery.Client(project=project)

    notices_id = f"{project}.{dataset}.notices"
    current = _current_row_count(client, notices_id)
    if current and len(rows) < SHRINK_GUARD * current:
        raise RuntimeError(
            f"refusing to truncate {notices_id}: new row count {len(rows)} is below "
            f"{SHRINK_GUARD:.0%} of the current {current} — partial source read?"
        )

    job_config = bigquery.LoadJobConfig(
        schema=_schema_fields(SCHEMA_SPEC),
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.MONTH, field="notice_date"
        ),
        clustering_fields=["state", "naics_code"],
    )
    client.load_table_from_json(rows, notices_id, job_config=job_config).result()

    if snapshot:
        today = datetime.now(UTC).date()
        snap_rows = [{**r, "snapshot_date": today.isoformat()} for r in rows]
        snap_config = bigquery.LoadJobConfig(
            schema=_schema_fields([SNAPSHOT_EXTRA, *SCHEMA_SPEC]),
            # Decorator target replaces only today's partition — re-runs are
            # idempotent, history is append-only.
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            time_partitioning=bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY, field="snapshot_date"
            ),
        )
        snap_id = f"{project}.{dataset}.notices_snapshots${today:%Y%m%d}"
        client.load_table_from_json(snap_rows, snap_id, job_config=snap_config).result()

    client.query(
        f"CREATE VIEW IF NOT EXISTS `{project}.{dataset}.notices_active` AS "
        f"SELECT * FROM `{notices_id}` WHERE NOT is_superseded"
    ).result()
