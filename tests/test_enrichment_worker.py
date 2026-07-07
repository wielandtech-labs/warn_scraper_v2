"""DB integration tests for the enrichment worker."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from warn_v2.db.models import Company, Notice
from warn_v2.enrichment.agent import EnrichmentContext, EnrichmentResult
from warn_v2.enrichment.worker import enrich_batch, find_pending

__all__ = ["Company", "EnrichmentContext", "EnrichmentResult", "Notice"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _company(db, name="Acme Inc", **kw) -> Company:
    c = Company(name=name, **kw)
    db.add(c)
    db.flush()
    return c


def _notice(
    db, company_id: int, state="CA", notice_date=date(2026, 1, 15), layoff_count=None
) -> Notice:
    # Simple unique ID for test purposes
    nid = f"test_{state}_{notice_date}_{company_id}"
    n = Notice(
        notice_id=nid,
        state=state,
        employer="Acme Inc",
        notice_date=notice_date,
        layoff_count=layoff_count,
        company_id=company_id,
    )
    db.add(n)
    db.flush()
    return n


@dataclass
class _StubResult:
    proposed: bool = True
    website: str | None = "https://acme.com"
    sic_code: str | None = "3559"
    sic_desc: str | None = "Special Industry Machinery"
    duns: str | None = None
    confidence: float = 0.85
    sources: list = None  # type: ignore[assignment]
    last_message: str | None = None
    turns: int = 1

    def __post_init__(self):
        if self.sources is None:
            self.sources = ["https://acme.com"]


class _StubClient:
    """Returns a scripted EnrichmentResult; doesn't actually call the API."""

    def __init__(self, result: _StubResult | None = None) -> None:
        self._result = result or _StubResult()
        self.calls: list[EnrichmentContext] = []

    def create(self, **_: Any) -> Any:
        raise AssertionError("_StubClient.create should not be called directly")


def _stub_run(result: _StubResult | None = None):
    """Return a run_enrichment replacement that returns a fixed result."""
    stub = result or _StubResult()

    def _run(ctx: EnrichmentContext, client, **kw) -> EnrichmentResult:
        return EnrichmentResult(
            proposed=stub.proposed,
            website=stub.website,
            sic_code=stub.sic_code,
            sic_desc=stub.sic_desc,
            duns=stub.duns,
            confidence=stub.confidence,
            sources=stub.sources or [],
            last_message=stub.last_message,
            turns=stub.turns,
        )

    return _run


# ---------------------------------------------------------------------------
# find_pending tests
# ---------------------------------------------------------------------------

def test_find_pending_returns_unenriched(db) -> None:
    c = _company(db)
    db.commit()

    pending = find_pending(db)
    assert any(p.id == c.id for p in pending)


def test_find_pending_skips_enriched(db) -> None:
    from datetime import UTC, datetime
    c = _company(db, enriched_at=datetime.now(UTC), enrichment_confidence=Decimal("0.9"))
    db.commit()

    pending = find_pending(db)
    assert not any(p.id == c.id for p in pending)


def test_find_pending_rerun_below(db) -> None:
    from datetime import UTC, datetime
    low = _company(db, name="Low Conf", enriched_at=datetime.now(UTC),
                   enrichment_confidence=Decimal("0.5"))
    high = _company(db, name="High Conf", enriched_at=datetime.now(UTC),
                    enrichment_confidence=Decimal("0.9"))
    db.commit()

    pending = find_pending(db, rerun_below=0.7)
    ids = [p.id for p in pending]
    assert low.id in ids
    assert high.id not in ids


def test_find_pending_state_filter(db) -> None:
    ca_company = _company(db, name="CA Corp")
    tx_company = _company(db, name="TX Corp")
    db.flush()
    _notice(db, ca_company.id, state="CA")
    _notice(db, tx_company.id, state="TX")
    db.commit()

    pending = find_pending(db, state_filter="CA")
    ids = [p.id for p in pending]
    assert ca_company.id in ids
    assert tx_company.id not in ids


def test_find_pending_limit(db) -> None:
    for i in range(10):
        _company(db, name=f"Company {i}")
    db.commit()

    pending = find_pending(db, limit=3)
    assert len(pending) <= 3


def test_find_pending_orders_by_workers_affected(db) -> None:
    small = _company(db, name="Small Co")
    big = _company(db, name="Big Co")
    mid = _company(db, name="Mid Co")
    none = _company(db, name="No Notices Co")  # zero impact -> last
    db.flush()
    _notice(db, small.id, layoff_count=10)
    _notice(db, big.id, layoff_count=500)
    _notice(db, big.id, notice_date=date(2026, 2, 1), layoff_count=300)  # big sums to 800
    _notice(db, mid.id, layoff_count=100)
    db.commit()

    ids = [p.id for p in find_pending(db)]
    # Big (800) > Mid (100) > Small (10) > None (0)
    assert ids.index(big.id) < ids.index(mid.id) < ids.index(small.id) < ids.index(none.id)


