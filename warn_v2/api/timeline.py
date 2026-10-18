"""Time buckets shared by the /timelapse endpoints.

Both timelines group by calendar month in SQL (a string prefix of
``notice_date``, portable across SQLite and Postgres) and roll months up to the
requested bucket here, since a quarter isn't a string prefix. Each returns a
**contiguous** period range, so a quiet period is still a frame of the
time-lapse rather than silently skipped, which would make the scrubber's time
axis uneven.

Both are also cached in-process (``TTLCache`` below): the month grouping is
the expensive part (1.6-3 s on prod's ~80k notices) and the data only changes
when scrapes land, a few times a day. Each endpoint keeps two caches -- the
monthly rows per filter set, which every bucket rolls up from, and the
serialized body per (bucket, filter set), so a hit skips the SQL and the JSON
encoding. warn_v2.api.timeline_warm keeps the /timelapse defaults warm.
"""
from __future__ import annotations

import json
import threading
import time
import typing
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any, Literal

from sqlalchemy import String, cast, func

from warn_v2.db.models import Notice

Bucket = Literal["year", "quarter", "month"]

# "YYYY-MM" of notice_date.
month_col = func.substr(cast(Notice.notice_date, String), 1, 7)

# Scrapes land a few times a day; the warmer refreshes the defaults well
# inside this, so they never expire under a visitor.
TTL_S = 15 * 60


def json_bytes(body: Any) -> bytes:
    """Encode as JSONResponse does (compact, UTF-8), for caching the bytes."""
    return json.dumps(
        body, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


class TTLCache[T]:
    """Thread-safe in-process LRU with per-entry expiry (after logo_fetch's
    _TTLCache). Past ``max_entries`` -- or ``max_bytes``, counting ``len()`` of
    bytes values -- the least recently used entries are dropped first, so the
    defaults everyone opens outlast one-off filter combinations.

    Misses are single-flight per key: concurrent requests for a cold key wait
    for one computation instead of each running a multi-second query.

    A body rolled up from cached rows gets a fresh TTL of its own, so it can
    trail the database by up to twice ``TTL_S`` -- fine for data that changes
    a few times a day.
    """

    def __init__(self, max_entries: int, max_bytes: int | None = None) -> None:
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._data: OrderedDict[Hashable, tuple[float, T]] = OrderedDict()
        self._lock = threading.Lock()
        self._inflight: dict[Hashable, threading.Lock] = {}

    def _get(self, key: Hashable) -> tuple[bool, T | None]:
        with self._lock:
            hit = self._data.get(key)
            if hit is None or hit[0] <= time.monotonic():
                return False, None
            self._data.move_to_end(key)
            return True, hit[1]

    def get_or_compute(
        self, key: Hashable, compute: Callable[[], T], *, refresh: bool = False
    ) -> T:
        """Return the live value for ``key``, computing (and storing) it on a
        miss, on expiry, or when ``refresh`` is set."""
        if not refresh:
            found, value = self._get(key)
            if found:
                return value  # type: ignore[return-value]
        with self._lock:
            flight = self._inflight.setdefault(key, threading.Lock())
        with flight:
            found, value = (False, None) if refresh else self._get(key)
            if not found:
                value = compute()
                with self._lock:
                    self._data[key] = (time.monotonic() + TTL_S, value)
                    self._data.move_to_end(key)
                    while len(self._data) > self._max_entries or (
                        self._max_bytes is not None
                        and len(self._data) > 1
                        and self._size() > self._max_bytes
                    ):
                        self._data.popitem(last=False)
        with self._lock:
            self._inflight.pop(key, None)
        return value  # type: ignore[return-value]

    def _size(self) -> int:
        return sum(len(typing.cast(bytes, v)) for _, v in self._data.values())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


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
