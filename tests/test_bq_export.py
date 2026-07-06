"""BigQuery export: row shaping, enriched-only filter, DUNS exclusion, load guard."""
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from warn_v2.db.models import Company, Location, Notice
from warn_v2.scripts import bq_export

SCHEMA_NAMES = [name for name, _, _ in bq_export.SCHEMA_SPEC]


def _company(db, name="Acme Inc", enriched=True, **kw) -> Company:
    c = Company(
        name=name,
        enriched_at=datetime.now(UTC) if enriched else None,
        **kw,
    )
    db.add(c)
    db.flush()
    return c


def _notice(db, company: Company | None, notice_id: str, location: Location | None = None,
            **kw) -> Notice:
    n = Notice(
        notice_id=notice_id,
        state=kw.pop("state", "CA"),
        employer=kw.pop("employer", company.name if company else "Nobody Inc"),
        company_id=company.id if company else None,
        location_id=location.id if location else None,
        **kw,
    )
    db.add(n)
    db.flush()
    return n


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------

def test_only_enriched_company_notices_export(db):
    enriched = _company(db, "Enriched Co")
    bare = _company(db, "Bare Co", enriched=False)
    _notice(db, enriched, "n_enriched")
    _notice(db, bare, "n_bare")
    _notice(db, None, "n_orphan")  # no company at all
    db.commit()

    rows = bq_export.fetch_export_rows(db)
    assert [r["notice_id"] for r in rows] == ["n_enriched"]


def test_merged_duplicate_exports_canonical_attributes(db):
    canonical = _company(db, "Canonical Co", naics_code="3361", naics_desc="Motor Vehicles",
                         parent_company_name="Parent Holdings")
    dup = _company(db, "Canonical Co LLC", enriched=False)
    dup.canonical_company_id = canonical.id
    _notice(db, dup, "n_dup")
    db.commit()

    rows = bq_export.fetch_export_rows(db)
    assert len(rows) == 1  # dup's canonical is enriched, so it qualifies
    assert rows[0]["company_name"] == "Canonical Co"
    assert rows[0]["naics_code"] == "3361"
    assert rows[0]["parent_company_name"] == "Parent Holdings"


def test_superseded_rows_included_and_flagged(db):
    c = _company(db)
    _notice(db, c, "n_live")
    sup = _notice(db, c, "n_old")
    sup.is_superseded = True
    db.commit()

    rows = {r["notice_id"]: r for r in bq_export.fetch_export_rows(db)}
    assert rows["n_live"]["is_superseded"] is False
    assert rows["n_old"]["is_superseded"] is True


def test_row_shape_matches_schema_and_coerces_scalars(db):
    loc = Location(city="Oakland", county="Alameda", state="CA", zip="94607",
                   lat=Decimal("37.804400"), lon=Decimal("-122.271100"),
                   geocode_source="census")
    db.add(loc)
    db.flush()
    c = _company(db, naics_code="3361", enrichment_confidence=Decimal("0.95"),
                 employee_count=500)
    _notice(db, c, "n_1", location=loc, notice_date=date(2026, 1, 15),
            effective_date=date(2026, 3, 15), layoff_count=250)
    db.commit()

    row = bq_export.fetch_export_rows(db)[0]
    assert sorted(row) == sorted(SCHEMA_NAMES)  # keys == schema, exactly
    assert row["notice_date"] == "2026-01-15"  # date -> ISO string
    assert row["lat"] == pytest.approx(37.8044)  # Decimal -> float
    assert isinstance(row["enrichment_confidence"], float)
    assert row["scraped_at"].startswith("20")  # datetime -> ISO string
    assert row["exported_at"] == row["exported_at"]  # present on every row


def test_no_duns_anywhere():
    for name in [*SCHEMA_NAMES, bq_export.SNAPSHOT_EXTRA[0]]:
        assert "duns" not in name.lower()


def test_schema_has_descriptions():
    for name, _type, desc in bq_export.SCHEMA_SPEC:
        assert desc, f"schema field {name} is missing a description"


# ---------------------------------------------------------------------------
# Loader (mocked client)
# ---------------------------------------------------------------------------

def _fake_client(existing_rows: int | None = 100):
    client = MagicMock()
    if existing_rows is None:
        from google.api_core.exceptions import NotFound

        client.get_table.side_effect = NotFound("no table")
    else:
        client.get_table.return_value = MagicMock(num_rows=existing_rows)
    return client


def _rows(n: int) -> list[dict]:
    return [{"notice_id": f"n{i}", "is_superseded": False} for i in range(n)]


def test_load_truncates_notices_and_snapshot_partition():
    client = _fake_client(existing_rows=100)
    bq_export.load_to_bigquery(_rows(100), "proj", "ds", client=client)

    targets = [call.args[1] for call in client.load_table_from_json.call_args_list]
    assert targets[0] == "proj.ds.notices"
    today = datetime.now(UTC).date()
    assert targets[1] == f"proj.ds.notices_snapshots${today:%Y%m%d}"

    for call in client.load_table_from_json.call_args_list:
        assert call.kwargs["job_config"].write_disposition == "WRITE_TRUNCATE"

    # Snapshot rows carry snapshot_date; the base rows don't.
    base_rows = client.load_table_from_json.call_args_list[0].args[0]
    snap_rows = client.load_table_from_json.call_args_list[1].args[0]
    assert "snapshot_date" not in base_rows[0]
    assert snap_rows[0]["snapshot_date"] == today.isoformat()

    # The active view is ensured.
    assert "notices_active" in client.query.call_args.args[0]


def test_load_snapshot_optional():
    client = _fake_client()
    bq_export.load_to_bigquery(_rows(100), "proj", "ds", snapshot=False, client=client)
    assert client.load_table_from_json.call_count == 1


def test_shrink_guard_refuses_partial_load():
    client = _fake_client(existing_rows=100)
    with pytest.raises(RuntimeError, match="refusing to truncate"):
        bq_export.load_to_bigquery(_rows(50), "proj", "ds", client=client)
    client.load_table_from_json.assert_not_called()


def test_shrink_guard_allows_first_load_and_growth():
    bq_export.load_to_bigquery(_rows(10), "proj", "ds", client=_fake_client(existing_rows=None))
    bq_export.load_to_bigquery(_rows(150), "proj", "ds", client=_fake_client(existing_rows=100))