def test_find_pending_limit_takes_highest_impact(db) -> None:
    small = _company(db, name="Small Co")
    big = _company(db, name="Big Co")
    db.flush()
    _notice(db, small.id, layoff_count=10)
    _notice(db, big.id, layoff_count=9000)
    db.commit()

    assert [p.id for p in find_pending(db, limit=1)] == [big.id]


def test_find_pending_impact_excludes_superseded(db) -> None:
    # A big layoff that's been superseded must not inflate the company's priority.
    sup_heavy = _company(db, name="Superseded-heavy Co")
    active_small = _company(db, name="Active-small Co")
    db.flush()
    big_sup = _notice(db, sup_heavy.id, layoff_count=9000)
    big_sup.is_superseded = True
    _notice(db, active_small.id, layoff_count=50)
    db.commit()

    ids = [p.id for p in find_pending(db)]
    # active_small (50) outranks sup_heavy (0 after excluding the superseded 9000)
    assert ids.index(active_small.id) < ids.index(sup_heavy.id)


def test_find_pending_orders_by_recency(db) -> None:
    old = _company(db, name="Old Notice Co")
    new = _company(db, name="New Notice Co")
    mid = _company(db, name="Mid Notice Co")
    none = _company(db, name="No Notices Co")  # no dated notices -> last
    db.flush()
    _notice(db, old.id, notice_date=date(2025, 3, 1), layoff_count=9000)
    _notice(db, new.id, notice_date=date(2026, 6, 15), layoff_count=5)
    _notice(db, mid.id, notice_date=date(2026, 1, 10), layoff_count=50)
    # An older second notice must not drag "new" down: recency = max(notice_date).
    _notice(db, new.id, notice_date=date(2024, 1, 1), layoff_count=5)
    db.commit()

    ids = [p.id for p in find_pending(db, order_by="recency")]
    # new (2026-06-15) > mid (2026-01-10) > old (2025-03-01) > none
    assert ids.index(new.id) < ids.index(mid.id) < ids.index(old.id) < ids.index(none.id)


def test_find_pending_recency_excludes_superseded(db) -> None:
    # A superseded fresh notice must not make a stale company look recent.
    stale = _company(db, name="Stale Co")
    active = _company(db, name="Active Co")
    db.flush()
    fresh_sup = _notice(db, stale.id, notice_date=date(2026, 6, 20), layoff_count=10)
    fresh_sup.is_superseded = True
    _notice(db, stale.id, notice_date=date(2025, 1, 1), layoff_count=10)
    _notice(db, active.id, notice_date=date(2026, 5, 1), layoff_count=10)
    db.commit()

    ids = [p.id for p in find_pending(db, order_by="recency")]
    assert ids.index(active.id) < ids.index(stale.id)


def test_find_pending_exclude_ids(db) -> None:
    a = _company(db, name="A Co")
    b = _company(db, name="B Co")
    db.commit()

    ids = [p.id for p in find_pending(db, exclude_ids={a.id})]
    assert a.id not in ids
    assert b.id in ids


def test_find_pending_rejects_unknown_order(db) -> None:
    import pytest

    with pytest.raises(ValueError):
        find_pending(db, order_by="alphabetical")


# ---------------------------------------------------------------------------
# enrich_batch tests
# ---------------------------------------------------------------------------

def test_enrich_batch_persists_result(db, monkeypatch) -> None:
    monkeypatch.setattr("warn_v2.enrichment.worker.run_enrichment", _stub_run())
    c = _company(db)
    db.commit()

    stats = enrich_batch(db, _StubClient())
    assert stats["enriched"] == 1
    assert stats["skipped"] == 0

    db.refresh(c)
    assert c.website == "https://acme.com"
    assert c.sic_code == "3559"
    assert c.enrichment_confidence == Decimal("0.85")
    assert c.enriched_at is not None
    assert json.loads(c.enrichment_sources or "[]") == ["https://acme.com"]
    assert c.enrichment_source == "claude"


def test_enrich_batch_idempotent(db, monkeypatch) -> None:
    """Re-running skips already-enriched companies."""
    monkeypatch.setattr("warn_v2.enrichment.worker.run_enrichment", _stub_run())
    _company(db)
    db.commit()

    stats1 = enrich_batch(db, _StubClient())
    assert stats1["enriched"] == 1

    # Second run: company is now enriched_at IS NOT NULL
    stats2 = enrich_batch(db, _StubClient())
    assert stats2["total"] == 0
    assert stats2["enriched"] == 0


