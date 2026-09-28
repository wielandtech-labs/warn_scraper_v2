"""Tests for the BLS series-id catalog.

These pin the two id layouts that are easy to get subtly wrong and impossible
to get an error out of: a malformed BLS series id comes back inside
`Results.series` with an empty `data` list, not as a failure. Every id here was
confirmed against the live API on 2026-09-28.
"""
from __future__ import annotations

import pytest

from warn_v2.labor import catalog


def test_laus_state_series_layout():
    # "LA" + seasonal(1) + area_code(15) + measure(2); statewide area codes are
    # "ST" + FIPS + 13 zeros, measure 03 = unemployment rate.
    assert catalog.laus_state_series("CA") == "LASST060000000000003"
    assert catalog.laus_state_series("PR") == "LASST720000000000003"
    assert all(len(catalog.laus_state_series(a)) == 20 for a in catalog.LAUS_AREAS)


def test_jolts_series_layout():
    # "JT" + seasonal(1) + industry(6) + state(2) + area(5) + size(2)
    # + element(2) + rate_or_level(1).
    assert catalog.jolts_series("layoffs") == "JTS000000000000000LDL"
    assert catalog.jolts_series("layoffs", "CA") == "JTS000000060000000LDL"
    assert catalog.jolts_series("quits") == "JTS000000000000000QUL"
    assert catalog.jolts_series("openings", "TX") == "JTS000000480000000JOL"
    for measure in catalog.JOLTS_ELEMENTS:
        assert len(catalog.jolts_series(measure)) == 21
        assert all(len(catalog.jolts_series(measure, a)) == 21 for a in catalog.JOLTS_AREAS)


def test_area_coverage_matches_what_bls_publishes():
    # LAUS covers the 50 states, DC and Puerto Rico; JOLTS has no Puerto Rico.
    assert len(catalog.LAUS_AREAS) == 52
    assert "PR" in catalog.LAUS_AREAS
    assert len(catalog.JOLTS_AREAS) == 51
    assert "PR" not in catalog.JOLTS_AREAS
    # Territories with no monthly series must not leak in from STATE_FIPS.
    for absent in ("GU", "AS", "MP", "VI"):
        assert absent not in catalog.LAUS_AREAS


def test_series_id_resolution():
    assert catalog.series_id("unemployment", measure="u3") == catalog.US_U3_SERIES
    assert catalog.series_id("unemployment", measure="u6") == catalog.US_U6_SERIES
    assert (
        catalog.series_id("unemployment", area="ca", measure="u3")
        == "LASST060000000000003"
    )
    assert (
        catalog.series_id("payrolls", measure="employment")
        == catalog.NATIONAL_PAYROLL_SERIES
    )
    assert (
        catalog.series_id("payrolls", measure="employment", industry="31-33")
        == "CES3000000001"
    )


@pytest.mark.parametrize(
    ("dataset", "kwargs"),
    [
        # BLS publishes no monthly state U-6.
        ("unemployment", {"area": "CA", "measure": "u6"}),
        # No LAUS monthly series for these territories.
        ("unemployment", {"area": "GU", "measure": "u3"}),
        # No JOLTS for Puerto Rico.
        ("jolts", {"area": "PR", "measure": "layoffs"}),
        # NAICS 11 (Agriculture) has no CES coverage.
        ("payrolls", {"measure": "employment", "industry": "11"}),
        # Payrolls are national only.
        ("payrolls", {"area": "CA", "measure": "employment"}),
    ],
)
def test_unpublished_combinations_resolve_to_none(dataset, kwargs):
    assert catalog.series_id(dataset, **kwargs) is None


def test_measures_vary_by_area():
    assert catalog.measures("unemployment") == ("u3", "u6")
    assert catalog.measures("unemployment", area="CA") == ("u3",)
    assert catalog.measures("jolts") == ("layoffs", "openings", "quits")


def test_all_series_is_deduplicated():
    ids = catalog.all_series()
    assert len(ids) == len(set(ids))
    # Several NAICS sectors share one CES supersector series (54/55/56 all map
    # to Professional and business services), so the raw expansion has repeats.
    assert len(catalog.SECTOR_CES_SERIES) > len(
        {s for s, _ in catalog.SECTOR_CES_SERIES.values()}
    )
    assert catalog.US_U3_SERIES in ids
    assert catalog.jolts_series("layoffs", "CA") in ids


def test_unknown_dataset_raises():
    with pytest.raises(ValueError):
        catalog.series_id("payroll_taxes", measure="x")
