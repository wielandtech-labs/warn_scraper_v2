"""Validation of scraper output before it reaches storage."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from warn_v2.scrapers.base import NoticeRow, StateScraper

log = logging.getLogger(__name__)

# WARN Act enacted August 4, 1988 — no valid notice can predate it.
_MIN_NOTICE_YEAR = 1988
# Allow notices up to 2 years in the future (advance-notice edge cases).
_MAX_NOTICE_YEAR_OFFSET = 2


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    reason: str | None = None
    row_count: int = 0


def validate(scraper: StateScraper, rows: list[NoticeRow]) -> ValidationResult:
    # 1. Strip rows with clearly impossible notice_dates first so the count
    #    check below applies to *valid* rows only.
    bad = _filter_bad_dates(rows)
    if bad:
        log.warning(
            "validate[%s]: filtered %d row(s) with invalid notice_date: %s",
            scraper.state,
            len(bad),
            bad[:5],
        )

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


def _filter_bad_dates(rows: list[NoticeRow]) -> list[str]:
    """Remove rows with impossible notice_dates in-place.

    A date is considered impossible when its year is before the WARN Act
    (1988) or more than two years in the future — both indicate a data-entry
    error rather than a legitimate notice.

    Returns a list of short descriptions of the dropped rows (for logging).
    Rows with ``notice_date=None`` are left untouched.
    """
    current_year = datetime.now(UTC).year
    max_year = current_year + _MAX_NOTICE_YEAR_OFFSET
    bad: list[str] = []
    valid: list[NoticeRow] = []
    for row in rows:
        nd = row.notice_date
        if nd is not None and (nd.year < _MIN_NOTICE_YEAR or nd.year > max_year):
            bad.append(f"{row.employer!r} notice_date={nd}")
        else:
            valid.append(row)
    rows[:] = valid
    return bad


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
