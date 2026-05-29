"""Tests for the enrichment provider plugin interface."""
from __future__ import annotations

import sys
import types

import pytest

from warn_v2.enrichment.provider import EnrichmentProvider, ProviderResult, load_provider

# ---------------------------------------------------------------------------
# load_provider tests
# ---------------------------------------------------------------------------


def test_load_provider_returns_none_when_unset(monkeypatch):
    monkeypatch.delenv("ENRICHMENT_PROVIDER_MODULE", raising=False)
    assert load_provider() is None


def test_load_provider_returns_none_when_empty(monkeypatch):
    monkeypatch.setenv("ENRICHMENT_PROVIDER_MODULE", "")
    assert load_provider() is None


def test_load_provider_raises_on_missing_colon(monkeypatch):
    monkeypatch.setenv("ENRICHMENT_PROVIDER_MODULE", "mypackage.module")
    with pytest.raises(ValueError, match=r"pkg\.module:ClassName"):
        load_provider()


def test_load_provider_raises_on_empty_class_name(monkeypatch):
    monkeypatch.setenv("ENRICHMENT_PROVIDER_MODULE", "mypackage.module:")
    with pytest.raises(ValueError):
        load_provider()


def test_load_provider_instantiates_stub_class(monkeypatch):
    """Dynamically insert a stub module and verify load_provider returns an instance."""

    class _StubProvider:
        def lookup(self, company_name: str, state: str | None) -> ProviderResult | None:
            return None

        def close(self) -> None:
            pass

    # Insert the stub module into sys.modules so importlib can find it
    stub_mod = types.ModuleType("_test_stub_provider_mod")
    stub_mod.StubProvider = _StubProvider  # type: ignore[attr-defined]
    sys.modules["_test_stub_provider_mod"] = stub_mod

    monkeypatch.setenv("ENRICHMENT_PROVIDER_MODULE", "_test_stub_provider_mod:StubProvider")
    try:
        instance = load_provider()
        assert instance is not None
        assert isinstance(instance, EnrichmentProvider)
    finally:
        del sys.modules["_test_stub_provider_mod"]


def test_load_provider_raises_on_missing_protocol_method(monkeypatch):
    """A class missing the required protocol methods raises TypeError."""

    class _BadProvider:
        """Has lookup but no close."""
        def lookup(self, company_name: str, state: str | None) -> None:
            return None

    stub_mod = types.ModuleType("_test_bad_provider_mod")
    stub_mod.BadProvider = _BadProvider  # type: ignore[attr-defined]
    sys.modules["_test_bad_provider_mod"] = stub_mod

    monkeypatch.setenv("ENRICHMENT_PROVIDER_MODULE", "_test_bad_provider_mod:BadProvider")
    try:
        with pytest.raises(TypeError, match="EnrichmentProvider"):
            load_provider()
    finally:
        del sys.modules["_test_bad_provider_mod"]


# ---------------------------------------------------------------------------
# ProviderResult tests
# ---------------------------------------------------------------------------


def test_provider_result_defaults():
    r = ProviderResult(entity_name="Acme Corp")
    assert r.duns is None
    assert r.sic_code is None
    assert r.naics_code is None
    assert r.confidence == 0.0
    assert r.sources == []


def test_provider_result_full():
    r = ProviderResult(
        entity_name="Acme Robotics Inc",
        duns="123456789",
        sic_code="3559",
        sic_desc="Special Industry Machinery, NEC",
        naics_code="333249",
        naics_desc="Other Industrial Machinery Manufacturing",
        website="https://acme.com",
        confidence=0.90,
        sources=["https://provider.example.com/company/acme"],
    )
    assert r.duns == "123456789"
    assert r.sic_code == "3559"
    assert r.naics_code == "333249"
    assert r.confidence == 0.90
