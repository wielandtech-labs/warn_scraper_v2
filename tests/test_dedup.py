from datetime import date

from warn_v2.pipeline.dedup import notice_id
from warn_v2.scrapers.base import NoticeRow


def _row(**kw) -> NoticeRow:
    base = {"state": "CA", "employer": "Acme Inc", "notice_date": date(2026, 1, 15)}
    base.update(kw)
    return NoticeRow(**base)


def test_notice_id_is_stable() -> None:
    a = notice_id(_row())
    b = notice_id(_row())
    assert a == b


def test_notice_id_normalizes_whitespace_and_case() -> None:
    a = notice_id(_row(employer="Acme Inc"))
    b = notice_id(_row(employer="  acme   inc  "))
    assert a == b


def test_notice_id_differs_on_different_employer() -> None:
    assert notice_id(_row(employer="Acme Inc")) != notice_id(_row(employer="Beta Inc"))


def test_notice_id_differs_on_different_date() -> None:
    a = notice_id(_row(notice_date=date(2026, 1, 15)))
    b = notice_id(_row(notice_date=date(2026, 1, 16)))
    assert a != b


def test_notice_id_includes_location() -> None:
    a = notice_id(_row(city="Oakland", zip="94607"))
    b = notice_id(_row(city="San Jose", zip="95110"))
    assert a != b
