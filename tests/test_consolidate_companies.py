"""Tests for consolidate_companies (DUNS-first + name fallback + parent grouping)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from warn_v2.db.models import Company
from warn_v2.pipeline.storage import _get_or_create_company
from warn_v2.scripts.consolidate_companies import consolidate_companies


def _company(db, name: str, **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def test_duns_merge(db) -> None:
    a = _company(db, "Acme Industries Inc", duns="111111111")
    b = _company(db, "Acme Industries LLC", duns="111111111")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 1
    assert res["duns_groups"] == 1
    db.expire_all()
    # lower id is the canonical survivor (no other tie-breaker here)
    assert db.get(Company, a.id).canonical_company_id is None
    assert db.get(Company, b.id).canonical_company_id == a.id


def test_name_fallback_merge_without_duns(db) -> None:
    a = _company(db, "Beta Co")
    b = _company(db, "Beta, LLC")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 1
    assert res["name_groups"] == 1
    db.expire_all()
    assert db.get(Company, b.id).canonical_company_id == a.id


def test_name_collision_different_duns_not_merged(db) -> None:
    # Same normalized name but two distinct DUNS = different entities → keep apart.
    a = _company(db, "Summit Inc", duns="222222222")
    b = _company(db, "Summit LLC", duns="333333333")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 0
    db.expire_all()
    assert db.get(Company, a.id).canonical_company_id is None
    assert db.get(Company, b.id).canonical_company_id is None


def test_survivor_prefers_enriched(db) -> None:
    plain = _company(db, "Gamma Inc", duns="444444444")
    rich = _company(
        db, "Gamma LLC", duns="444444444",
        enriched_at=datetime.now(UTC), enrichment_confidence=Decimal("0.95"),
    )
    db.commit()

    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    # the enriched row wins even though it has the higher id
    assert db.get(Company, rich.id).canonical_company_id is None
    assert db.get(Company, plain.id).canonical_company_id == rich.id


def test_parent_group_key_prefers_gu_duns(db) -> None:
    c = _company(db, "Sub Co", duns="555555555",
                 global_ultimate_duns="999000111", global_ultimate_name="Mega Corp")
    db.commit()
    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    assert db.get(Company, c.id).parent_group_key == "duns:999000111"


def test_parent_group_key_name_fallback(db) -> None:
    c = _company(db, "Orphan Inc")  # no duns, no parent
    db.commit()
    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    assert db.get(Company, c.id).parent_group_key == "self:orphan"


def test_dry_run_writes_nothing(db) -> None:
    _company(db, "Delta Inc", duns="666666666")
    b = _company(db, "Delta LLC", duns="666666666")
    db.commit()

    res = consolidate_companies(dry_run=True, force=True)
    assert res["merged"] == 1  # reported
    db.expire_all()
    assert db.get(Company, b.id).canonical_company_id is None  # but not written


def test_idempotent(db) -> None:
    _company(db, "Epsilon Inc", duns="777777777")
    _company(db, "Epsilon LLC", duns="777777777")
    db.commit()

    first = consolidate_companies(dry_run=False, force=True)
    second = consolidate_companies(dry_run=False, force=True)
    assert first["merged"] == 1
    assert second["merged"] == 1  # stable, not double-counted or undone


# --- forward prevention in _get_or_create_company --------------------------

def test_get_or_create_matches_normalized_variant(db) -> None:
    first = _get_or_create_company(db, "Zeta Industries Inc")
    db.flush()
    second = _get_or_create_company(db, "Zeta Industries, LLC")
    assert second.id == first.id  # variant attaches to the same row, no duplicate


def test_get_or_create_resolves_to_canonical(db) -> None:
    canon = _company(db, "Theta Corp")
    canon.name_normalized = "theta"
    dupe = _company(db, "Theta LLC")
    dupe.name_normalized = "theta"
    dupe.canonical_company_id = canon.id
    db.flush()

    got = _get_or_create_company(db, "Theta LLC")
    assert got.id == canon.id  # new notices accrue to the canonical survivor
