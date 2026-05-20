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
