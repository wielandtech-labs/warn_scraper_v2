"""Unit tests for NAICS sector grouping."""
from __future__ import annotations

from warn_v2.companies.naics import SECTOR_NAME, sector_for_code, sector_prefixes


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
