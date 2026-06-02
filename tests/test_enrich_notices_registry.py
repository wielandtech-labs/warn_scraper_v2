"""Tests for the notice-enricher registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from warn_v2.enrich_notices.base import NoticeEnricher
from warn_v2.enrich_notices.registry import all_enrichers, get_enricher


def test_ga_enricher_is_registered() -> None:
    enricher = get_enricher("GA")
    assert enricher.state == "GA"
    # GAEnricher structurally satisfies the protocol.
    assert isinstance(enricher, NoticeEnricher)


def test_get_enricher_is_case_insensitive() -> None:
    assert get_enricher("ga").state == "GA"


def test_all_enrichers_includes_ga() -> None:
    states = {e.state for e in all_enrichers()}
    assert "GA" in states


def test_unknown_state_raises() -> None:
    with pytest.raises(KeyError):
        get_enricher("ZZ")


def test_ga_run_delegates_to_enrich_ga(monkeypatch: pytest.MonkeyPatch) -> None:
    """GAEnricher.run forwards every argument to enrich_ga()."""
    captured: dict = {}

    def fake_enrich_ga(**kwargs):
        captured.update(kwargs)
        return {"considered": 1, "enriched": 1, "pdf_fetched": 0,
                "skipped": 0, "errors": 0}

    monkeypatch.setattr("warn_v2.scripts.enrich_ga.enrich_ga", fake_enrich_ga)

    enricher = get_enricher("GA")
    stats = enricher.run(
        limit=7, dry_run=True, pdf_dir=Path("/tmp/pdfs"), request_delay=5.0
    )

    assert stats["enriched"] == 1
    assert captured == {
        "limit": 7,
        "dry_run": True,
        "pdf_dir": Path("/tmp/pdfs"),
        "request_delay": 5.0,
    }
