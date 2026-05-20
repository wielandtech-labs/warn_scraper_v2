"""Validation of scraper output before it reaches storage."""
from __future__ import annotations

from dataclasses import dataclass

from warn_v2.scrapers.base import NoticeRow, StateScraper


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    reason: str | None = None
    row_count: int = 0


def validate(scraper: StateScraper, rows: list[NoticeRow]) -> ValidationResult:
    count = len(rows)
    low, high = scraper.expected_row_range
    if count < low:
        return ValidationResult(
            ok=False,
            reason=f"row count {count} below expected min {low}",
            row_count=count,
        )
    if count > high:
        return ValidationResult(
            ok=False,
            reason=f"row count {count} above expected max {high}",
            row_count=count,
        )
    missing = _missing_required(rows, scraper.required_fields)
    if missing:
        return ValidationResult(
            ok=False,
            reason=f"required fields blank in too many rows: {missing}",
            row_count=count,
        )
    return ValidationResult(ok=True, row_count=count)


_MAX_BLANK_RATIO = 0.1


def _missing_required(rows: list[NoticeRow], required: frozenset[str]) -> dict[str, int]:
    """Return {field: blank_count} for any required field that's blank in >10% of rows."""
    total = len(rows)
    if total == 0:
        return {}
    blanks: dict[str, int] = {f: 0 for f in required}
    for row in rows:
        for field in required:
            value = getattr(row, field, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                blanks[field] += 1
    return {f: n for f, n in blanks.items() if n / total > _MAX_BLANK_RATIO}
