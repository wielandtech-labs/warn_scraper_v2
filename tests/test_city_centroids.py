"""Tests for the city centroid lookup module."""
from __future__ import annotations

from decimal import Decimal

import pytest

from warn_v2.geo import city_centroids


@pytest.fixture(autouse=True)
def _seed_test_centroids():
    """Replace the real cache with a tiny known-good fixture for each test."""
    # Keys use the canonical "{STATE}|{city_lower}" format.
    city_centroids.reload_for_testing({
        "CA|los angeles": (34.0549, -118.2426),
        "TX|austin": (30.2672, -97.7431),
        "AK|anchorage": (61.2181, -149.9003),
        "MA|boston": (42.3601, -71.0589),
        "WA|seattle": (47.6062, -122.3321),
    })
    yield
    # Reset so subsequent tests re-load from disk on first call.
    city_centroids._cache = None  # type: ignore[attr-defined]


def test_lookup_known_city():
    pair = city_centroids.lookup("CA", "Los Angeles")
    assert pair is not None
    assert pair[0] == pytest.approx(34.05, abs=0.01)
    assert pair[1] == pytest.approx(-118.24, abs=0.01)


def test_lookup_case_insensitive():
    """City name matching is case-insensitive."""
    assert city_centroids.lookup("TX", "austin") == city_centroids.lookup("TX", "Austin")
    assert city_centroids.lookup("AK", "ANCHORAGE") == city_centroids.lookup("AK", "Anchorage")


def test_lookup_state_case_insensitive():
    """State code matching is case-insensitive."""
    assert city_centroids.lookup("ma", "Boston") == city_centroids.lookup("MA", "Boston")


def test_lookup_unknown_city():
    assert city_centroids.lookup("CA", "Nowhereville") is None


def test_lookup_unknown_state():
    assert city_centroids.lookup("ZZ", "Los Angeles") is None


def test_lookup_none_state():
    assert city_centroids.lookup(None, "Seattle") is None


def test_lookup_none_city():
    assert city_centroids.lookup("WA", None) is None


def test_lookup_empty_strings():
    assert city_centroids.lookup("", "Seattle") is None
    assert city_centroids.lookup("WA", "") is None


def test_lookup_strips_whitespace():
    """Leading/trailing whitespace in city or state is ignored."""
    pair = city_centroids.lookup("  WA  ", "  Seattle  ")
    assert pair is not None
    assert pair[0] == pytest.approx(47.61, abs=0.01)


def test_lookup_decimal_returns_decimal():
    pair = city_centroids.lookup_decimal("MA", "Boston")
    assert pair is not None
    assert isinstance(pair[0], Decimal)
    assert isinstance(pair[1], Decimal)


def test_lookup_decimal_unknown_returns_none():
    assert city_centroids.lookup_decimal("ZZ", "Nowhere") is None
