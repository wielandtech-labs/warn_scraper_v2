"""Unit tests for closure-type normalization."""
from __future__ import annotations

import pytest

from warn_v2.closure import normalize_closure_category


@pytest.mark.parametrize(
    "raw",
    [
        "Closure",
        "closure",
        "Plant Closure",
        "Permanent Closures",
        "Closing",
        "CL",          # Wisconsin / Indiana code
        " cl ",
        "Closure Permanent",   # CA EDD vocabulary
        "Closure Temporary",
    ],
)
def test_closure_variants(raw: str) -> None:
    assert normalize_closure_category(raw) == "Closure"


@pytest.mark.parametrize(
    "raw",
    [
        "Layoff",
        "layoff",
        "Temporary Layoff",
        "Lay Off",
        "Reduction in force",
        "RIF",
        "LO",          # Indiana code
        "WR",          # Wisconsin work-reduction code
        "Layoff Permanent",              # CA EDD vocabulary
        "Layoff Temporary",
        "Layoff Not known at this time",
    ],
)
def test_layoff_variants(raw: str) -> None:
    assert normalize_closure_category(raw) == "Layoff"


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "Unknown",
        "Other",
        "Layoff and Closure",   # ambiguous — names both
        "Layoff/Closure",
        "Closure or Layoff",
    ],
)
def test_unrecognized_or_ambiguous_is_none(raw: str | None) -> None:
    assert normalize_closure_category(raw) is None


def test_substring_codes_do_not_false_match() -> None:
    # "lo"/"wr"/"cl" only match as whole words, not inside other words.
    assert normalize_closure_category("Relocation") is None
    assert normalize_closure_category("Clerical change") is None
