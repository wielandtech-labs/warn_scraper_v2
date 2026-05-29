from datetime import date

from warn_v2.pipeline.validate import validate
from warn_v2.scrapers.base import NoticeRow


class _StubScraper:
    state = "ZZ"
    source_url = "https://example.test/warn"
    expected_row_range = (2, 10)
    required_fields = frozenset({"employer", "notice_date"})

    def fetch(self):  # pragma: no cover - not exercised here
        raise NotImplementedError

    def parse(self, raw):  # pragma: no cover - not exercised here
        raise NotImplementedError


def _row(**kw) -> NoticeRow:
    base = {"state": "ZZ", "employer": "Acme", "notice_date": date(2026, 1, 1)}
    base.update(kw)
    return NoticeRow(**base)


def test_validate_ok_within_range() -> None:
    rows = [_row() for _ in range(5)]
    result = validate(_StubScraper(), rows)
    assert result.ok
    assert result.row_count == 5


def test_validate_fails_below_range() -> None:
    result = validate(_StubScraper(), [_row()])
    assert not result.ok
    assert "below expected min" in result.reason


def test_validate_fails_above_range() -> None:
    result = validate(_StubScraper(), [_row() for _ in range(20)])
    assert not result.ok
    assert "above expected max" in result.reason


def test_validate_fails_on_too_many_blank_required_fields() -> None:
    rows = [_row(employer="") for _ in range(5)]
    result = validate(_StubScraper(), rows)
    assert not result.ok
    assert "employer" in result.reason


# ---------------------------------------------------------------------------
# Date sanity checks
# ---------------------------------------------------------------------------


def test_validate_filters_far_future_notice_date() -> None:
    """The RI fat-finger case: year 2108 is silently dropped; rest passes."""
    rows = [_row() for _ in range(5)]
    rows.append(_row(notice_date=date(2108, 11, 1)))
    result = validate(_StubScraper(), rows)
    assert result.ok
    assert result.row_count == 5  # bad row was removed before count check


def test_validate_filters_pre_warn_act_date() -> None:
    """A notice dated before the WARN Act (pre-1988) is filtered out."""
    rows = [_row() for _ in range(5)]
    rows.append(_row(notice_date=date(1975, 6, 1)))
    result = validate(_StubScraper(), rows)
    assert result.ok
    assert result.row_count == 5


def test_validate_allows_near_future_date() -> None:
    """Dates up to 2 years in the future are valid (advance-notice filings)."""
    from datetime import UTC, datetime

    next_year = datetime.now(UTC).year + 1
    rows = [_row(notice_date=date(next_year, 1, 1)) for _ in range(5)]
    result = validate(_StubScraper(), rows)
    assert result.ok


def test_validate_fails_count_after_date_filter() -> None:
    """If bad-date rows push valid count below the minimum, validation fails."""
    # 1 good row + 1 bad-date row; _StubScraper.expected_row_range min is 2
    rows = [_row(), _row(notice_date=date(2108, 1, 1))]
    result = validate(_StubScraper(), rows)
    assert not result.ok
    assert "below expected min" in (result.reason or "")
