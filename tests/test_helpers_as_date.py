"""Tests for as_date year-range hardening (guards against source typos)."""
from __future__ import annotations

from datetime import date

from warn_v2.scrapers._helpers import as_date


def test_valid_dates_pass_through() -> None:
    assert as_date("2026-01-15") == date(2026, 1, 15)
    assert as_date("11/17/2025") == date(2025, 11, 17)


def test_blank_returns_none() -> None:
    assert as_date(None) is None
    assert as_date("") is None
    assert as_date("   ") is None


def test_unparseable_returns_none() -> None:
    assert as_date("not a date") is None


def test_corrupt_low_year_rejected() -> None:
    # The MT/RI prod bug: "0225" / "0204" parse to years 225 / 204.
    assert as_date("0225-11-17") is None
    assert as_date("0204-05-04") is None
    assert as_date(date(225, 11, 17)) is None


def test_far_future_year_rejected() -> None:
    assert as_date(date(3000, 1, 1)) is None


def test_boundary_years() -> None:
    # 1988 is the lower bound (inclusive); today+2 is the upper bound.
    assert as_date(date(1988, 1, 1)) == date(1988, 1, 1)
    assert as_date(date(1987, 12, 31)) is None
    future_ok = date(date.today().year + 2, 1, 1)
    assert as_date(future_ok) == future_ok
    future_bad = date(date.today().year + 3, 1, 1)
    assert as_date(future_bad) is None