def test_enrich_batch_recent_limit_works_both_ends(db, monkeypatch) -> None:
    """recent_limit adds a recency-ordered batch, deduped against the impact
    batch — a company that is both biggest and most recent occupies one impact
    slot and the recency batch tops up with the next-most-recent."""
    order: list[str] = []

    def _recording_run(ctx, client, **kw):
        order.append(ctx.company_name)
        return _stub_run()(ctx, client, **kw)

    monkeypatch.setattr("warn_v2.enrichment.worker.run_enrichment", _recording_run)

    big_old = _company(db, name="Big Old")  # impact 900, stale
    big_new = _company(db, name="Big New")  # impact 500 AND newest -> overlap candidate
    small_new = _company(db, name="Small New")  # impact 50, fresh
    small_mid = _company(db, name="Small Mid")  # impact 10, mid-age
    db.flush()
    _notice(db, big_old.id, notice_date=date(2025, 1, 1), layoff_count=900)
    _notice(db, big_new.id, notice_date=date(2026, 6, 1), layoff_count=500)
    _notice(db, small_new.id, notice_date=date(2026, 6, 15), layoff_count=50)
    _notice(db, small_mid.id, notice_date=date(2026, 3, 1), layoff_count=10)
    db.commit()

    stats = enrich_batch(db, _StubClient(), limit=2, recent_limit=2, inter_delay_s=0)

    # Impact batch: Big Old (900), Big New (500). Recency batch: Small New
    # (2026-06-15), then — Big New already taken — Small Mid (2026-03-01).
    assert stats["total"] == 4
    assert stats["enriched"] == 4
    assert order == ["Big Old", "Big New", "Small New", "Small Mid"]


def test_enrich_batch_counts_skipped_on_no_propose(db, monkeypatch) -> None:
    """When agent doesn't finalize, company counts as skipped."""
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        _stub_run(_StubResult(proposed=False)),
    )
    _company(db)
    db.commit()

    stats = enrich_batch(db, _StubClient())
    assert stats["skipped"] == 1
    assert stats["enriched"] == 0


def test_enrich_batch_dry_run_does_not_persist(db, monkeypatch) -> None:
    monkeypatch.setattr("warn_v2.enrichment.worker.run_enrichment", _stub_run())
    c = _company(db)
    db.commit()

    stats = enrich_batch(db, _StubClient(), dry_run=True)
    assert stats["enriched"] == 1

    db.refresh(c)
    assert c.enriched_at is None
    assert c.website is None


def test_enrich_batch_empty_when_no_pending(db, monkeypatch) -> None:
    monkeypatch.setattr("warn_v2.enrichment.worker.run_enrichment", _stub_run())
    stats = enrich_batch(db, _StubClient())
    assert stats["total"] == 0
    assert stats["enriched"] == 0
    assert stats["skipped"] == 0


def test_enrich_batch_rerun_below(db, monkeypatch) -> None:
    from datetime import UTC, datetime
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        _stub_run(_StubResult(confidence=0.9)),
    )
    c = _company(db, enriched_at=datetime.now(UTC), enrichment_confidence=Decimal("0.5"))
    db.commit()

    stats = enrich_batch(db, _StubClient(), rerun_below=0.7)
    assert stats["enriched"] == 1
    db.refresh(c)
    assert c.enrichment_confidence == Decimal("0.90")


# ---------------------------------------------------------------------------
# Cascade tier tests
# ---------------------------------------------------------------------------


def test_find_pending_recent_years(db) -> None:
    """recent_years only returns companies with notices in the last N years."""
    recent_co = _company(db, name="Recent Corp")
    old_co = _company(db, name="Old Corp")
    db.flush()
    _notice(db, recent_co.id, state="CA", notice_date=date(2025, 6, 1))   # ~1 year ago
    _notice(db, old_co.id, state="CA", notice_date=date(2020, 1, 1))       # ~6 years ago
    db.commit()

    pending = find_pending(db, recent_years=2)
    ids = [p.id for p in pending]
    assert recent_co.id in ids
    assert old_co.id not in ids


