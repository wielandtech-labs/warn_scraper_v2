"""Tests for the ZIP centroid lookup module."""
from __future__ import annotations

from decimal import Decimal

import pytest

from warn_v2.geo import zip_centroids


@pytest.fixture(autouse=True)
def _seed_test_centroids():
    """Replace the real cache with a tiny known-good fixture for each test."""
    zip_centroids.reload_for_testing({
        "94607": (37.7944, -122.2724),  # Oakland CA
        "90028": (34.1019, -118.3267),  # Hollywood CA
        "10001": (40.7506, -73.9971),   # NYC (Chelsea)
        "94089": (37.4030, -122.0146),  # Sunnyvale CA
        "00501": (40.8154, -73.0451),   # Holtsville NY (IRS address)
    })
    yield
    # Re-prime to empty so subsequent tests that don't use this fixture see
    # the default-loaded version on first call.
    zip_centroids._cache = None  # type: ignore[attr-defined]


def test_lookup_known_zip():
    pair = zip_centroids.lookup("94607")
    assert pair is not None
    assert pair[0] == pytest.approx(37.79, abs=0.01)
    assert pair[1] == pytest.approx(-122.27, abs=0.01)


def test_lookup_unknown_zip():
    assert zip_centroids.lookup("99999") is None


def test_lookup_none():
    assert zip_centroids.lookup(None) is None
    assert zip_centroids.lookup("") is None


def test_lookup_strips_zip_plus_4():
    pair = zip_centroids.lookup("94607-1234")
    assert pair is not None
    assert pair[0] == pytest.approx(37.79, abs=0.01)


def test_lookup_zero_pads_short_zips():
    # The IRS uses 00501 — needs zero padding when given as "501"
    pair = zip_centroids.lookup("501")
    assert pair is not None


def test_lookup_rejects_non_digit():
    assert zip_centroids.lookup("abcde") is None
    assert zip_centroids.lookup("9460x") is None


def test_lookup_rejects_too_long():
    assert zip_centroids.lookup("946070") is None


def test_lookup_decimal_returns_decimal():
    pair = zip_centroids.lookup_decimal("94607")
    assert pair is not None
    assert isinstance(pair[0], Decimal)
    assert isinstance(pair[1], Decimal)


def test_lookup_decimal_unknown_returns_none():
    assert zip_centroids.lookup_decimal("99999") is None
