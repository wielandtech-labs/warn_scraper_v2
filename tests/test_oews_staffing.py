"""Tests for the OEWS staffing-pattern loader and fetch-script parsing."""
from __future__ import annotations

import pytest

from warn_v2.labor import oews
from warn_v2.scripts.fetch_oews_staffing import _parse_sheet

# ---------------------------------------------------------------------------
# labor/oews loader
# ---------------------------------------------------------------------------

_SEED = {
    "occupations": {
        "51-4041": "Machinists",
        "51-1011": "First-Line Supervisors of Production Workers",
        "53-7062": "Laborers and Material Movers",
    },
    "levels": {
        "sector": {
            "31-33": {
                "title": "Manufacturing",
                "coverage": 12.0,
                "occs": [["51-4041", 8.0], ["53-7062", 4.0]],
            }
        },
        "naics3": {
            "312": {
                "title": "Beverage and Tobacco Product Manufacturing",
                "coverage": 6.5,
                "occs": [["53-7062", 6.5]],
            }
        },
        "naics4": {
            "3119": {
                "title": "Other Food Manufacturing",
                "coverage": 15.0,
                "occs": [["51-4041", 10.0], ["51-1011", 5.0]],
            }
        },
    },
}


@pytest.fixture()
def seeded():
    oews.reload_for_testing(_SEED, vintage="May 2025")
    yield
    # None (not {}) resets to the real bundled file — an empty-dict teardown
    # would pin every later test in the session to "no patterns".
    oews.reload_for_testing(None)


def test_lookup_prefers_most_specific_level(seeded):
    p = oews.lookup("311999")
    assert p is not None
    assert (p.naics_key, p.level) == ("3119", "4-digit")
    assert p.industry_title == "Other Food Manufacturing"
    assert p.coverage_pct == 15.0
    # (soc, title, pct) triples, pattern order preserved, titles resolved.
    assert p.occupations == [
        ("51-4041", "Machinists", 10.0),
        ("51-1011", "First-Line Supervisors of Production Workers", 5.0),
    ]


def test_lookup_falls_back_to_subsector_then_sector(seeded):
    # No naics4 "3121" entry → the 3-digit subsector matches.
    p = oews.lookup("312111")
    assert p is not None
    assert (p.naics_key, p.level) == ("312", "3-digit")

    # Neither "3359" nor "335" seeded → the sector range id matches.
    p = oews.lookup("335999")
    assert p is not None
    assert (p.naics_key, p.level) == ("31-33", "sector")
    assert p.occupations[0] == ("51-4041", "Machinists", 8.0)


def test_lookup_short_codes_work_at_their_level(seeded):
    assert oews.lookup("312").naics_key == "312"
    # 2-digit code: only the sector level applies.
    assert oews.lookup("31").naics_key == "31-33"


def test_lookup_rejects_junk(seeded):
    assert oews.lookup(None) is None
    assert oews.lookup("") is None
    assert oews.lookup("xx") is None
    assert oews.lookup("31-33") is None  # non-digit input; sector ids are internal
    assert oews.lookup("999999") is None  # unknown sector prefix


def test_lookup_rejects_99_pseudo_codes(seeded):
    # Provider "unclassified establishments" pseudo-code must never match a
    # pattern, even if a (stale) bundle contains OEWS 999xxx government rows.
    oews.reload_for_testing(
        {
            "occupations": {"33-3051": "Police and Sheriff's Patrol Officers"},
            "levels": {
                "sector": {},
                "naics3": {
                    "999": {"title": "Government", "coverage": 5.0,
                            "occs": [["33-3051", 5.0]]}
                },
                "naics4": {},
            },
        },
        vintage="May 2025",
    )
    assert oews.lookup("999990") is None
    assert oews.lookup("999") is None


def test_data_vintage_and_empty_cache(seeded):
    assert oews.data_vintage() == "May 2025"
    oews.reload_for_testing({}, vintage=None)
    assert oews.lookup("311999") is None
    assert oews.data_vintage() is None