def test_enrich_batch_provider_hit_skips_edgar_and_claude(db, monkeypatch) -> None:
    """When provider returns a result, EDGAR and Claude are never called."""
    from warn_v2.enrichment.provider import ProviderResult

    edgar_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup",
        lambda name, state=None: edgar_calls.append(name) or None,
    )
    claude_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        lambda ctx, client, **kw: claude_calls.append(ctx.company_name)
        or EnrichmentResult(proposed=False),
    )

    class _FakeProvider:
        def lookup(self, company_name: str, state):
            return ProviderResult(
                entity_name="Boeing Company",
                sic_code="3721",
                sic_desc="Aircraft & Parts",
                naics_code="336411",
                naics_desc="Aircraft Manufacturing",
                duns="009867000",
                website="https://boeing.com",
                employee_count=170000,
                parent_company_name="The Boeing Company",
                parent_duns="009867123",
                global_ultimate_name="The Boeing Company",
                hq_address="929 Long Bridge Dr, Arlington, VA 22202",
                confidence=0.95,
                sources=["https://provider.example.com"],
            )

        def close(self) -> None:
            pass

    c = _company(db, name="Boeing")
    db.commit()

    stats = enrich_batch(db, _StubClient(), provider=_FakeProvider(), inter_delay_s=0)
    assert stats == {"total": 1, "enriched": 1, "skipped": 0,
                     "provider": 1, "provider_miss": 0, "provider_rejected": 0,
                     "provider_dba": 0, "unsearchable": 0, "edgar": 0, "claude": 0,
                     "sibling": 0}
    assert edgar_calls == []
    assert claude_calls == []

    db.refresh(c)
    assert c.enrichment_source == "provider"
    assert c.sic_code == "3721"
    assert c.naics_code == "336411"
    assert c.duns == "009867000"
    assert c.website == "https://boeing.com"
    assert c.employee_count == 170000
    assert c.parent_company_name == "The Boeing Company"
    assert c.parent_duns == "009867123"
    assert c.global_ultimate_name == "The Boeing Company"
    assert c.hq_address == "929 Long Bridge Dr, Arlington, VA 22202"
    assert c.enriched_at is not None


def test_enrich_batch_edgar_hit_skips_claude(db, monkeypatch) -> None:
    """When provider is absent and EDGAR matches, Claude is never called."""
    from warn_v2.enrichment.lookup import LookupResult

    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup",
        lambda name, state=None: LookupResult(
            entity_name="General Electric",
            sic_code="3612",
            sic_desc="Power, Distribution & Specialty Transformers",
            naics_code="335311",
            naics_desc="Power, Distribution, and Specialty Transformer Manufacturing",
            confidence=0.85,
            sources=["https://efts.sec.gov/LATEST/search-index?q=General+Electric"],
        ),
    )
    claude_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        lambda ctx, client, **kw: claude_calls.append(ctx.company_name)
        or EnrichmentResult(proposed=False),
    )

    c = _company(db, name="General Electric")
    db.commit()

    stats = enrich_batch(db, _StubClient(), inter_delay_s=0)
    assert stats == {"total": 1, "enriched": 1, "skipped": 0,
                     "provider": 0, "provider_miss": 0, "provider_rejected": 0,
                     "provider_dba": 0, "unsearchable": 0, "edgar": 1, "claude": 0,
                     "sibling": 0}
    assert claude_calls == []

    db.refresh(c)
    assert c.enrichment_source == "edgar"
    assert c.sic_code == "3612"
    assert c.naics_code == "335311"
    assert c.duns is None  # EDGAR tier never sets DUNS
    assert c.enriched_at is not None


def test_enrich_batch_falls_through_to_claude(db, monkeypatch) -> None:
    """When no provider and EDGAR misses, Tier 3 Claude is called."""
    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup",
        lambda name, state=None: None,
    )
    monkeypatch.setattr("warn_v2.enrichment.worker.run_enrichment", _stub_run())

    c = _company(db, name="Acme Temp Services")
    db.commit()

    stats = enrich_batch(db, _StubClient(), inter_delay_s=0)
    assert stats == {"total": 1, "enriched": 1, "skipped": 0,
                     "provider": 0, "provider_miss": 0, "provider_rejected": 0,
                     "provider_dba": 0, "unsearchable": 0, "edgar": 0, "claude": 1,
                     "sibling": 0}

    db.refresh(c)
    assert c.enrichment_source == "claude"
    assert c.website == "https://acme.com"
    assert c.sic_code == "3559"
    assert c.enriched_at is not None


def test_enrich_batch_provider_gets_cleaned_search_name(db, monkeypatch) -> None:
    """Site designators are stripped from the name passed to provider + EDGAR."""
    edgar_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup",
        lambda name, state=None: edgar_calls.append(name) or None,
    )
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        lambda ctx, client, **kw: EnrichmentResult(proposed=False),
    )

    provider_calls: list[str] = []

    class _MissProvider:
        def lookup(self, company_name: str, state):
            provider_calls.append(company_name)
            return None

        def close(self) -> None:
            pass

    _company(db, name="Google - Bordeaux")
    db.commit()

    enrich_batch(db, _StubClient(), provider=_MissProvider(), inter_delay_s=0)
    assert provider_calls == ["Google"]
    assert edgar_calls == ["Google"]


# ---------------------------------------------------------------------------
# Provider-first flow: tiers + provider_attempted_at
# ---------------------------------------------------------------------------

