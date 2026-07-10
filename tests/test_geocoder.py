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
    assert pair.source == "zip"


def test_geocode_city_tier_fallback_when_no_zip(monkeypatch):
    """When ZIP centroid misses, city centroid is returned."""
    # No ZIP provided, city centroid should kick in.
    pair = geocode(None, "Austin", "TX", None)
    assert pair is not None
    assert pair[0] == pytest.approx(Decimal("30.27"), abs=Decimal("0.01"))
    assert pair[1] == pytest.approx(Decimal("-97.74"), abs=Decimal("0.01"))
    assert pair.source == "city"


def test_geocode_city_tier_fallback_when_zip_unknown():
    """When ZIP is present but not in the table, city centroid is returned."""
    pair = geocode(None, "Boston", "MA", "99999")  # 99999 not in fixture
    assert pair is not None
    assert pair[0] == pytest.approx(Decimal("42.36"), abs=Decimal("0.01"))
    assert pair.source == "city"


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


# ---------------------------------------------------------------------------
# Bounding-box validation (out-of-state results fall through tiers)
# ---------------------------------------------------------------------------

def test_geocode_rejects_out_of_state_census_falls_to_zip(monkeypatch):
    """A census result outside the state's bbox (HQ address) is rejected;
    the ZIP tier (in-state) wins instead."""
    from warn_v2.geo import geocoder

    zip_centroids.reload_for_testing({"30301": (33.7490, -84.3880)})  # Atlanta GA
    # Census resolves the HQ address... in California.
    monkeypatch.setattr(
        geocoder, "_census_geocode",
        lambda *a, **k: (Decimal("37.7749"), Decimal("-122.4194"), None),
    )

    pair = geocode("1 Corporate Way", "Atlanta", "GA", "30301")
    assert pair is not None
    assert pair.source == "zip"
    assert pair[0] == pytest.approx(Decimal("33.75"), abs=Decimal("0.01"))


def test_geocode_rejects_out_of_state_zip_centroid():
    """An out-of-state ZIP (HQ zip in a GA row) must not pin the notice there."""
    zip_centroids.reload_for_testing({"94607": (37.7944, -122.2724)})  # Oakland CA

    # GA row carrying a California HQ ZIP, nothing else usable.
    pair = geocode(None, None, "GA", "94607")
    assert pair is None


def test_geocode_all_tiers_out_of_state_returns_none(monkeypatch):
    from warn_v2.geo import geocoder

    zip_centroids.reload_for_testing({"94607": (37.7944, -122.2724)})
    city_centroids.reload_for_testing({"CA|oakland": (37.8044, -122.2712)})
    monkeypatch.setattr(
        geocoder, "_census_geocode",
        lambda *a, **k: (Decimal("37.7749"), Decimal("-122.4194"), None),
    )

    assert geocode("1 Main St", "Oakland", "GA", "94607") is None


def test_geocode_unknown_state_skips_validation():
    """No bbox for the state -> results pass through unvalidated."""
    zip_centroids.reload_for_testing({"00901": (18.4655, -66.1057)})  # San Juan PR

    pair = geocode(None, None, "PR", "00901")
    assert pair is not None
    assert pair.source == "zip"


def test_in_state_bbox_alaska_antimeridian():
    """Aleutian islands west of the antimeridian have positive longitudes."""
    from warn_v2.geo.bbox import in_state_bbox

    assert in_state_bbox("AK", 61.2, -149.9)   # Anchorage
    assert in_state_bbox("AK", 52.8, 173.2)    # Attu Island (lon > 0)
    assert not in_state_bbox("AK", 33.7, -84.4)  # Atlanta


# ---------------------------------------------------------------------------
# County resolution (census tier carries it; ZIP/city tiers reverse-look-up)
# ---------------------------------------------------------------------------

def test_geocode_census_tier_carries_county(monkeypatch):
    from warn_v2.geo import geocoder

    monkeypatch.setattr(
        geocoder, "_census_geocode",
        lambda *a, **k: (Decimal("33.7490"), Decimal("-84.3880"), "Fulton"),
    )
    result = geocode("1 Main St", "Atlanta", "GA", "30301")
    assert result is not None
    assert result.source == "census"
    assert result.county == "Fulton"


def test_geocode_zip_tier_reverse_looks_up_county(monkeypatch):
    from warn_v2.geo import geocoder

    calls = []

    def _fake_lookup(lat, lon, state):
        calls.append((lat, lon, state))
        return "Alameda"

    monkeypatch.setattr(geocoder, "county_from_coords", _fake_lookup)
    result = geocode(None, "Oakland", "CA", "94607")
    assert result is not None
    assert result.source == "zip"
    assert result.county == "Alameda"
    assert calls == [(result.lat, result.lon, "CA")]


def test_geocode_scraper_county_wins_no_lookup(monkeypatch):
    """A caller-supplied county is echoed back; no reverse lookup happens."""
    from warn_v2.geo import geocoder

    def _boom(lat, lon, state):
        raise AssertionError("county_from_coords must not be called")

    monkeypatch.setattr(geocoder, "county_from_coords", _boom)
    result = geocode(None, "Oakland", "CA", "94607", "Alameda")
    assert result is not None
    assert result.county == "Alameda"


def test_geocode_county_stays_none_when_lookup_misses():
    """The conftest stub returns None → result.county is None, no crash."""
    result = geocode(None, "Oakland", "CA", "94607")
    assert result is not None
    assert result.county is None


# ---------------------------------------------------------------------------
# _county_from_geographies (Census payload parsing + state-FIPS validation)
# ---------------------------------------------------------------------------

def _census_counties_payload(basename: str, state_fips: str) -> dict:
    """Trimmed-down real response shape from geocoder/geographies/*."""
    return {
        "Counties": [
            {
                "GEOID": f"{state_fips}173",
                "STATE": state_fips,
                "BASENAME": basename,
                "NAME": f"{basename} County",
                "COUNTY": "173",
            }
        ]
    }


def test_county_from_geographies_extracts_names():
    from warn_v2.geo.geocoder import _county_from_geographies

    payload = _census_counties_payload("Sedgwick", "20")
    assert _county_from_geographies(payload, "KS") == ("Sedgwick County", "Sedgwick")


def test_county_from_geographies_full_name_disambiguates():
    """Independent cities keep their qualifier: NAME, not BASENAME, is first."""
    from warn_v2.geo.geocoder import _county_from_geographies

    payload = {
        "Counties": [
            {"GEOID": "24510", "STATE": "24", "BASENAME": "Baltimore",
             "NAME": "Baltimore city", "COUNTY": "510"}
        ]
    }
    assert _county_from_geographies(payload, "MD") == ("Baltimore city", "Baltimore")


def test_county_from_geographies_rejects_wrong_state_fips():
    """A DC address on the MD line resolving to a Maryland county is dropped."""
    from warn_v2.geo.geocoder import _county_from_geographies

    payload = _census_counties_payload("Prince George's", "24")  # MD
    assert _county_from_geographies(payload, "DC") is None
    assert _county_from_geographies(payload, "MD") == (
        "Prince George's County", "Prince George's"
    )


def test_county_from_geographies_handles_missing_layer():
    from warn_v2.geo.geocoder import _county_from_geographies

    assert _county_from_geographies({}, "KS") is None
    assert _county_from_geographies({"Counties": []}, "KS") is None
    assert _county_from_geographies({"Counties": [{"STATE": "20"}]}, "KS") is None
