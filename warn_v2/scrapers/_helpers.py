"""Shared coercers and small utilities used across state scrapers.

These exist so per-state scrapers stay tiny and the same date/int/string parsing
rules are applied consistently — when the self-heal agent regenerates a parser,
it only has to call these helpers rather than reinvent them.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import pandas as pd

__all__ = [
    "ColumnMap",
    "as_date",
    "as_int",
    "as_str",
    "city_from_address",
    "is_blank",
    "norm",
    "zip_from",
]


def norm(s: Any) -> str:
    """Lowercase, trim, collapse whitespace. Used for column lookup."""
    return " ".join(str(s).strip().lower().split())


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def as_date(value: Any) -> date | None:
    if is_blank(value):
        return None
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def as_int(value: Any) -> int | None:
    if is_blank(value):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def as_str(value: Any) -> str | None:
    if is_blank(value):
        return None
    s = str(value).strip()
    return s or None


def city_from_address(address: Any) -> str | None:
    """Best-effort: '123 Main St, San Diego, CA 92101' → 'San Diego'."""
    s = as_str(address)
    if not s:
        return None
    parts = [p.strip() for p in s.split(",")]
    if len(parts) >= 3:
        return parts[-2]
    return None


_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def zip_from(zip_value: Any, address: Any = None) -> str | None:
    """Return a 5-digit ZIP from an explicit field, falling back to scanning an address."""
    z = as_str(zip_value)
    if z:
        m = _ZIP_RE.search(z)
        if m:
            return m.group(1)
    a = as_str(address)
    if a:
        m = _ZIP_RE.search(a)
        if m:
            return m.group(1)
    return None


class ColumnMap:
    """Case-/whitespace-insensitive column lookup over a pandas DataFrame.

    Constructed once per parse(); `.get(row, ('notice date', 'date'))` returns the
    value at the first matching column name (or None).
    """

    def __init__(self, columns: pd.Index) -> None:
        self._map: dict[str, Any] = {norm(c): c for c in columns}

    def get(self, row: pd.Series, keys: tuple[str, ...]) -> Any:
        for key in keys:
            actual = self._map.get(key)
            if actual is not None and actual in row.index:
                return row[actual]
        return None

    def has(self, key: str) -> bool:
        return norm(key) in self._map
