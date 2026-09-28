"""Tests for consolidate_companies (unique-id-first + name fallback + parent grouping)."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from warn_v2.db.models import Company, Notice
from warn_v2.pipeline.storage import _get_or_create_company
from warn_v2.scripts.consolidate_companies import consolidate_companies


def _company(db, name: str, **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def test_unique_id_merge(db) -> None:
    a = _company(db, "Acme Industries Inc", unique_id="111111111")
    b = _company(db, "Acme Industries LLC", unique_id="111111111")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 1
    assert res["unique_id_groups"] == 1
    db.expire_all()
    # lower id is the canonical survivor (no other tie-breaker here)
    assert db.get(Company, a.id).canonical_company_id is None
    assert db.get(Company, b.id).canonical_company_id == a.id


def test_name_fallback_merge_without_unique_id(db) -> None:
    a = _company(db, "Beta Co")
    b = _company(db, "Beta, LLC")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 1
    assert res["name_groups"] == 1
    db.expire_all()
    assert db.get(Company, b.id).canonical_company_id == a.id


def test_name_collision_different_unique_ids_not_merged(db) -> None:
    # Same normalized name but two distinct unique ids = different entities → keep apart.
    a = _company(db, "Summit Inc", unique_id="222222222")
    b = _company(db, "Summit LLC", unique_id="333333333")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 0
    db.expire_all()
    assert db.get(Company, a.id).canonical_company_id is None
    assert db.get(Company, b.id).canonical_company_id is None


def test_multi_unique_id_same_website_merges(db) -> None:
    # One company whose enrichment split across several unique ids, all at the same
    # site -> merge despite the multi-id guard (the Boeing case).
    a = _company(db, "Boeing", unique_id="100000001", website="http://www.boeing.com")
    b = _company(db, "Boeing Company", unique_id="100000002", website="https://boeing.com/careers")
    c = _company(db, "The Boeing Company", unique_id="100000003", website="www.boeing.com")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["website_groups"] == 1
    assert res["merged"] == 2  # two fold into one survivor
    db.expire_all()
    # lowest id wins with no other tie-breaker; the other two point at it
    assert db.get(Company, a.id).canonical_company_id is None
    assert db.get(Company, b.id).canonical_company_id == a.id
    assert db.get(Company, c.id).canonical_company_id == a.id


def test_website_merge_flattens_child_chains(db) -> None:
    # A hub that absorbed a Pass-1 unique-id child, then LOSES the website-path merge
    # to another hub, must not leave the grandchild in a 2-hop chain — every
    # member resolves to the single ultimate survivor.
    # hub_a wins (lowest id); child shares hub_b's unique id so Pass 1 puts it under
    # the losing hub_b.
    hub_a = _company(db, "Boeing", unique_id="500000001", website="http://www.boeing.com")
    hub_b = _company(db, "Boeing Company", unique_id="500000002", website="https://boeing.com")
    child = _company(db, "Boeing Field Office", unique_id="500000002")
    db.commit()

    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    surv = hub_a.id  # lowest id, no other tie-breaker
    assert db.get(Company, hub_a.id).canonical_company_id is None
    assert db.get(Company, hub_b.id).canonical_company_id == surv
    # the grandchild (child of the losing hub) points straight at the ultimate
    # survivor, not the intermediate losing hub
    assert db.get(Company, child.id).canonical_company_id == surv


def test_multi_unique_id_different_website_not_merged(db) -> None:
    # Same normalized name + different unique ids + DIFFERENT sites = genuinely
    # different companies -> keep apart.
    a = _company(db, "Summit Inc", unique_id="200000001", website="http://summit-a.com")
    b = _company(db, "Summit LLC", unique_id="200000002", website="http://summit-b.com")
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 0
    assert res["website_groups"] == 0
    db.expire_all()
    assert db.get(Company, a.id).canonical_company_id is None
    assert db.get(Company, b.id).canonical_company_id is None


def test_multi_unique_id_partial_website_rides_along(db) -> None:
    # An un-enriched (no-website) sibling doesn't block the merge; it rides along
    # on the shared name and the one known domain.
    a = _company(db, "Boeing", unique_id="400000001", website="http://www.boeing.com")
    b = _company(db, "Boeing Co", unique_id="400000002")  # no website
    db.commit()

    res = consolidate_companies(dry_run=False, force=True)
    assert res["merged"] == 1
    assert res["website_groups"] == 1
    db.expire_all()
    assert db.get(Company, b.id).canonical_company_id == a.id


def test_survivor_prefers_enriched(db) -> None:
    plain = _company(db, "Gamma Inc", unique_id="444444444")
    rich = _company(
        db, "Gamma LLC", unique_id="444444444",
        enriched_at=datetime.now(UTC), enrichment_confidence=Decimal("0.95"),
    )
    db.commit()

    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    # the enriched row wins even though it has the higher id
    assert db.get(Company, rich.id).canonical_company_id is None
    assert db.get(Company, plain.id).canonical_company_id == rich.id


def test_survivor_prefers_digit_free_name(db) -> None:
    # The Kmart case: same unique id, both enriched at the same confidence, and the
    # store-numbered row has more notices — the clean name still wins, since the
    # survivor's name is the label the whole group displays.
    enriched = {"enriched_at": datetime.now(UTC), "enrichment_confidence": Decimal("1.00")}
    store = _company(db, "KMART CORPORATION # 7435", unique_id="555555555", **enriched)
    clean = _company(db, "Kmart Corporation", unique_id="555555555", **enriched)
    for i in range(3):
        db.add(Notice(notice_id=f"km{i}", state="MI", employer=store.name, company_id=store.id))
    db.add(Notice(notice_id="km_clean", state="MI", employer=clean.name, company_id=clean.id))
    db.commit()

    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    assert db.get(Company, clean.id).canonical_company_id is None
    assert db.get(Company, store.id).canonical_company_id == clean.id


def test_parent_group_key_prefers_gu_id(db) -> None:
    # Two siblings of one ultimate share the global_ultimate_id -> same group key.
    a = _company(db, "Sub One", unique_id="555000001",
                 global_ultimate_id="uuid-mega", global_ultimate_unique_id="999000111")
    b = _company(db, "Sub Two", unique_id="555000002",
                 global_ultimate_id="uuid-mega", global_ultimate_name="Mega Corp")
    db.commit()
    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    assert db.get(Company, a.id).parent_group_key == "ult:uuid-mega"
    assert db.get(Company, b.id).parent_group_key == "ult:uuid-mega"


def test_parent_group_key_falls_back_to_gu_unique_id_then_name(db) -> None:
    c = _company(db, "Sub Co", unique_id="555555555",
                 global_ultimate_unique_id="999000111", global_ultimate_name="Mega Corp")
    d = _company(db, "Other Sub", unique_id="555555556", global_ultimate_name="Mega Corp")
    db.commit()
    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    assert db.get(Company, c.id).parent_group_key == "uid:999000111"
    assert db.get(Company, d.id).parent_group_key == "name:mega"  # 'corp' stripped


def test_parent_group_key_name_fallback(db) -> None:
    c = _company(db, "Orphan Inc")  # no unique_id, no parent
    db.commit()
    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    assert db.get(Company, c.id).parent_group_key == "self:orphan"


def test_dry_run_writes_nothing(db) -> None:
    _company(db, "Delta Inc", unique_id="666666666")
    b = _company(db, "Delta LLC", unique_id="666666666")
    db.commit()

    res = consolidate_companies(dry_run=True, force=True)
    assert res["merged"] == 1  # reported
    db.expire_all()
    assert db.get(Company, b.id).canonical_company_id is None  # but not written


def test_idempotent(db) -> None:
    _company(db, "Epsilon Inc", unique_id="777777777")
    _company(db, "Epsilon LLC", unique_id="777777777")
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