class _MissProviderCounting:
    def __init__(self):
        self.calls: list[str] = []

    def lookup(self, company_name: str, state):
        self.calls.append(company_name)
        return None

    def close(self) -> None:
        pass


def test_provider_only_miss_stamps_and_stays_queued(db, monkeypatch) -> None:
    """Main flow: a D&B miss stamps the attempt, leaves the row unenriched,
    and never falls through to EDGAR/Claude."""
    edgar_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup",
        lambda name, state=None: edgar_calls.append(name) or None,
    )
    claude_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        lambda ctx, client, **kw: claude_calls.append(ctx.company_name)
        or EnrichmentResult(proposed=False),
    )

    c = _company(db, name="Mystery Corp")
    db.commit()

    provider = _MissProviderCounting()
    stats = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    assert stats["provider_miss"] == 1
    assert stats["enriched"] == 0
    assert stats["skipped"] == 0  # a miss is not a failure
    assert edgar_calls == []
    assert claude_calls == []

    db.refresh(c)
    assert c.enriched_at is None  # still queued for a backup pass
    assert c.provider_attempted_at is not None

    # Second provider-only run skips the already-attempted company entirely.
    stats2 = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    assert stats2["total"] == 0
    assert provider.calls == ["Mystery Corp"]


def test_provider_match_rejected_when_inconsistent_with_original(db, monkeypatch) -> None:
    """Certainty guard: an aggressively-stripped query that resolves to an
    unrelated company must NOT persist a DUNS — it's treated as a miss."""
    from warn_v2.enrichment.provider import ProviderResult

    class _WrongMatchProvider:
        def lookup(self, company_name: str, state):
            # The query found *a* company, but not the one we asked about.
            return ProviderResult(
                entity_name="Booz Allen Hamilton",
                duns="111111111",
                confidence=0.95,
            )

    c = _company(db, name="Peraton 1875 Explorer St Reston, VA 20190")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_WrongMatchProvider(), inter_delay_s=0,
        tiers={"provider"},
    )
    assert stats["provider_rejected"] == 1
    assert stats["provider"] == 0
    assert stats["enriched"] == 0

    db.refresh(c)
    assert c.duns is None  # the dubious DUNS was NOT persisted
    assert c.enriched_at is None
    assert c.provider_attempted_at is not None  # still stamped, won't be retried


def test_provider_match_accepted_when_consistent(db, monkeypatch) -> None:
    """A faithful match (shares a distinctive token with the original) persists."""
    from warn_v2.enrichment.provider import ProviderResult

    class _GoodMatchProvider:
        def lookup(self, company_name: str, state):
            return ProviderResult(
                entity_name="Peraton Inc.", duns="222222222", confidence=0.92,
            )

    c = _company(db, name="Peraton 1875 Explorer St Reston, VA 20190")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_GoodMatchProvider(), inter_delay_s=0,
        tiers={"provider"},
    )
    assert stats["provider"] == 1
    assert stats["provider_rejected"] == 0

    db.refresh(c)
    assert c.duns == "222222222"
    assert c.enrichment_source == "provider"


def test_generic_single_token_skips_provider_lookup(db, monkeypatch) -> None:
    """A name that cleans to a lone generic token is too risky to search — the
    provider is never called and the row is left as a miss."""
    provider_calls: list[str] = []

    class _SpyProvider:
        def lookup(self, company_name: str, state):
            provider_calls.append(company_name)
            return None

    c = _company(db, name="Alliance (Virgil Roberts)")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_SpyProvider(), inter_delay_s=0, tiers={"provider"},
    )
    assert provider_calls == []  # lookup skipped entirely
    assert stats["provider_miss"] == 1
    db.refresh(c)
    assert c.provider_attempted_at is not None  # stamped, won't churn


def test_backup_tiers_select_only_provider_attempted(db, monkeypatch) -> None:
    """--tiers edgar,claude only touches companies D&B has already tried."""
    from datetime import UTC, datetime

    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup", lambda name, state=None: None
    )
    claude_calls: list[str] = []

    def _fake_claude(ctx, client, **kw):
        claude_calls.append(ctx.company_name)
        return EnrichmentResult(
            proposed=True, website="https://x.example", confidence=0.9, sources=[]
        )

    monkeypatch.setattr("warn_v2.enrichment.worker.run_enrichment", _fake_claude)

    tried = _company(db, name="Tried Corp")
    tried.provider_attempted_at = datetime.now(UTC)
    _company(db, name="Untried Corp")
    db.commit()

    stats = enrich_batch(db, _StubClient(), inter_delay_s=0, tiers={"edgar", "claude"})
    assert stats["total"] == 1
    assert stats["claude"] == 1
    assert claude_calls == ["Tried Corp"]

    db.refresh(tried)
    assert tried.enrichment_source == "claude"


