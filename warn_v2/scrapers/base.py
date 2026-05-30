"""Scraper plugin contract.

Splitting `fetch()` (raw bytes from the live source) from `parse()` (pure function
on bytes) is the central V2 design choice — it lets the validator save raw inputs
that the self-heal agent can later replay against a regenerated parser.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol, runtime_checkable


class ScrapeFailed(Exception):
    """Raised by fetch() when the source can't be retrieved."""


class ParseFailed(Exception):
    """Raised by parse() when the raw bytes can't be interpreted."""


@dataclass(slots=True)
class NoticeRow:
    """One WARN notice as produced by a scraper, before storage normalization."""

    state: str
    employer: str
    notice_date: date | None = None
    effective_date: date | None = None
    layoff_count: int | None = None
    closure_type: str | None = None
    city: str | None = None
    county: str | None = None
    zip: str | None = None
    address: str | None = None
    naics_code: str | None = None
    source_url: str | None = None
    raw_notice_url: str | None = None
    extra: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class StateScraper(Protocol):
    """Per-state scraper plugin.

    Implementations live in `warn_v2.scrapers.states.{state_abbr_lower}` and
    register themselves via `warn_v2.scrapers.registry.register`.
    """

    state: str
    source_url: str
    expected_row_range: tuple[int, int]
    required_fields: frozenset[str]

    def fetch(self) -> bytes:
        """Retrieve the live source. Raise ScrapeFailed on network errors."""
        ...

    def parse(self, raw: bytes) -> list[NoticeRow]:
        """Pure function from raw bytes to notices. Raise ParseFailed on failure."""
        ...
