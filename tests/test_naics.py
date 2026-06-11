"""Unit tests for NAICS sector grouping."""
from __future__ import annotations

from warn_v2.companies.naics import (
    SECTOR_NAME,
    sector_for_code,
    sector_prefixes,
    subsector_for_code,
    subsector_name,
)
from warn_v2.companies.naics_subsectors import NAICS_SUBSECTORS


def test_sector_for_code_maps_prefix():
    assert sector_for_code("311999") == "31-33"
    assert sector_for_code("332710") == "31-33"
    assert sector_for_code("445110") == "44-45"
    assert sector_for_code("488111") == "48-49"
    assert sector_for_code("541511") == "54"
    assert sector_for_code("622110") == "62"


def test_sector_for_code_edge_cases():
    assert sector_for_code(None) is None
    assert sector_for_code("") is None
    assert sector_for_code("9") is None      # too short
    assert sector_for_code("99999") is None  # unknown prefix


def test_sector_prefixes():
    assert set(sector_prefixes("31-33")) == {"31", "32", "33"}
    assert set(sector_prefixes("44-45")) == {"44", "45"}
    assert sector_prefixes("54") == ["54"]
    assert sector_prefixes("bogus") is None
    assert sector_prefixes(None) is None


def test_sector_name_covers_all_ids():
    assert SECTOR_NAME["31-33"] == "Manufacturing"
    assert all(sid in SECTOR_NAME for sid in {"11", "44-45", "62", "92"})


def test_subsector_for_code():
    assert subsector_for_code("311999") == "311"
    assert subsector_for_code("458110") == "458"
    assert subsector_for_code("31") is None       # too short
    assert subsector_for_code(None) is None
    assert subsector_for_code("990000") is None    # 99 is not a known sector prefix


def test_subsector_name():
    assert subsector_name("311") == "Food Manufacturing"
    assert subsector_name("999") is None
    assert subsector_name(None) is None


def test_subsector_table_consistency():
    """Every subsector key is a 3-digit code whose sector prefix is known.

    Guards the static 2022 table against transcription errors (the filter relies
    on the 2-digit prefix mapping to a real sector).
    """
    for code, title in NAICS_SUBSECTORS.items():
        assert len(code) == 3 and code.isdigit(), code
        assert sector_for_code(code) is not None, f"{code}: prefix maps to no sector"
        assert title and title.strip(), f"{code}: empty title"
