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
                     "edgar": 0, "claude": 0}
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
                     "edgar": 1, "claude": 0}
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
                     "edgar": 0, "claude": 1}

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