def test_provider_miss_retries_with_dba_trade_name(db) -> None:
    """When the legal-entity query misses and the filing carries a dba trade
    name, the trade name gets one retry lookup and a faithful hit persists."""
    from warn_v2.enrichment.provider import ProviderResult

    class _DbaProvider:
        def __init__(self):
            self.calls: list[str] = []

        def lookup(self, company_name: str, state):
            self.calls.append(company_name)
            if company_name == "Cardinal Health":
                return ProviderResult(
                    entity_name="Cardinal Health, Inc.", duns="333333333",
                    confidence=0.95,
                )
            return None

        def close(self) -> None:
            pass

    c = _company(db, name="Managed Services-IDS (dba Cardinal Health)")
    db.commit()

    provider = _DbaProvider()
    stats = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    assert provider.calls == ["Managed Services-IDS", "Cardinal Health"]
    assert stats["provider_dba"] == 1
    assert stats["provider_miss"] == 0
    assert stats["enriched"] == 1

    db.refresh(c)
    assert c.duns == "333333333"
    assert c.enrichment_source == "provider"
    assert c.provider_attempted_at is not None


def test_provider_miss_without_dba_makes_single_call(db) -> None:
    provider = _MissProviderCounting()
    _company(db, name="Mystery Corp")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    assert provider.calls == ["Mystery Corp"]
    assert stats["provider_miss"] == 1
    assert stats["provider_dba"] == 0


def test_dba_retry_match_rejected_when_inconsistent(db) -> None:
    """A dba retry hit must stay faithful to the TRADE name, or it's a miss."""
    from warn_v2.enrichment.provider import ProviderResult

    class _WrongDbaProvider:
        def lookup(self, company_name: str, state):
            if company_name == "Arc":
                return ProviderResult(
                    entity_name="Booz Allen Hamilton", duns="444444444",
                    confidence=0.95,
                )
            return None

        def close(self) -> None:
            pass

    c = _company(db, name="Good Sports Plus Ltd. dba Arc")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_WrongDbaProvider(), inter_delay_s=0,
        tiers={"provider"},
    )
    assert stats["provider_dba"] == 0
    assert stats["provider_miss"] == 1

    db.refresh(c)
    assert c.duns is None
    assert c.provider_attempted_at is not None


def test_dba_retry_unavailable_keeps_stamp_and_pauses(db) -> None:
    """The primary attempt was real, so an infrastructure failure on the dba
    retry keeps the stamp but pauses the provider for the rest of the run."""
    from warn_v2.enrichment.provider import ProviderUnavailable

    class _TrippingDbaProvider:
        def __init__(self):
            self.calls: list[str] = []

        def lookup(self, company_name: str, state):
            self.calls.append(company_name)
            if company_name == "Cardinal Health":
                raise ProviderUnavailable("session tripped")
            return None

        def close(self) -> None:
            pass

    c1 = _company(db, name="Managed Services-IDS (dba Cardinal Health)")
    c2 = _company(db, name="Second Corp")
    db.commit()

    provider = _TrippingDbaProvider()
    stats = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    # The retry tripped: c1's genuine primary attempt still counts as a miss,
    # and c2 is never tried (provider paused).
    assert provider.calls == ["Managed Services-IDS", "Cardinal Health"]
    assert stats["provider_miss"] == 1

    db.refresh(c1)
    db.refresh(c2)
    assert c1.provider_attempted_at is not None  # primary shot was real
    assert c2.provider_attempted_at is None  # untouched, stays queued


def test_unsearchable_query_skips_backup_tiers(db, monkeypatch) -> None:
    """Junk/truncated names must not burn EDGAR or Claude calls either."""
    edgar_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup",
        lambda name, state=None: edgar_calls.append(name) or None,
    )
    claude_calls: list[str] = []
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        lambda ctx, client, **kw: claude_calls.append(ctx.company_name)
        or EnrichmentResult(proposed=False),
    )

    from datetime import UTC, datetime
    junk = _company(db, name="#1349")
    junk.provider_attempted_at = datetime.now(UTC)
    db.commit()

    stats = enrich_batch(db, _StubClient(), inter_delay_s=0, tiers={"edgar", "claude"})
    assert edgar_calls == []
    assert claude_calls == []
    assert stats["unsearchable"] == 1
    assert stats["skipped"] == 0  # an unsearchable name must not fail the run
    assert stats["enriched"] == 0

    db.refresh(junk)
    assert junk.enriched_at is None


# ---------------------------------------------------------------------------
# Sibling propagation
# ---------------------------------------------------------------------------

