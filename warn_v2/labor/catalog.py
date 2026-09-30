"""BLS series-id catalog: (dataset, area, measure) -> the raw BLS series id.

The ``bls_series`` table stores rows keyed by the raw id, so this module is the
only place that knows how those ids are built. It is deliberately a code
catalog rather than a DB table: the id layouts are a property of the BLS
surveys, they change with the code that reads them, and keeping them here means
adding a survey costs a constant rather than a migration.

A wrong id does NOT error at the API — it comes back inside ``Results.series``
with an empty ``data`` list — so the ingester asserts every requested series
returned points, and ``tests/test_labor_catalog.py`` pins the layouts.

Three datasets:

* ``unemployment`` — CPS U-3/U-6 nationally, LAUS rates per state. BLS
  publishes no monthly state U-6, so state areas carry ``u3`` only.
* ``payrolls`` — CES all-employees levels, total nonfarm or by NAICS sector.
* ``jolts`` — layoffs & discharges, job openings and quits, nationally and per
  state. Not broken out by industry here; CES covers the industry view.
"""
from __future__ import annotations

from warn_v2.geo.geocoder import STATE_FIPS

DATASETS = ("unemployment", "payrolls", "jolts")

# --- unemployment ------------------------------------------------------------

# Unemployment rate, percent, seasonally adjusted (CPS).
US_U3_SERIES = "LNS14000000"
# U-6: unemployed + marginally attached + part time for economic reasons, as a
# percent of the labor force plus marginally attached. BLS's broadest published
# measure of labor underutilization.
US_U6_SERIES = "LNS13327709"

# LAUS publishes monthly state rates for the 50 states, DC and Puerto Rico.
# The other territories in STATE_FIPS (AS/GU/MP/VI) have no monthly series.
_NO_LAUS = frozenset({"AS", "GU", "MP", "VI"})
LAUS_AREAS: tuple[str, ...] = tuple(
    sorted(code for code in STATE_FIPS if code not in _NO_LAUS)
)


def laus_state_series(state: str) -> str:
    """LAUS seasonally-adjusted unemployment rate for a state.

    20 characters: "LA" + seasonal(1) + area_code(15) + measure(2), where a
    statewide area_code is "ST" + 2-digit FIPS + 13 zeros and measure 03 is the
    unemployment rate. California -> ``LASST060000000000003``.
    """
    fips = STATE_FIPS[state.upper()]
    return "LAS" + "ST" + fips + "0" * 11 + "03"


# --- payrolls ----------------------------------------------------------------

# All employees, thousands, seasonally adjusted, total nonfarm.
NATIONAL_PAYROLL_SERIES = "CES0000000001"

# NAICS sector id -> (CES supersector employment series, CES industry name).
# CES supersectors are broader than 2-digit NAICS in places (e.g. NAICS 54/55/56
# all roll into "Professional and business services") — the payload carries the
# CES name so the narrative attributes figures to the right aggregate. NAICS 11
# (Agriculture) has no CES coverage. All series ids verified against the live
# API 2026-07-10.
SECTOR_CES_SERIES: dict[str, tuple[str, str]] = {
    "21": ("CES1000000001", "Mining and logging"),
    "22": ("CES4422000001", "Utilities"),
    "23": ("CES2000000001", "Construction"),
    "31-33": ("CES3000000001", "Manufacturing"),
    "42": ("CES4142000001", "Wholesale trade"),
    "44-45": ("CES4200000001", "Retail trade"),
    "48-49": ("CES4300000001", "Transportation and warehousing"),
    "51": ("CES5000000001", "Information"),
    "52": ("CES5500000001", "Financial activities"),
    "53": ("CES5500000001", "Financial activities"),
    "54": ("CES6000000001", "Professional and business services"),
    "55": ("CES6000000001", "Professional and business services"),
    "56": ("CES6000000001", "Professional and business services"),
    "61": ("CES6500000001", "Private education and health services"),
    "62": ("CES6500000001", "Private education and health services"),
    "71": ("CES7000000001", "Leisure and hospitality"),
    "72": ("CES7000000001", "Leisure and hospitality"),
    "81": ("CES8000000001", "Other services"),
    "92": ("CES9000000001", "Government"),
}


