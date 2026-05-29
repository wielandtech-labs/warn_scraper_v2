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


def _notice(db, company_id: int, state="CA", notice_date=date(2026, 1, 15)) -> Notice:
    # Simple unique ID for test purposes
    nid = f"test_{state}_{notice_date}_{company_id}"
    n = Notice(
        notice_id=nid,
        state=state,
        employer="Acme Inc",
        notice_date=notice_date,
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