def _provider_enriched(db, name: str, duns: str, confidence="0.95", **kw) -> Company:
    from datetime import UTC, datetime
    return _company(
        db, name=name, duns=duns, enrichment_source="provider",
        enriched_at=datetime.now(UTC), enrichment_confidence=Decimal(confidence),
        website="https://abm.example", sic_code="7349", naics_code="561720",
        employee_count=1000, parent_company_name="Parent Co",
        hq_address="1 Main St", **kw,
    )


def test_sibling_prepass_enriches_attempted_twin_without_provider_call(db) -> None:
    """The backlog case: a twin already stamped provider_attempted_at is
    invisible to provider-only find_pending — the pre-pass still enriches it,
    with no provider lookup spent."""
    from datetime import UTC, datetime

    donor = _provider_enriched(db, "ABM Industries Incorporated", "555555555")
    twin = _company(db, name="ABM Industries - 1120")
    twin.provider_attempted_at = datetime.now(UTC)
    db.commit()

    provider = _MissProviderCounting()
    stats = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    assert stats["sibling"] == 1
    assert provider.calls == []  # nothing left to look up

    db.refresh(twin)
    assert twin.enrichment_source == "sibling"
    assert twin.duns == donor.duns
    assert twin.website == donor.website
    assert twin.naics_code == donor.naics_code
    assert twin.enrichment_confidence == Decimal("0.90")  # capped below donor
    assert twin.enriched_at is not None
    assert json.loads(twin.enrichment_sources) == [f"sibling:company_id={donor.id}"]


def test_sibling_prepass_skips_conflicting_duns(db) -> None:
    """Two donors under one key with different DUNS = different legal entities
    (franchisees) — never propagate under that key."""
    # Both donors clean to the key 'hooters' but carry different DUNS.
    _provider_enriched(db, "Hooters - Austin", "111111111")
    _provider_enriched(db, "Hooters - Tampa", "222222222")
    twin = _company(db, name="Hooters - Alamo")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_MissProviderCounting(), inter_delay_s=0,
        tiers={"provider"},
    )
    assert stats["sibling"] == 0
    db.refresh(twin)
    assert twin.enrichment_source != "sibling"
    assert twin.duns is None


def test_sibling_prepass_skips_generic_key_and_non_provider_donors(db) -> None:
    from datetime import UTC, datetime

    # Generic single-token key ("services") never donates.
    _provider_enriched(db, "Services LLC", "333333333")
    generic_twin = _company(db, name="Services - Houston")
    # edgar/claude enrichments are guesses — never propagate them.
    edgar_donor = _company(
        db, name="Edgar Corp", enrichment_source="edgar",
        enriched_at=datetime.now(UTC), enrichment_confidence=Decimal("0.85"),
        sic_code="1234",
    )
    edgar_twin = _company(db, name="Edgar Corp - Plant 2")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_MissProviderCounting(), inter_delay_s=0,
        tiers={"provider"},
    )
    assert stats["sibling"] == 0
    db.refresh(generic_twin)
    db.refresh(edgar_twin)
    assert generic_twin.duns is None
    assert edgar_twin.enriched_at is None
    assert edgar_donor.enrichment_source == "edgar"


def test_sibling_propagates_in_run_after_fresh_provider_hit(db) -> None:
    """Two same-key rows in one batch: the provider is called once, the second
    row copies the first row's fresh hit."""
    from warn_v2.enrichment.provider import ProviderResult

    class _OneHitProvider:
        def __init__(self):
            self.calls: list[str] = []

        def lookup(self, company_name: str, state):
            self.calls.append(company_name)
            return ProviderResult(
                entity_name="Take 5 Oil Change LLC", duns="666666666",
                confidence=0.95,
            )

        def close(self) -> None:
            pass

    first = _company(db, name="Take 5 Oil Change #101")
    second = _company(db, name="Take 5 Oil Change #202")
    db.commit()

    provider = _OneHitProvider()
    stats = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    assert len(provider.calls) == 1  # one lookup covered both rows
    assert stats["provider"] == 1
    assert stats["sibling"] == 1

    db.refresh(first)
    db.refresh(second)
    duns = {first.duns, second.duns}
    assert duns == {"666666666"}
    sources = {first.enrichment_source, second.enrichment_source}
    assert sources == {"provider", "sibling"}


def test_sibling_prepass_requires_faithful_match(db) -> None:
    """A cleaned_key collision made only of generic tokens is not evidence the
    rows are the same company — the faithfulness guard blocks propagation."""
    donor = _provider_enriched(db, "National Staffing Inc", "777777777")
    # Same key ('national staffing') but every shared token is generic.
    twin = _company(db, name="National Staffing - Dallas")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_MissProviderCounting(), inter_delay_s=0,
        tiers={"provider"},
    )
    assert stats["sibling"] == 0
    db.refresh(twin)
    assert twin.duns is None
    assert donor.duns == "777777777"