def test_reload_none_resets_to_bundled_file():
    # After a None reset the next lookup loads the real committed bundle —
    # this also guards that the data file actually ships with the package.
    oews.reload_for_testing({}, vintage=None)
    oews.reload_for_testing(None)
    pattern = oews.lookup("311999")
    assert pattern is not None
    assert pattern.level in ("4-digit", "3-digit", "sector")
    assert oews.data_vintage() is not None


# ---------------------------------------------------------------------------
# scripts/fetch_oews_staffing parsing (no network)
# ---------------------------------------------------------------------------

_HEADER = ("NAICS", "NAICS_TITLE", "O_GROUP", "OCC_CODE", "OCC_TITLE", "PCT_TOTAL", "TOT_EMP")


def _row(naics, title, o_group, soc, occ_title, pct):
    return (naics, title, o_group, soc, occ_title, pct, 1)


def test_parse_sheet_filters_and_key_derivation():
    rows = [
        _HEADER,
        # Padded 4-digit key: "311900" → "3119".
        _row("311900", "Other Food Mfg", "detailed", "51-4041", "Machinists", 10.0),
        _row("311900", "Other Food Mfg", "detailed", "51-1011", "Supervisors", 5.0),
        # Aggregate rows are not staffing-pattern entries.
        _row("311900", "Other Food Mfg", "major", "51-0000", "Production", 60.0),
        _row("311900", "Other Food Mfg", "total", "00-0000", "All Occupations", 100.0),
        # Suppressed estimate ("**") and non-positive shares are skipped.
        _row("311900", "Other Food Mfg", "detailed", "51-9999", "Suppressed", "**"),
        _row("311900", "Other Food Mfg", "detailed", "51-9998", "Zero", 0),
        # Below the 0.5% floor.
        _row("311900", "Other Food Mfg", "detailed", "51-9997", "Rare", 0.3),
        # Non-digit combo codes are skipped defensively.
        _row("31-33A", "Combo", "detailed", "51-4041", "Machinists", 9.0),
    ]
    industries, titles = _parse_sheet(iter(rows), key_len=4)
    assert set(industries) == {"3119"}
    entry = industries["3119"]
    assert entry["title"] == "Other Food Mfg"
    assert entry["occs"] == [["51-4041", 10.0], ["51-1011", 5.0]]
    assert entry["coverage"] == 15.0
    assert titles == {"51-4041": "Machinists", "51-1011": "Supervisors"}


def test_parse_sheet_3digit_and_sector_keys():
    rows = [
        _HEADER,
        _row("113000", "Forestry and Logging", "detailed", "45-4022", "Logging Operators", 20.0),
        # Government rows (999xxx) are excluded at every digit level — keeping
        # them let provider pseudo-codes (999990) match the government pattern.
        _row("999000", "Government", "detailed", "33-3051", "Police Officers", 5.0),
    ]
    industries, _ = _parse_sheet(iter(rows), key_len=3)
    assert set(industries) == {"113"}

    rows = [
        _HEADER,
        _row("31-33", "Manufacturing", "detailed", "51-4041", "Machinists", 3.0),
        # The OEWS "99" government row is not one of our NAICS sectors.
        _row("99", "Government", "detailed", "11-1011", "Chief Executives", 1.0),
    ]
    industries, _ = _parse_sheet(iter(rows), key_len=None)
    assert set(industries) == {"31-33"}


def test_parse_sheet_prunes_to_top_n_by_share():
    occs = [
        _row("311900", "T", "detailed", f"51-40{i:02d}", f"Occ {i}", float(i))
        for i in range(1, 15)
    ]
    industries, _ = _parse_sheet(iter([_HEADER, *occs]), key_len=4)
    kept = industries["3119"]["occs"]
    assert len(kept) == 12  # top 12 of 14
    assert kept[0] == ["51-4014", 14.0]  # sorted by share, descending
    assert kept[-1] == ["51-4003", 3.0]


def test_parse_sheet_rejects_unknown_columns():
    with pytest.raises(RuntimeError, match="Unexpected OEWS columns"):
        _parse_sheet(iter([("FOO", "BAR"), ("x", "y")]), key_len=4)