# --- JOLTS -------------------------------------------------------------------

# JOLTS covers the 50 states and DC; no Puerto Rico.
#
# State JOLTS runs roughly nine months behind the national series: state
# estimates are model-based and republished on an annual cycle, so as of
# 2026-09 national LD ran through 2026-M07 while every state stopped at
# 2025-M12. That is normal, not a broken fetch — a state series queried for
# the current year alone comes back with an empty `data` list, exactly as a
# malformed id would. Always query a span that reaches back at least a year
# before concluding an id is wrong.
JOLTS_AREAS: tuple[str, ...] = tuple(a for a in LAUS_AREAS if a != "PR")

# Our measure name -> JOLTS data-element code. Levels (trailing "L"), in
# thousands, seasonally adjusted. Layoffs and discharges is the one directly
# comparable to a WARN notice: it counts separations that actually happened.
JOLTS_ELEMENTS: dict[str, str] = {
    "layoffs": "LD",
    "openings": "JO",
    "quits": "QU",
}


def jolts_series(measure: str, state: str | None = None) -> str:
    """JOLTS level series for a measure, nationally or for one state.

    21 characters: "JT" + seasonal(1) + industry(6) + state(2) + area(5) +
    size_class(2) + data_element(2) + rate_or_level(1). Total nonfarm, all
    size classes, seasonally adjusted, level. National layoffs and discharges
    -> ``JTS000000000000000LDL``; California -> ``JTS000000060000000LDL``.
    """
    element = JOLTS_ELEMENTS[measure]
    state_code = STATE_FIPS[state.upper()] if state else "00"
    return "JTS" + "000000" + state_code + "00000" + "00" + element + "L"


# --- resolution --------------------------------------------------------------

def measures(dataset: str, *, area: str = "US") -> tuple[str, ...]:
    """Measures that exist for a dataset in a given area, in display order."""
    if dataset == "unemployment":
        return ("u3", "u6") if area == "US" else ("u3",)
    if dataset == "payrolls":
        return ("employment",)
    if dataset == "jolts":
        return tuple(JOLTS_ELEMENTS)
    raise ValueError(f"unknown dataset {dataset!r}")


def series_id(
    dataset: str,
    *,
    area: str = "US",
    measure: str,
    industry: str | None = None,
) -> str | None:
    """Resolve one series id, or None when that combination isn't published."""
    area = area.upper()
    if dataset == "unemployment":
        if area == "US":
            return {"u3": US_U3_SERIES, "u6": US_U6_SERIES}.get(measure)
        if measure != "u3" or area not in LAUS_AREAS:
            return None
        return laus_state_series(area)
    if dataset == "payrolls":
        if measure != "employment" or area != "US":
            return None
        if industry is None:
            return NATIONAL_PAYROLL_SERIES
        mapping = SECTOR_CES_SERIES.get(industry)
        return mapping[0] if mapping else None
    if dataset == "jolts":
        if measure not in JOLTS_ELEMENTS:
            return None
        if area == "US":
            return jolts_series(measure)
        if area not in JOLTS_AREAS:
            return None
        return jolts_series(measure, area)
    raise ValueError(f"unknown dataset {dataset!r}")


def all_series() -> list[str]:
    """Every distinct series id the ingester should keep current.

    Deduplicated and sorted: several NAICS sectors share one CES supersector
    series, so the raw expansion contains repeats.
    """
    ids: set[str] = {US_U3_SERIES, US_U6_SERIES, NATIONAL_PAYROLL_SERIES}
    ids.update(laus_state_series(a) for a in LAUS_AREAS)
    ids.update(series for series, _name in SECTOR_CES_SERIES.values())
    for measure in JOLTS_ELEMENTS:
        ids.add(jolts_series(measure))
        ids.update(jolts_series(measure, a) for a in JOLTS_AREAS)
    return sorted(ids)
