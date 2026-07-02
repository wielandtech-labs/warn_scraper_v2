"""as_int coercion — thousands separators and rejection of ambiguous strings."""
from __future__ import annotations

import pytest

from warn_v2.scrapers._helpers import as_int


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("42", 42),
        (42, 42),
        (42.0, 42),
        ("1,604", 1604),  # DC 2020 / comma-thousands cells
        ("9,236", 9236),
        ("1,234,567", 1234567),
        ("  55 ", 55),
        ("0", 0),
    ],
)
def test_as_int_parses(value, expected) -> None:
    assert as_int(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "TBD",
        "unknown",
        "50, 60",     # list, not a thousands group
        "27, 4",      # not a 3-digit group
        "1,60",       # malformed thousands group
        "9,236 Nationwide",  # trailing text stays unparsed
    ],
)
def test_as_int_rejects(value) -> None:
    assert as_int(value) is None
