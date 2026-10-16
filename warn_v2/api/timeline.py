"""Time buckets shared by the /timelapse endpoints.

Both timelines group by calendar month in SQL (a string prefix of
``notice_date``, portable across SQLite and Postgres) and roll months up to the
requested bucket here, since a quarter isn't a string prefix. Each returns a
**contiguous** period range, so a quiet period is still a frame of the
time-lapse rather than silently skipped, which would make the scrubber's time
axis uneven.
"""
from __future__ import annotations

from typing import Literal

from sqlalchemy import String, cast, func

from warn_v2.db.models import Notice

Bucket = Literal["year", "quarter", "month"]

# "YYYY-MM" of notice_date.
month_col = func.substr(cast(Notice.notice_date, String), 1, 7)


def period_of(month: str, bucket: Bucket) -> str:
    """Roll a "YYYY-MM" month up to its bucket key: "YYYY", "YYYY-Qn" or
    "YYYY-MM"."""
    if bucket == "year":
        return month[:4]
    if bucket == "quarter":
        return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"
    return month


def _ordinal(period: str, bucket: Bucket) -> int:
    year = int(period[:4])
    if bucket == "year":
        return year
    if bucket == "quarter":
        return year * 4 + int(period[6]) - 1
    return year * 12 + int(period[5:7]) - 1


def _from_ordinal(n: int, bucket: Bucket) -> str:
    if bucket == "year":
        return str(n)
    if bucket == "quarter":
        return f"{n // 4}-Q{n % 4 + 1}"
    return f"{n // 12}-{n % 12 + 1:02d}"


def period_range(periods: set[str], bucket: Bucket) -> list[str]:
    """Every period from the earliest to the latest of ``periods``, in order."""
    if not periods:
        return []
    ords = [_ordinal(p, bucket) for p in periods]
    return [_from_ordinal(n, bucket) for n in range(min(ords), max(ords) + 1)]
