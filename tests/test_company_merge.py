"""Admin merge overrides: the resolver and its use by the nightly consolidator."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from warn_v2.companies.merge import apply_overrides, flatten
from warn_v2.db.models import Company, CompanyMergeOverride
from warn_v2.scripts.consolidate_companies import consolidate_companies

# --- apply_overrides / flatten (pure) ---------------------------------------


def test_override_merges_row():
    assert apply_overrides({}, [(2, 1)]) == {2: 1}


def test_unmerge_override_removes_auto_merge():
    assert apply_overrides({2: 1, 3: 1}, [(2, None)]) == {3: 1}


def test_merge_into_row_that_sits_under_the_source_promotes_the_target():
    # consolidator put clean "Kmart Corporation" (1) under store row (9); the admin
    # merges 9 into 1 -> 1 becomes the root, 9 and 9's other children follow.
    out = flatten(apply_overrides({1: 9, 5: 9}, [(9, 1)]))
    assert out == {9: 1, 5: 1}


def test_merge_into_auto_merged_row_resolves_to_its_root():
    out = flatten(apply_overrides({1: 7}, [(2, 1)]))
    assert out == {1: 7, 2: 7}


def test_newer_override_wins_a_cycle():
    # newest first: 1 -> 2 is newer, so the older 2 -> 1 is skipped.
    assert flatten(apply_overrides({}, [(1, 2), (2, 1)])) == {1: 2}


def test_self_merge_is_ignored():
    assert apply_overrides({}, [(3, 3)]) == {}


# --- consolidator integration -------------------------------------------------


def _company(db, name: str, **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def _override(db, src: Company, tgt: Company | None, age_s: int = 0) -> None:
    db.add(CompanyMergeOverride(
        company_id=src.id,
        target_company_id=tgt.id if tgt else None,
        decided_at=datetime.now(UTC) - timedelta(seconds=age_s),
    ))


def test_manual_merge_survives_consolidator_run(db):
    # Store-numbered names that no heuristic would merge.
    target = _company(db, "Kmart Corporation")
    store = _company(db, "Kmart -- Store # 3461 -- Winter Haven")
    _override(db, store, target)
    db.commit()

    res = consolidate_companies(dry_run=False, force=False)
    assert res["overrides"] == 1
    db.expire_all()
    assert db.get(Company, store.id).canonical_company_id == target.id
    assert db.get(Company, target.id).canonical_company_id is None


def test_unmerge_override_beats_duns_merge(db):
    a = _company(db, "Acme Inc", duns="111111111")
    b = _company(db, "Acme Retail Stores", duns="111111111")
    _override(db, b, None)
    db.commit()

    consolidate_companies(dry_run=False, force=True)
    db.expire_all()
    assert db.get(Company, a.id).canonical_company_id is None
    assert db.get(Company, b.id).canonical_company_id is None


def test_manual_merges_do_not_count_toward_guardrail(db):
    # 1 target + 3 manual sources = 75% merged, but none by heuristics.
    target = _company(db, "Kmart Corporation")
    for i in range(3):
        _override(db, _company(db, f"Kmart Store #{i}0{i}"), target)
    db.commit()

    res = consolidate_companies(dry_run=False, force=False)
    assert not res.get("aborted")
    assert res["merged"] == 3
