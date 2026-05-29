"""Tests for the geocoder cascade (Census → ZIP centroid → city centroid)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from warn_v2.geo import city_centroids, zip_centroids
from warn_v2.geo.geocoder import geocode


@pytest.fixture(autouse=True)
def _seed_centroids():
    """Seed both centroid caches with fixture data; bypass live files."""
    zip_centroids.reload_for_testing({
        "94607": (37.7944, -122.2724),   # Oakland CA (ZIP known)
    })
    city_centroids.reload_for_testing({
        "TX|austin": (30.2672, -97.7431),    # city known, ZIP unknown
        "MA|boston": (42.3601, -71.0589),
    })
    yield
    zip_centroids._cache = None       # type: ignore[attr-defined]
    city_centroids._cache = None      # type: ignore[attr-defined]


def test_geocode_zip_tier_used_when_no_address():
    pair = geocode(None, "Oakland", "CA", "94607")
    assert pair is not None
    assert pair[0] == pytest.approx(Decimal("37.79"), abs=Decimal("0.01"))


def test_geocode_city_tier_fallback_when_no_zip(monkeypatch):
    """When ZIP centroid misses, city centroid is returned."""
    # No ZIP provided, city centroid should kick in.
    pair = geocode(None, "Austin", "TX", None)
    assert pair is not None
    assert pair[0] == pytest.approx(Decimal("30.27"), abs=Decimal("0.01"))
    assert pair[1] == pytest.approx(Decimal("-97.74"), abs=Decimal("0.01"))


def test_geocode_city_tier_fallback_when_zip_unknown():
    """When ZIP is present but not in the table, city centroid is returned."""
    pair = geocode(None, "Boston", "MA", "99999")  # 99999 not in fixture
    assert pair is not None
    assert pair[0] == pytest.approx(Decimal("42.36"), abs=Decimal("0.01"))


def test_geocode_returns_none_when_all_tiers_miss():
    """All three tiers miss → None (no crash)."""
    pair = geocode(None, "Nowhere", "ZZ", "00000")
    assert pair is None


def test_geocode_census_tier_skipped_when_no_address(monkeypatch):
    """Census geocoder is never called when address is None."""
    called = []

    def _fake_census(street, city, state, zip_code):
        called.append(street)
        return None

    monkeypatch.setattr(
        "warn_v2.geo.geocoder._census_geocode",
        _fake_census,
    )
    geocode(None, "Oakland", "CA", "94607")
    assert called == [], "Census geocoder should not be called when address is None"