def test_sibling_prepass_dry_run_writes_nothing(db) -> None:
    from datetime import UTC, datetime

    _provider_enriched(db, "ABM Industries Incorporated", "555555555")
    twin = _company(db, name="ABM Industries - 1120")
    twin.provider_attempted_at = datetime.now(UTC)
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_MissProviderCounting(), inter_delay_s=0,
        tiers={"provider"}, dry_run=True,
    )
    assert stats["sibling"] >= 1  # counted...
    db.refresh(twin)
    assert twin.enriched_at is None  # ...but nothing written
    assert twin.duns is None
    assert twin.enrichment_source is None


def test_provider_only_dry_run_does_not_stamp(db) -> None:
    c = _company(db, name="Dry Corp")
    db.commit()

    enrich_batch(
        db, _StubClient(), provider=_MissProviderCounting(), inter_delay_s=0,
        tiers={"provider"}, dry_run=True,
    )
    db.refresh(c)
    assert c.provider_attempted_at is None


def test_full_cascade_still_falls_through(db, monkeypatch) -> None:
    """Explicit full-cascade keeps the old behavior (and stamps the attempt)."""
    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup", lambda name, state=None: None
    )
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        lambda ctx, client, **kw: EnrichmentResult(
            proposed=True, website="https://y.example", confidence=0.9, sources=[]
        ),
    )

    c = _company(db, name="Fallthrough Corp")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_MissProviderCounting(), inter_delay_s=0,
        tiers={"provider", "edgar", "claude"},
    )
    assert stats["provider_miss"] == 1
    assert stats["claude"] == 1
    db.refresh(c)
    assert c.enrichment_source == "claude"
    assert c.provider_attempted_at is not None


def test_provider_unavailable_does_not_stamp_and_pauses_run(db, monkeypatch) -> None:
    """An infrastructure failure (session trip / cap / cooldown) must NOT burn a
    company's one provider shot: the row is left un-attempted (so a healthy run
    retries it), and the provider is not called again for the rest of the run."""
    from warn_v2.enrichment.provider import ProviderUnavailable

    class _UnavailableProvider:
        def __init__(self):
            self.calls: list[str] = []

        def lookup(self, company_name: str, state):
            self.calls.append(company_name)
            raise ProviderUnavailable("session tripped")

        def close(self) -> None:
            pass

    c1 = _company(db, name="Boeing Company")
    c2 = _company(db, name="Cisco Systems, Inc.")
    db.commit()

    provider = _UnavailableProvider()
    stats = enrich_batch(
        db, _StubClient(), provider=provider, inter_delay_s=0, tiers={"provider"}
    )
    # Nothing counted as a miss or skip; the provider was called once then paused.
    assert stats["provider_miss"] == 0
    assert stats["enriched"] == 0
    assert stats["skipped"] == 0
    assert provider.calls == ["Boeing Company"]  # second company never tried

    db.refresh(c1)
    db.refresh(c2)
    assert c1.provider_attempted_at is None  # NOT burned
    assert c2.provider_attempted_at is None

    # A subsequent healthy run still finds and attempts both (they were queued).
    healthy = _MissProviderCounting()
    stats2 = enrich_batch(
        db, _StubClient(), provider=healthy, inter_delay_s=0, tiers={"provider"}
    )
    assert stats2["total"] == 2
    assert sorted(healthy.calls) == ["Boeing Company", "Cisco Systems, Inc."]
    db.refresh(c1)
    assert c1.provider_attempted_at is not None  # now a genuine attempt stamps


def test_provider_unavailable_falls_through_to_backup_in_mixed_run(db, monkeypatch) -> None:
    """In a mixed run, an unavailable provider still lets EDGAR/Claude enrich the
    company — without stamping a (false) provider attempt."""
    from warn_v2.enrichment.provider import ProviderUnavailable

    monkeypatch.setattr(
        "warn_v2.enrichment.lookup.edgar_lookup", lambda name, state=None: None
    )
    monkeypatch.setattr(
        "warn_v2.enrichment.worker.run_enrichment",
        lambda ctx, client, **kw: EnrichmentResult(
            proposed=True, website="https://z.example", confidence=0.9, sources=[]
        ),
    )

    class _UnavailableProvider:
        def lookup(self, company_name: str, state):
            raise ProviderUnavailable("daily cap reached")

        def close(self) -> None:
            pass

    c = _company(db, name="Boeing Company")
    db.commit()

    stats = enrich_batch(
        db, _StubClient(), provider=_UnavailableProvider(), inter_delay_s=0,
        tiers={"provider", "edgar", "claude"},
    )
    assert stats["provider_miss"] == 0
    assert stats["claude"] == 1
    db.refresh(c)
    assert c.enrichment_source == "claude"
    assert c.provider_attempted_at is None  # provider never actually searched it
